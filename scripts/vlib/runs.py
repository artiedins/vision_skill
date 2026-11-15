#!/usr/bin/env python3
import hashlib
import json
import re
import shutil
import time
import uuid
from pathlib import Path

from . import images, ledger

JSON_INSTRUCTION = "\n\nReturn one JSON object or array, with no prose or code fence."


def safe_name(text, fallback="call"):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text or "").strip("._")
    return cleaned[:60] or fallback


def run_name(tag, slug):
    return time.strftime("%Y%m%d-%H%M%S") + "_" + safe_name(tag or slug.replace("/", "_")) + "_" + uuid.uuid4().hex[:10]


def portable_path(path, cfg, base_cwd=None):
    # Store state_dir-internal and workspace-internal paths as relative strings so moving a
    # workspace or explicit --state-dir never breaks run_json, run_md, or thread media references.
    resolved = Path(path).expanduser().resolve()
    state_root = cfg.state_dir.resolve()
    if resolved.is_relative_to(state_root):
        return str(resolved.relative_to(state_root))
    cwd = (Path(base_cwd) if base_cwd else Path.cwd()).resolve()
    if resolved.is_relative_to(cwd):
        return str(resolved.relative_to(cwd))
    return str(resolved)


def resolve_saved_path(saved, cfg):
    path = Path(saved)
    if path.is_absolute():
        return path
    in_state = cfg.state_dir / path
    if in_state.exists():
        return in_state
    in_cwd = Path.cwd() / path
    if in_cwd.exists():
        return in_cwd
    return in_state


def fingerprint(payload):
    # Hash the actual request, including ordered, normalised image bytes, not its label or path.
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def request_record(payload):
    saved = json.loads(json.dumps(payload))
    for message in saved["messages"]:
        if isinstance(message["content"], list):
            for part in message["content"]:
                if part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    part["image_url"] = {"sha256_data_url": hashlib.sha256(url.encode()).hexdigest()}
    return saved


def write_run(cfg, name, request, response, answer, meta):
    cfg.runs_dir().mkdir(parents=True, exist_ok=True)
    json_path = cfg.runs_dir() / f"{name}.json"
    md_path = cfg.runs_dir() / f"{name}.md"
    ledger.write_json(json_path, {"meta": meta, "request": request, "response": response})
    thread_line = f'- Thread: {meta["thread"]} (turn {meta["turn"]})\n' if meta.get("thread") else ""
    header = (
        f'# {meta.get("tag") or name}: {meta["model"]}\n\n'
        f'- When: {meta["when"]}\n'
        f"{thread_line}"
        f'- Cost: {ledger.money(meta["cost"])} ({meta["cost_source"]})\n'
        f'- Finish reason: {meta.get("finish_reason")}\n'
        f'- Images, in order: {", ".join(meta["image_paths"]) or "(none)"}\n\n'
    )
    md_path.write_text(header + f'## Prompt\n\n{meta["prompt"]}\n\n## Answer\n\n{answer}\n', encoding="utf-8")
    return {"md": str(md_path), "json": str(json_path)}


def extract_json(text):
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        parsed = json.loads(text)
        json.dumps(parsed, allow_nan=False)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def schema_from_file(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("schema file must contain a JSON object")
    return {"name": data.get("name", safe_name(Path(path).stem)), "strict": data.get("strict", True), "schema": data["schema"] if "schema" in data else data}


def thread_key(name):
    cleaned = safe_name(name, fallback="")
    if not cleaned:
        raise ValueError("thread name must contain at least one letter or digit")
    return cleaned


def thread_path(cfg, name):
    return cfg.threads_dir() / f"{thread_key(name)}.json"


def thread_media_dir(cfg, name):
    return cfg.threads_dir() / f"{thread_key(name)}_media"


def last_thread_path(cfg):
    return cfg.state_dir / "last_thread.txt"


def last_thread_name(cfg):
    path = last_thread_path(cfg)
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def set_last_thread(cfg, name):
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    last_thread_path(cfg).write_text(name.strip() + "\n", encoding="utf-8")


def load_thread(cfg, name):
    path = thread_path(cfg, name)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_turn_images(cfg, name, turn_number, image_paths):
    # Browser workflows routinely reuse a fixed screenshot path such as files.path('shot.png').
    # Snapshotting each turn's normalized image into <thread>_media keeps earlier turns intact even
    # when the caller overwrites or deletes the original file before a follow-up turn.
    if not image_paths:
        return []
    media_dir = thread_media_dir(cfg, name)
    media_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for index, src in enumerate(image_paths, 1):
        mime, data = images.upload_bytes(src)
        ext = "jpg" if mime == "image/jpeg" else "png"
        dest = media_dir / f"turn{turn_number:03d}_{index:02d}.{ext}"
        dest.write_bytes(data)
        saved.append(portable_path(dest, cfg))
    return saved


def thread_history(cfg, thread):
    if not thread:
        return []
    history = []
    for turn in thread.get("turns") or []:
        refs = turn.get("snapshot_images") or turn.get("source_images") or []
        resolved = []
        for ref in refs:
            candidate = resolve_saved_path(ref, cfg)
            if not candidate.is_file():
                raise ValueError(f"thread {thread.get('thread')!r} turn {turn.get('turn')} is missing saved image {candidate}; use --reset-thread to start fresh")
            resolved.append(str(candidate))
        history.append(
            {
                "user_text": turn["user_text"],
                "image_paths": resolved,
                "assistant_text": turn["assistant_text"],
            }
        )
    return history


def append_thread_turn(cfg, name, model, system, effort, user_text, image_paths, assistant_text, meta):
    key = thread_key(name)
    existing = load_thread(cfg, name)
    when = meta.get("when") or time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if existing is None:
        existing = {
            "thread": name,
            "key": key,
            "created": when,
            "updated": when,
            "model": model,
            "system": system,
            "effort": effort,
            "turns": [],
        }
    turn_number = len(existing["turns"]) + 1
    snaps = snapshot_turn_images(cfg, name, turn_number, image_paths)
    existing["turns"].append(
        {
            "turn": turn_number,
            "when": when,
            "model": model,
            "effort": effort,
            "user_text": user_text,
            "source_images": [portable_path(p, cfg) for p in image_paths],
            "snapshot_images": snaps,
            "assistant_text": assistant_text,
            "cost": meta.get("cost"),
            "request_id": meta.get("request_id"),
            "run_md": meta.get("run_md"),
        }
    )
    existing["updated"] = when
    existing["model"] = model
    existing["system"] = system
    existing["effort"] = effort
    ledger.write_json(thread_path(cfg, name), existing)
    set_last_thread(cfg, name)
    return existing


def list_threads(cfg):
    folder = cfg.threads_dir()
    if not folder.is_dir():
        return []
    last = last_thread_name(cfg)
    last_key = thread_key(last) if last else None
    rows = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        turns = data.get("turns") or []
        rows.append(
            {
                "thread": data.get("thread") or path.stem,
                "key": data.get("key") or path.stem,
                "turns": len(turns),
                "model": data.get("model"),
                "effort": data.get("effort"),
                "cost_total": sum((t.get("cost") or 0.0) for t in turns),
                "updated": data.get("updated"),
                "is_last": (data.get("key") or path.stem) == last_key,
            }
        )
    rows.sort(key=lambda r: r.get("updated") or "", reverse=True)
    return rows


def clear_threads(cfg, name=None, clear_all=False):
    folder = cfg.threads_dir()
    removed = []
    if clear_all:
        if folder.is_dir():
            for path in sorted(folder.glob("*.json")):
                removed.append(path.stem)
            shutil.rmtree(folder)
        last_thread_path(cfg).unlink(missing_ok=True)
        return removed
    if not name:
        raise ValueError("pass a thread name or --all to clear threads")
    key = thread_key(name)
    tpath = thread_path(cfg, name)
    mdir = thread_media_dir(cfg, name)
    if tpath.is_file():
        tpath.unlink()
        removed.append(key)
    if mdir.is_dir():
        shutil.rmtree(mdir)
    last = last_thread_name(cfg)
    if last and thread_key(last) == key:
        last_thread_path(cfg).unlink(missing_ok=True)
    return removed
