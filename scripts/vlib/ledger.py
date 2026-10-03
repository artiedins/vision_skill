#!/usr/bin/env python3
import fcntl
import json
import math
import os
import time
import uuid
from contextlib import contextmanager


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def locked(cfg):
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    with (cfg.state_dir / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another vision command is using this state directory; wait for it")
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def append(cfg, record):
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    with (cfg.state_dir / "ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read(cfg):
    path = cfg.state_dir / "ledger.jsonl"
    if not path.is_file():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            cost = record["cost"]
            if cost is not None and (not math.isfinite(float(cost)) or float(cost) < 0):
                raise ValueError("invalid cost")
            records.append(record)
        except (ValueError, KeyError, TypeError):
            raise ValueError(f"damaged ledger at {path}:{number}; refusing to ignore spend")
    return records


def pending(cfg):
    # Record of the most recent in-flight request; evidence after an ambiguous failure, never a block.
    path = cfg.state_dir / "pending.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def start_session(cfg, note=""):
    session = {
        "id": time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:10],
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": note,
    }
    write_json(cfg.state_dir / "session.json", session)
    return session


def current_session(cfg):
    path = cfg.state_dir / "session.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def totals(cfg):
    records = read(cfg)
    session_id = (current_session(cfg) or {}).get("id")
    current = [r for r in records if r.get("session") == session_id]
    by_model = {}
    for record in records:
        entry = by_model.setdefault(record.get("model", "?"), {"calls": 0, "cost": 0.0})
        entry["calls"] += 1
        entry["cost"] += record["cost"] or 0
    return {
        "calls_total": len(records),
        "cost_total": sum(r["cost"] or 0 for r in records),
        "calls_session": len(current),
        "cost_session": sum(r["cost"] or 0 for r in current),
        "unknown_costs": sum(r["cost"] is None for r in records),
        "session_id": session_id,
        "by_model": by_model,
        "pending": pending(cfg),
    }


def money(value):
    if value is None:
        return "unknown"
    if 0 < abs(value) < 1e-9:
        return f"${value:.3g}"
    return f"${value:.9f}"
