#!/usr/bin/env python3
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from . import ledger

JSON_INSTRUCTION = "\n\nReturn one JSON object or array, with no prose or code fence."


def safe_name(text, fallback="call"):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text or "").strip("._")
    return cleaned[:60] or fallback


def run_name(tag, slug):
    return time.strftime("%Y%m%d-%H%M%S") + "_" + safe_name(tag or slug.replace("/", "_")) + "_" + uuid.uuid4().hex[:10]


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
    header = (
        f'# {meta.get("tag") or name}: {meta["model"]}\n\n'
        f'- When: {meta["when"]}\n'
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
