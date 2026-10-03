#!/usr/bin/env python3
import base64
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

from . import images, ledger

API = "https://openrouter.ai/api/v1"


class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def request_json(url, key="", payload=None, timeout=60):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
        request.add_header("X-Title", "vision-skill")
    # Never replay a paid POST automatically: a timeout or 5xx can follow a billed generation.
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode(errors="replace")
        if key:
            message = message.replace(key, "[redacted]")
        raise ApiError(f"HTTP {exc.code}: {message[:500]}", status=exc.code) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        message = str(exc).replace(key, "[redacted]") if key else str(exc)
        raise ApiError(f"request failed: {message}") from None


def catalog(cfg, refresh=False):
    cache = cfg.state_dir / "catalog.json"
    fresh = cache.is_file() and time.time() - cache.stat().st_mtime < 6 * 3600
    if not refresh and fresh:
        try:
            return {m["id"]: m for m in json.loads(cache.read_text(encoding="utf-8"))["data"]}
        except (ValueError, KeyError, TypeError):
            pass
    data = request_json(f"{API}/models", timeout=90)["data"]
    ledger.write_json(cache, {"fetched": time.time(), "data": data})
    return {m["id"]: m for m in data}


def build_payload(slug, prompt, image_paths, system=None, effort="high", max_tokens=4000, schema=None):
    content = [{"type": "text", "text": prompt}]
    for path in image_paths:
        mime, data = images.upload_bytes(path)
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}})
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    payload = {"model": slug, "messages": messages, "max_tokens": max_tokens, "provider": {"require_parameters": True}}
    if effort != "default":
        payload["reasoning"] = {"effort": effort}
    if schema:
        payload["response_format"] = {"type": "json_schema", "json_schema": schema}
    return payload


def chat(cfg, payload):
    return request_json(f"{API}/chat/completions", cfg.api_key, payload, cfg.timeout)


def answer_of(body):
    choices = body.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "\n".join(item.get("text", "") for item in content if item.get("type") == "text")
    return content, message


def usage_record(body, slug):
    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    cost = usage.get("cost")
    try:
        cost = float(cost)
        if not math.isfinite(cost) or cost < 0:
            cost = None
    except (TypeError, ValueError):
        cost = None
    return {
        "model": slug,
        "response_model": body.get("model"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "cost": cost,
        "cost_source": "usage.cost" if cost is not None else "unknown",
        "finish_reason": (body.get("choices") or [{}])[0].get("finish_reason"),
        "provider": body.get("provider"),
        "generation_id": body.get("id"),
    }


def credits(cfg):
    key = cfg.api_key or cfg.mgmt_key
    if not key:
        return None
    return request_json(f"{API}/credits", key, timeout=30)["data"]


def activity(cfg):
    # Account-side usage by day and model; the management key sees every account job, not just ours.
    key = cfg.mgmt_key or cfg.api_key
    if not key:
        return None
    return request_json(f"{API}/activity", key, timeout=30).get("data") or []
