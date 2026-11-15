#!/usr/bin/env python3
import argparse
import json
import os
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
    history: list = field(default_factory=list)
    thread: str = ""
    turn_number: int = 0


def check_model(name):
    slug = config.resolve_model(name)
    if slug not in config.BY_SLUG:
        raise ValueError(f"{name!r} is not allowed. Choose from: " + ", ".join(config.BY_SLUG))
    return slug


def endpoint_of(slug):
    return config.BY_SLUG[slug].endpoint


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
    return client.build_payload(
        slug,
        endpoint_of(slug),
        prompt,
        request.image_paths,
        system=request.system,
        effort=request.effort,
        max_tokens=request.max_tokens,
        schema=request.schema,
        history=request.history,
    )


def saved_result(cfg, record):
    path = runs.resolve_saved_path(record["run_json"], cfg)
    if not path.is_file():
        raise ValueError(f"completed request has a missing transcript: {path}; not spending again")
    data = json.loads(path.read_text(encoding="utf-8"))
    answer, _ = client.answer_of(data["response"])
    return {"meta": record, "answer": answer, "parsed": runs.extract_json(answer), "skipped": True}


def failure_message(meta, structured):
    # Name the actual cause so the next call can be fixed instead of guessed at. A truncated
    # reasoning-only answer is the common failure and reads as "not JSON" without this.
    finish = meta.get("finish_reason") or "no finish_reason"
    parts = [f"finish_reason={finish}"]
    if meta.get("reasoning_tokens"):
        spent = f"{meta['reasoning_tokens']} of max_tokens={meta.get('max_tokens')}"
        parts.append(f"reasoning_tokens={spent}")
    if structured:
        parts.append("no parseable JSON")
    if finish == "length":
        parts.append("raise --max-tokens or lower --effort")
    return f"answer incomplete or refused ({', '.join(parts)}); saved and charged, not marked complete"


def prompt_text_of(payload):
    last_content = payload["messages"][-1]["content"]
    if isinstance(last_content, str):
        return last_content
    return next((item.get("text", "") for item in last_content if item.get("type") == "text"), "")


def do_call(cfg, request, quiet=False, resume=False):
    payload = make_payload(request)
    fingerprint = runs.fingerprint(payload)
    if resume:
        previous = next((r for r in reversed(ledger.read(cfg)) if r.get("fingerprint") == fingerprint and r.get("success")), None)
        if previous:
            print(f"vision: skip {request.tag} (identical successful request)", file=sys.stderr)
            return saved_result(cfg, previous)
    probed = [images.probe(p) for p in request.image_paths]
    for meta_item in probed:
        meta_item.pop("exif", None)
    with ledger.locked(cfg):
        # Two parallel calls may both find no session; the lock makes one start it and the other
        # join, instead of each creating its own session id.
        session = ledger.current_session(cfg)
        if session is None:
            session = ledger.start_session(cfg, note="automatically started by first paid request")
    name = runs.run_name(request.tag or request.thread, payload["model"])
    run_md_abs = cfg.runs_dir() / f"{name}.md"
    run_json_abs = cfg.runs_dir() / f"{name}.json"
    meta = {
        "request_id": name,
        "fingerprint": fingerprint,
        "tag": request.tag,
        "session": session["id"],
        "model": payload["model"],
        "endpoint": payload["provider"]["only"][0],
        "effort": request.effort,
        "max_tokens": request.max_tokens,
        "prompt": prompt_text_of(payload),
        "image_paths": [runs.portable_path(p, cfg) for p in request.image_paths],
        "ephemeral_inputs": [runs.portable_path(p, cfg) for p in request.image_paths if Path(p).resolve().is_relative_to(Path("/tmp"))],
        "images": probed,
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_md": runs.portable_path(run_md_abs, cfg),
        "run_json": runs.portable_path(run_json_abs, cfg),
    }
    if request.thread:
        meta["thread"] = request.thread
        meta["turn"] = request.turn_number
    if os.environ.get("PQ_VISION_RUN_ID"):
        meta["harness_run"] = os.environ["PQ_VISION_RUN_ID"]
    pending_path = ledger.pending_path(cfg, name)
    ledger.write_json(pending_path, meta)
    started = time.monotonic()
    try:
        body = client.chat(cfg, payload)
    except client.ApiError as exc:
        # Explicit request/auth rejections have no generation to retry. Ambiguous failures
        # (timeouts, 429s, 5xx) leave the pending marker behind as a record of what was in flight.
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
    with ledger.locked(cfg):
        ledger.append(cfg, meta)
        if meta["cost"] is not None:
            pending_path.unlink()
        total = ledger.totals(cfg)
    thread_tag = f' thread={request.thread}#{request.turn_number}' if request.thread else ""
    print(
        f'vision: model={meta["model"]} endpoint={meta["endpoint"]} provider={meta.get("provider")}{thread_tag} '
        f'cost={ledger.money(meta["cost"])} '
        f'session={ledger.money(total["cost_session"])} total={ledger.money(total["cost_total"])} '
        f'finish={meta["finish_reason"]} run={run_md_abs}',
        file=sys.stderr,
    )
    if meta["cost"] is None:
        # Unknown cost stays unknown; the pending marker keeps the response for later reconciliation.
        print("vision: WARNING no reported cost; this call is excluded from totals until reconciled", file=sys.stderr)
    if not meta["success"]:
        raise ValueError(failure_message(meta, structured))
    if not quiet:
        print(json.dumps(parsed, indent=2, ensure_ascii=False) if structured else answer)
    return {"meta": meta, "answer": answer, "parsed": parsed, "skipped": False}


def per_million(pricing, field):
    try:
        return round(float(pricing[field]) * 1_000_000, 3)
    except (KeyError, TypeError, ValueError):
        return None


def cmd_models(cfg, args):
    catalog = client.catalog(cfg, refresh=args.refresh)
    endpoints = client.endpoints(cfg, refresh=args.refresh)
    rows = []
    for model in config.ALLOWED:
        entry = catalog.get(model.slug) or {}
        listed = (endpoints.get(model.slug) or {}).get("endpoints") or []
        pinned = next((e for e in listed if e.get("tag") == model.endpoint), None)
        rows.append(
            {
                "slug": model.slug,
                "label": model.label,
                "tier": model.tier,
                "endpoint": model.endpoint,
                "endpoint_listed": pinned is not None,
                "endpoint_status": (pinned or {}).get("status"),
                "endpoint_count": len(listed),
                "prompt_per_mtok": per_million((pinned or {}).get("pricing") or {}, "prompt"),
                "completion_per_mtok": per_million((pinned or {}).get("pricing") or {}, "completion"),
                "quantization": (pinned or {}).get("quantization"),
                "image_input": "image" in entry.get("architecture", {}).get("input_modalities", []),
                "note": model.note,
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    print(f'{"slug":35s} {"pinned endpoint":26s} {"health":>6s} {"in $/Mtok":>9s} {"out $/Mtok":>10s} img')
    for row in rows:
        flag = "" if row["endpoint_listed"] else "  <- PIN NOT LISTED"
        print(
            f'{row["slug"]:35s} {row["endpoint"]:26s} {str(row["endpoint_status"]):>6s} '
            f'{str(row["prompt_per_mtok"]):>9s} {str(row["completion_per_mtok"]):>10s} '
            f'{"yes" if row["image_input"] else "no"}{flag}'
        )
    missing = [row["slug"] for row in rows if not row["endpoint_listed"]]
    if missing:
        print("vision: WARNING pinned endpoint not in the live list for: " + ", ".join(missing), file=sys.stderr)
    print(
        "vision: health 0 is normal; nonzero is a provider-side status flag, not a routing block. "
        "Marketplace endpoint prices float live; billed spend comes from usage.cost.",
        file=sys.stderr,
    )


PROBE_PROMPT = "Image 1 is a test card. Reply on one line with the large number, the colour of the square " "on the left, and the shape on the right."


def cmd_probe(cfg, args):
    names = [m.strip() for m in (args.models or ",".join(config.BY_SLUG)).split(",") if m.strip()]
    models = [check_model(name) for name in names]
    if len(models) != len(set(models)):
        raise ValueError("probe needs a list of distinct allowed models")
    card = images.probe_card(cfg.state_dir / "probe_card.jpg")
    rows = []
    for model in models:
        request = Request(
            model=model,
            prompt=PROBE_PROMPT,
            image_paths=[card],
            effort=args.effort,
            max_tokens=args.max_tokens,
            tag="probe",
        )
        try:
            result = do_call(cfg, request, quiet=True)
            answer = result["answer"].strip()
            rows.append(
                {
                    "model": model,
                    "endpoint": endpoint_of(model),
                    "provider": result["meta"].get("provider"),
                    "routed": result["meta"].get("routing"),
                    "cost": result["meta"]["cost"],
                    "read_number": "42" in answer,
                    "answer": answer,
                    "run": str(runs.resolve_saved_path(result["meta"]["run_md"], cfg)),
                }
            )
        except (ValueError, client.ApiError) as exc:
            # A rejected pin, an exhausted reasoning budget or an empty answer: report and continue.
            rows.append({"model": model, "endpoint": endpoint_of(model), "error": str(exc)})
            print(f"vision: probe {model} failed: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    for row in rows:
        if "error" in row:
            print(f'{row["model"]:35s} {row["endpoint"]:26s} FAILED  {row["error"][:120]}')
        else:
            print(f'{row["model"]:35s} {row["endpoint"]:26s} ok  provider={row["provider"]} ' f'number_read={"yes" if row["read_number"] else "no"} cost={ledger.money(row["cost"])}')


def cmd_info(cfg, args):
    print(json.dumps([images.probe(p) for p in args.images], indent=2, ensure_ascii=False))


def cmd_prep(cfg, args):
    variants = images.variant_list(args.preset, box=args.box, long_edge=args.long_edge, scale=args.scale, contrast=args.contrast, sharpen=args.sharpen, quality=args.quality, name=args.name)
    out_dir = Path(args.out) if args.out else (cfg.prepared_dir() / runs.run_name("prep", "img"))
    results = []
    for src in args.images:
        results.extend(images.prepare(src, out_dir, variants, max_long_edge=args.max_long_edge, prefix=args.prefix))
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


def request_from_args(args, model, prompt, system=None, effort=None, history=None, thread="", turn_number=0):
    return Request(
        model=model,
        prompt=prompt,
        image_paths=args.image,
        system=args.system if system is None else system,
        effort=(args.effort or "high") if effort is None else effort,
        max_tokens=args.max_tokens,
        schema=runs.schema_from_file(args.schema) if args.schema else None,
        tag=args.tag or "",
        json_mode=args.json,
        history=history or [],
        thread=thread,
        turn_number=turn_number,
    )


def resolve_ask_thread(cfg, args):
    if args.reset_thread and not args.thread:
        raise ValueError("--reset-thread requires --thread <name>")
    if args.continue_last:
        name = runs.last_thread_name(cfg)
        if not name:
            raise ValueError("no previous thread in this state directory; start one with --thread <name>")
        existing = runs.load_thread(cfg, name)
        if existing is None:
            raise ValueError(f"last thread {name!r} is no longer on disk; start a new one with --thread <name>")
        return name, existing
    if not args.thread:
        return "", None
    name = args.thread.strip()
    runs.thread_key(name)
    if args.reset_thread:
        with ledger.locked(cfg):
            runs.clear_threads(cfg, name=name)
        return name, None
    return name, runs.load_thread(cfg, name)


def cmd_ask(cfg, args):
    prompt = read_prompt(args)
    thread_name, existing = resolve_ask_thread(cfg, args)
    if args.model:
        model = check_model(args.model)
    elif existing and existing.get("model"):
        model = check_model(existing["model"])
    else:
        raise ValueError("--model is required when starting a standalone call or a new --thread (existing threads reuse their last model when --model is omitted)")
    system = args.system if args.system is not None else (existing.get("system") if existing else None)
    effort = args.effort if args.effort is not None else (existing.get("effort") if existing else "high")
    history = runs.thread_history(cfg, existing) if existing else []
    turn_number = (len(existing.get("turns") or []) + 1) if existing else (1 if thread_name else 0)
    request = request_from_args(args, model, prompt, system=system, effort=effort, history=history, thread=thread_name, turn_number=turn_number)
    result = do_call(cfg, request, quiet=args.quiet)
    if thread_name and result["meta"].get("success"):
        with ledger.locked(cfg):
            runs.append_thread_turn(
                cfg,
                thread_name,
                model=model,
                system=system,
                effort=effort,
                user_text=request.prompt,
                image_paths=request.image_paths,
                assistant_text=result["answer"],
                meta=result["meta"],
            )


def cmd_threads(cfg, args):
    action = args.action or "list"
    if action == "list":
        rows = runs.list_threads(cfg)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
            return
        if not rows:
            print("no active threads")
            return
        for row in rows:
            marker = " *" if row["is_last"] else ""
            print(
                f'{row["thread"] + marker:28s} turns={row["turns"]:<3d} model={str(row["model"]):32s} '
                f'cost={ledger.money(row["cost_total"])} updated={row["updated"]}'
            )
        return
    if action == "show":
        name = args.name or runs.last_thread_name(cfg)
        if not name:
            raise ValueError("threads show needs a thread name (no last thread recorded)")
        thread = runs.load_thread(cfg, name)
        if thread is None:
            raise ValueError(f"no such thread: {name}")
        if args.json:
            print(json.dumps(thread, indent=2, ensure_ascii=False))
            return
        print(f'# Thread {thread["thread"]} (model={thread.get("model")}, effort={thread.get("effort")}, turns={len(thread.get("turns") or [])})')
        if thread.get("system"):
            print(f'System: {thread["system"]}')
        for turn in thread.get("turns") or []:
            imgs = ", ".join(turn.get("source_images") or []) or "(no new images)"
            print(f'\n--- Turn {turn["turn"]} ({turn.get("model")}, {ledger.money(turn.get("cost"))}, images: {imgs}) ---')
            print("User:\n" + turn["user_text"])
            print("\nAssistant:\n" + turn["assistant_text"])
        return
    if action == "clear":
        with ledger.locked(cfg):
            removed = runs.clear_threads(cfg, name=args.name, clear_all=args.all)
        if args.json:
            print(json.dumps({"cleared": removed}, indent=2))
        else:
            print("cleared: " + (", ".join(removed) if removed else "none"))
        return
    raise ValueError(f"unknown threads action: {action}")


def result_row(cfg, result, tag):
    meta = result["meta"]
    return {
        "tag": tag,
        "model": meta["model"],
        "cost": meta["cost"],
        "skipped": result["skipped"],
        "answer": result["parsed"] if result["parsed"] is not None else result["answer"],
        "run": str(runs.resolve_saved_path(meta["run_md"], cfg)),
    }


def cmd_panel(cfg, args):
    models = [check_model(m.strip()) for m in args.models.split(",") if m.strip()]
    if not models or len(models) != len(set(models)):
        raise ValueError("panel needs a nonempty list of distinct allowed models")
    prompt = read_prompt(args)
    path = Path(args.out_dir or cfg.runs_dir()) / (runs.run_name(args.tag or "panel", "panel") + ".md")
    rows = []
    failed = 0
    try:
        for model in models:
            request = request_from_args(args, model, prompt)
            try:
                result = do_call(cfg, request, quiet=True)
                rows.append(result_row(cfg, result, request.tag))
            except (ValueError, client.ApiError) as exc:
                # One model failing (allocation, pinned endpoint, truncated answer) must not cost
                # the answers already paid for. Its transcript and ledger record are on disk.
                failed += 1
                rows.append({"tag": request.tag, "model": model, "error": str(exc)})
                print(f"vision: panel {model} failed: {exc}", file=sys.stderr)
            lines = [f"# Panel: {len(rows) - failed} of {len(models)} completed", "", prompt]
            for row in rows:
                if "error" in row:
                    lines += ["", f'## {row["model"]}, FAILED', "", row["error"]]
                else:
                    lines += ["", f'## {row["model"]}, {ledger.money(row["cost"])}', "", json.dumps(row["answer"], indent=2) if not isinstance(row["answer"], str) else row["answer"]]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    finally:
        print(f"vision: panel {len(rows) - failed}/{len(models)} completed; {path}", file=sys.stderr)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        elif not args.quiet:
            for row in rows:
                print(f'\n{row["model"]}:\n{row.get("error") or row["answer"]}')
    if failed:
        raise ValueError(f"{failed} of {len(models)} panel calls failed; see {path}")


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
    rows = []
    failed = 0
    try:
        for request in requests:
            try:
                result = do_call(cfg, request, quiet=True, resume=not args.redo)
                rows.append(result_row(cfg, result, request.tag))
            except (ValueError, client.ApiError) as exc:
                # An unusable or rejected answer is saved and charged; the rest of the batch runs.
                failed += 1
                rows.append({"tag": request.tag, "model": request.model, "error": str(exc)})
                print(f"vision: batch item {request.tag} failed: {exc}", file=sys.stderr)
            if args.out:
                ledger.write_json(Path(args.out), rows)
    finally:
        after = ledger.totals(cfg)
        # counted from this batch's own rows, because other calls may share the state directory
        mine = [row for row in rows if "error" not in row]
        cost = sum(row["cost"] or 0 for row in mine)
        print(f"vision: batch {len(mine)}/{len(requests)} completed, {len(mine)} newly recorded calls; " f"reported new cost {ledger.money(cost)}", file=sys.stderr)
        if after["pending"] or after["unknown_costs"]:
            print("vision: WARNING batch cost is incomplete; unresolved request/cost remains", file=sys.stderr)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        elif not args.quiet:
            for row in rows:
                print(f'{row["tag"]}: {row.get("error") or row["answer"]}')
    if failed:
        raise ValueError(f"{failed} of {len(requests)} batch items failed; results on disk may be partial")


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
    print(f'ledger total: {data["calls_total"]} calls, {ledger.money(data["cost_total"])} reported')
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
                "threads_active": len(runs.list_threads(cfg)),
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
    parser = argparse.ArgumentParser(description="OpenRouter vision calls, multi-turn threads, image prep and cost records")
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
    p = sub.add_parser("prep", help="oriented JPEG derivatives into scratch (or --out); never overwrite")
    p.add_argument("images", nargs="+")
    p.add_argument("--out", help="destination directory; defaults to a fresh folder under <state_dir>/prepared/")
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
    p = sub.add_parser("ask", help="single-turn or multi-turn (--thread / --continue) vision request")
    p.add_argument("--model", help="allowed model slug or short name; optional when continuing an existing thread")
    tgroup = p.add_mutually_exclusive_group()
    tgroup.add_argument("--thread", help="named multi-turn conversation stored in scratch state")
    tgroup.add_argument("--continue", dest="continue_last", action="store_true", help="continue the most recently used thread")
    p.add_argument("--reset-thread", action="store_true", help="clear prior turns for --thread before starting fresh")
    prompt = p.add_mutually_exclusive_group(required=True)
    prompt.add_argument("--prompt")
    prompt.add_argument("--prompt-file")
    p.add_argument("--image", action="append", default=[])
    p.add_argument("--system")
    p.add_argument("--effort", default=None, choices=["none", "minimal", "low", "medium", "high", "default"])
    p.add_argument("--max-tokens", type=int, default=4000)
    p.add_argument("--json", action="store_true")
    p.add_argument("--schema")
    p.add_argument("--tag")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_ask)
    p = sub.add_parser("panel", help="ask several distinct models the same prompt in one run")
    p.add_argument("--models", required=True)
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
    p.set_defaults(func=cmd_panel)
    p = sub.add_parser("threads", help="inspect or clear multi-turn scratch conversations")
    p.add_argument("action", nargs="?", default="list", choices=["list", "show", "clear"])
    p.add_argument("name", nargs="?")
    p.add_argument("--all", action="store_true", help="with clear: remove all saved threads")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_threads)
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
    p = sub.add_parser("probe", help="paid reachability check: one tiny call per pinned endpoint")
    p.add_argument("--models", help="comma-separated short names or slugs; default all allowed models")
    p.add_argument("--effort", default="low", choices=["none", "minimal", "low", "medium", "high", "default"])
    p.add_argument("--max-tokens", type=int, default=800)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_probe)
    p = sub.add_parser("start")
    p.add_argument("--note")
    p.set_defaults(func=cmd_start)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        cfg = config.load_config(env_file=args.env_file, state_dir=args.state_dir, timeout=args.timeout)
        paid = args.command in ("ask", "panel", "batch", "probe")
        if paid and not cfg.api_key:
            raise ValueError("No API key found. Populate .env from .env.example with OR_API_KEY.")
        # do_call takes the lock for its own short registry updates, so paid commands may run
        # concurrently in one state directory. Only session start needs the whole lock.
        if args.command == "start":
            with ledger.locked(cfg):
                args.func(cfg, args)
        else:
            args.func(cfg, args)
    except (ValueError, OSError, KeyError, TypeError, client.ApiError) as exc:
        print(f"vision: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
