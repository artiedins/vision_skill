#!/usr/bin/env python3
import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from vlib import client, config, images, ledger, runs


@dataclass
class Request:
    model: str
    prompt: str
    image_paths: list = field(default_factory=list)
    system: str = None
    effort: str = "high"
    max_tokens: int = 4000
    schema: dict = None
    tag: str = ""
    json_mode: bool = False


def check_model(name):
    slug = config.resolve_model(name)
    if slug not in config.BY_SLUG:
        raise ValueError(f"{name!r} is not allowed. Choose from: " + ", ".join(config.BY_SLUG))
    return slug


def read_prompt(args):
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt == "-":
        return sys.stdin.read()
    return args.prompt or ""


def make_payload(request):
    slug = check_model(request.model)
    if not isinstance(request.prompt, str) or not request.prompt.strip():
        raise ValueError("provide a nonempty --prompt, --prompt-file or --prompt - for stdin")
    if type(request.max_tokens) is not int or request.max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")
    if request.effort not in ("none", "minimal", "low", "medium", "high", "default"):
        raise ValueError("unknown reasoning effort")
    prompt = request.prompt
    if request.json_mode and not request.schema:
        prompt += runs.JSON_INSTRUCTION
    return client.build_payload(slug, prompt, request.image_paths, system=request.system, effort=request.effort, max_tokens=request.max_tokens, schema=request.schema)


def saved_result(record):
    path = Path(record["run_json"])
    if not path.is_file():
        raise ValueError(f"completed request has a missing transcript: {path}; not spending again")
    data = json.loads(path.read_text(encoding="utf-8"))
    answer, _ = client.answer_of(data["response"])
    return {"meta": record, "answer": answer, "parsed": runs.extract_json(answer), "skipped": True}


def do_call(cfg, request, quiet=False, resume=False):
    payload = make_payload(request)
    fingerprint = runs.fingerprint(payload)
    if resume:
        previous = next((r for r in reversed(ledger.read(cfg)) if r.get("fingerprint") == fingerprint and r.get("success")), None)
        if previous:
            print(f"vision: skip {request.tag} (identical successful request)", file=sys.stderr)
            return saved_result(previous)
    probed = [images.probe(p) for p in request.image_paths]
    for meta in probed:
        meta.pop("exif", None)
    session = ledger.current_session(cfg)
    if session is None:
        session = ledger.start_session(cfg, note="automatically started by first paid request")
    name = runs.run_name(request.tag, payload["model"])
    meta = {
        "request_id": name,
        "fingerprint": fingerprint,
        "tag": request.tag,
        "session": session["id"],
        "model": payload["model"],
        "effort": request.effort,
        "max_tokens": request.max_tokens,
        "prompt": payload["messages"][-1]["content"][0]["text"],
        "image_paths": [str(Path(p).resolve()) for p in request.image_paths],
        "images": probed,
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_md": str(cfg.runs_dir() / f"{name}.md"),
        "run_json": str(cfg.runs_dir() / f"{name}.json"),
    }
    pending_path = cfg.state_dir / "pending.json"
    ledger.write_json(pending_path, meta)
    started = time.monotonic()
    try:
        body = client.chat(cfg, payload)
    except client.ApiError as exc:
        # Explicit request/auth rejections have no generation to retry. Ambiguous failures
        # (timeouts, 429s, 5xx) leave pending.json behind as a record of what was in flight.
        if exc.status in (400, 401, 403, 404, 405, 413, 415, 422):
            pending_path.unlink()
        raise
    if not isinstance(body, dict):
        raise ValueError("invalid API response; request remains pending")
    ledger.write_json(pending_path, dict(meta, response=body))
    answer, _ = client.answer_of(body)
    meta.update(client.usage_record(body, payload["model"]))
    meta["seconds"] = round(time.monotonic() - started, 2)
    structured = request.json_mode or request.schema is not None
    parsed = runs.extract_json(answer) if structured else None
    meta["success"] = bool(answer.strip()) and not body.get("error") and (meta["finish_reason"] in ("stop", "end_turn")) and (not structured or parsed is not None)
    runs.write_run(cfg, name, runs.request_record(payload), body, answer, meta)
    ledger.append(cfg, meta)
    if meta["cost"] is not None:
        pending_path.unlink()
    total = ledger.totals(cfg)
    print(
        f'vision: model={meta["model"]} cost={ledger.money(meta["cost"])} '
        f'session={ledger.money(total["cost_session"])} project={ledger.money(total["cost_total"])} '
        f'finish={meta["finish_reason"]} run={meta["run_md"]}',
        file=sys.stderr,
    )
    if meta["cost"] is None:
        # Unknown cost stays unknown; pending.json keeps the response so it can be reconciled later.
        print("vision: WARNING no reported cost; this call is excluded from totals until reconciled", file=sys.stderr)
    if not meta["success"]:
        raise ValueError("answer incomplete, refused, errored or not JSON as requested; saved and " "charged in ledger, not marked complete. No automatic retry.")
    if not quiet:
        print(json.dumps(parsed, indent=2, ensure_ascii=False) if structured else answer)
    return {"meta": meta, "answer": answer, "parsed": parsed, "skipped": False}


def cmd_models(cfg, args):
    catalog = client.catalog(cfg, refresh=args.refresh)
    rows = []
    for model in config.ALLOWED:
        entry = catalog.get(model.slug)
        rows.append(
            {
                "slug": model.slug,
                "tier": model.tier,
                "note": model.note,
                "available": entry is not None,
                "image_input": "image" in (entry or {}).get("architecture", {}).get("input_modalities", []),
                "pricing": (entry or {}).get("pricing"),
                "context_length": (entry or {}).get("context_length"),
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            price = row["pricing"] or {}
            print(f'{row["slug"]:36s} in/token={price.get("prompt", "?")} ' f'out/token={price.get("completion", "?")} image_input={row["image_input"]}')


def cmd_info(cfg, args):
    print(json.dumps([images.probe(p) for p in args.images], indent=2, ensure_ascii=False))


def cmd_prep(cfg, args):
    variants = images.variant_list(args.preset, box=args.box, long_edge=args.long_edge, scale=args.scale, contrast=args.contrast, sharpen=args.sharpen, quality=args.quality, name=args.name)
    results = []
    for src in args.images:
        results.extend(images.prepare(src, args.out, variants, max_long_edge=args.max_long_edge, prefix=args.prefix))
    if args.manifest:
        path = Path(args.manifest)
        if path.exists() or path.resolve() in [Path(p).resolve() for p in args.images]:
            raise ValueError("manifest would overwrite an existing file")
        ledger.write_json(path, {"variants": results})
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for item in results:
            print(f'{item["path"]}  {item["width"]}x{item["height"]}  {item["kilobytes"]} KB')


def request_from_args(args, model, prompt):
    return Request(
        model=model,
        prompt=prompt,
        image_paths=args.image,
        system=args.system,
        effort=args.effort,
        max_tokens=args.max_tokens,
        schema=runs.schema_from_file(args.schema) if args.schema else None,
        tag=args.tag or "",
        json_mode=args.json,
    )


def cmd_ask(cfg, args):
    do_call(cfg, request_from_args(args, args.model, read_prompt(args)), quiet=args.quiet)


def result_row(result, tag):
    meta = result["meta"]
    return {
        "tag": tag,
        "model": meta["model"],
        "cost": meta["cost"],
        "skipped": result["skipped"],
        "answer": result["parsed"] if result["parsed"] is not None else result["answer"],
        "run": meta["run_md"],
    }


def cmd_panel(cfg, args):
    models = [check_model(m.strip()) for m in args.models.split(",") if m.strip()]
    if not models or len(models) != len(set(models)):
        raise ValueError("panel needs a nonempty list of distinct allowed models")
    prompt = read_prompt(args)
    path = Path(args.out_dir or cfg.runs_dir()) / (runs.run_name(args.tag or "panel", "panel") + ".md")
    rows = []
    try:
        for model in models:
            request = request_from_args(args, model, prompt)
            result = do_call(cfg, request, quiet=True)
            rows.append(result_row(result, request.tag))
            lines = [f"# Panel: {len(rows)} of {len(models)} completed", "", prompt]
            for row in rows:
                lines += ["", f'## {row["model"]}, {ledger.money(row["cost"])}', "", json.dumps(row["answer"], indent=2) if not isinstance(row["answer"], str) else row["answer"]]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    finally:
        print(f"vision: panel {len(rows)}/{len(models)} completed; {path}", file=sys.stderr)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        elif not args.quiet:
            for row in rows:
                print(f'\n{row["model"]}:\n{row["answer"]}')


def batch_requests(args):
    path = Path(args.tasks).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data if isinstance(data, list) else data["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a nonempty JSON list")
    requests = []
    for index, task in enumerate(tasks, 1):
        model = check_model(task["model"])
        groups = [task.get("images", [])]
        if task.get("images_dir"):
            if task.get("images"):
                raise ValueError("use images or images_dir, not both")
            folder = path.parent / task["images_dir"]
            groups = [[str(p)] for p in sorted(folder.glob(task.get("glob", "*"))) if p.is_file()]
            if not groups:
                raise ValueError(f"no files match images_dir for task {index}")
        for group in groups:
            tag = task.get("tag") or f"task{index}"
            if task.get("images_dir"):
                tag += "_" + Path(group[0]).name
            requests.append(
                Request(
                    model=model,
                    prompt=task["prompt"],
                    image_paths=[str(path.parent / p) for p in group],
                    system=task.get("system"),
                    effort=task.get("effort", args.effort),
                    max_tokens=task.get("max_tokens", args.max_tokens),
                    schema=runs.schema_from_file(path.parent / task["schema"]) if task.get("schema") else None,
                    tag=tag,
                    json_mode=task.get("json", args.json),
                )
            )
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be positive")
    return requests[: args.limit] if args.limit is not None else requests


def cmd_batch(cfg, args):
    requests = batch_requests(args)
    before = ledger.totals(cfg)
    rows = []
    try:
        for request in requests:
            result = do_call(cfg, request, quiet=True, resume=not args.redo)
            rows.append(result_row(result, request.tag))
            if args.out:
                ledger.write_json(Path(args.out), rows)
    finally:
        after = ledger.totals(cfg)
        count = after["calls_total"] - before["calls_total"]
        cost = after["cost_total"] - before["cost_total"]
        print(f"vision: batch {len(rows)}/{len(requests)} completed, {count} newly recorded calls; " f"reported new cost {ledger.money(cost)}", file=sys.stderr)
        if after["pending"] or after["unknown_costs"]:
            print("vision: WARNING batch cost is incomplete; unresolved request/cost remains", file=sys.stderr)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        elif not args.quiet:
            for row in rows:
                print(f'{row["tag"]}: {row["answer"]}')


def cmd_start(cfg, args):
    session = ledger.start_session(cfg, note=args.note or "")
    print(f'vision: session {session["id"]}')


def cost_data(cfg):
    return ledger.totals(cfg)


def cmd_cost(cfg, args):
    data = cost_data(cfg)
    if args.json:
        print(json.dumps(data, indent=2))
        return
    print(f'session: {data["calls_session"]} calls, {ledger.money(data["cost_session"])} reported')
    print(f'project: {data["calls_total"]} calls, {ledger.money(data["cost_total"])} reported')
    if data["pending"] or data["unknown_costs"]:
        print("WARNING: totals are incomplete; an unresolved request or unknown cost remains")
    for model, entry in data["by_model"].items():
        print(f'{model}: {entry["calls"]} calls, {ledger.money(entry["cost"])} reported')


def cmd_status(cfg, args):
    try:
        account = client.credits(cfg)
    except client.ApiError as exc:
        account = {"error": str(exc)}
    print(
        json.dumps(
            {
                "env_file": str(cfg.env_file) if cfg.env_file else None,
                "api_key_present": bool(cfg.api_key),
                "management_key_present": bool(cfg.mgmt_key),
                "state_dir": str(cfg.state_dir),
                "session": ledger.current_session(cfg),
                "spend": cost_data(cfg),
                "account": account,
            },
            indent=2,
        )
    )


def cmd_spend(cfg, args):
    # Account usage from OpenRouter, by day. Includes jobs this ledger did not make.
    try:
        rows = client.activity(cfg)
        account = client.credits(cfg)
    except client.ApiError as exc:
        print(f"vision: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if rows is None:
        raise ValueError("spend needs OR_MGMNT_KEY (or OR_API_KEY) to read account usage")
    days = {}
    for row in rows:
        day = days.setdefault(row.get("date", "?")[:10], {"requests": 0, "usage": 0.0})
        day["requests"] += row.get("requests") or 0
        day["usage"] += row.get("usage") or 0.0
    ordered = sorted(days.items(), reverse=True)[: args.days]
    if args.json:
        print(json.dumps({"days": [{"date": d, **v} for d, v in ordered], "account": account}, indent=2))
        return
    for day, entry in ordered:
        print(f'{day}  {entry["requests"]:>6} requests  {ledger.money(entry["usage"])}')
    if account:
        remaining = account.get("total_credits", 0) - account.get("total_usage", 0)
        print(f'account: {ledger.money(account.get("total_usage"))} used of {ledger.money(account.get("total_credits"))}, {ledger.money(remaining)} left')


def build_parser():
    parser = argparse.ArgumentParser(description="OpenRouter vision calls, image prep and cost records")
    parser.add_argument("--state-dir")
    parser.add_argument("--env-file")
    parser.add_argument("--timeout", type=int, help="network timeout in seconds, default 300")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("status", cmd_status), ("cost", cmd_cost), ("models", cmd_models)):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true")
        if name == "models":
            p.add_argument("--refresh", action="store_true")
        p.set_defaults(func=func)
    p = sub.add_parser("spend", help="account usage by day from OpenRouter (management key)")
    p.add_argument("--days", type=int, default=7, help="how many recent days to show, default 7")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_spend)
    p = sub.add_parser("info", help="local dimensions and EXIF")
    p.add_argument("images", nargs="+")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_info)
    p = sub.add_parser("prep", help="oriented JPEG derivatives; never overwrite")
    p.add_argument("images", nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--preset", default="provider", choices=list(images.PRESETS))
    p.add_argument("--box", help="left,top,right,bottom as fractions of oriented source")
    p.add_argument("--long-edge", type=int, default=0, help="downsize only; implies one full/crop variant")
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--contrast", type=float, default=1.0)
    p.add_argument("--sharpen", type=float, default=1.0)
    p.add_argument("--quality", type=int, default=90)
    p.add_argument("--name")
    p.add_argument("--prefix", default="")
    p.add_argument("--max-long-edge", type=int, default=0)
    p.add_argument("--manifest")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_prep)
    for name in ("ask", "panel"):
        p = sub.add_parser(name)
        p.add_argument("--model" if name == "ask" else "--models", required=True)
        if name == "panel":
            p.add_argument("--out-dir")
        prompt = p.add_mutually_exclusive_group(required=True)
        prompt.add_argument("--prompt")
        prompt.add_argument("--prompt-file")
        p.add_argument("--image", action="append", default=[])
        p.add_argument("--system")
        p.add_argument("--effort", default="high", choices=["none", "minimal", "low", "medium", "high", "default"])
        p.add_argument("--max-tokens", type=int, default=4000)
        p.add_argument("--json", action="store_true")
        p.add_argument("--schema")
        p.add_argument("--tag")
        p.add_argument("--quiet", action="store_true")
        p.set_defaults(func=cmd_ask if name == "ask" else cmd_panel)
    p = sub.add_parser("batch")
    p.add_argument("tasks")
    p.add_argument("--out")
    p.add_argument("--limit", type=int)
    p.add_argument("--redo", action="store_true", help="intentionally repeat identical completed requests")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--effort", default="high")
    p.add_argument("--max-tokens", type=int, default=4000)
    p.set_defaults(func=cmd_batch)
    p = sub.add_parser("start")
    p.add_argument("--note")
    p.set_defaults(func=cmd_start)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        cfg = config.load_config(env_file=args.env_file, state_dir=args.state_dir, timeout=args.timeout)
        paid = args.command in ("ask", "panel", "batch")
        if paid and not cfg.api_key:
            raise ValueError("No API key found. Populate .env from .env.example with OR_API_KEY.")
        if paid or args.command == "start":
            with ledger.locked(cfg):
                args.func(cfg, args)
        else:
            args.func(cfg, args)
    except (ValueError, OSError, KeyError, TypeError, client.ApiError) as exc:
        print(f"vision: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
