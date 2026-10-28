#!/usr/bin/env python3
import base64
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, images, ledger

API = "https://openrouter.ai/api/v1"
CACHE_SECONDS = 6 * 3600


class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def request_json(url, key="", payload=None, timeout=60, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
        request.add_header("X-Title", "vision-skill")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
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


def _cached(cfg, name, refresh, fetch):
    cache = cfg.state_dir / name
    if not refresh and cache.is_file() and time.time() - cache.stat().st_mtime < CACHE_SECONDS:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (ValueError, KeyError, TypeError):
            pass
    data = fetch()
    ledger.write_json(cache, data)
    return data


def catalog(cfg, refresh=False):
    def fetch():
        return {m["id"]: m for m in request_json(f"{API}/models", timeout=90)["data"]}

    return _cached(cfg, "catalog.json", refresh, fetch)


def endpoints(cfg, refresh=False):
    # Per-model endpoint lists. tags, health status and per-endpoint prices decide whether a
    # pinned endpoint exists at all; account data policy can still reject it at call time.
    def fetch():
        fetched = {}
        for model in config.ALLOWED:
            body = request_json(f"{API}/models/{model.slug}/endpoints", cfg.api_key, timeout=60)
            fetched[model.slug] = body.get("data") or {}
        return fetched

    return _cached(cfg, "endpoints.json", refresh, fetch)


def provider_block(endpoint):
    block = {"allow_fallbacks": False, "require_parameters": True}
    if endpoint:
        block["only"] = [endpoint]
    return block


def build_payload(slug, endpoint, prompt, image_paths, system=None, effort="high", max_tokens=4000, schema=None):
    content = [{"type": "text", "text": prompt}]
    for path in image_paths:
        mime, data = images.upload_bytes(path)
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}})
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    payload = {"model": slug, "messages": messages, "max_tokens": max_tokens, "provider": provider_block(endpoint)}
    if effort != "default":
        payload["reasoning"] = {"effort": effort}
    if schema:
        payload["response_format"] = {"type": "json_schema", "json_schema": schema}
    return payload


def chat(cfg, payload):
    # X-OpenRouter-Metadata has the router name the provider it selected for this call.
    return request_json(f"{API}/chat/completions", cfg.api_key, payload, cfg.timeout, headers={"X-OpenRouter-Metadata": "enabled"})


def answer_of(body):
    choices = body.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "\n".join(item.get("text", "") for item in content if item.get("type") == "text")
    return content, message


def routing_of(body):
    meta = body.get("openrouter_metadata") or {}
    endpoints = meta.get("endpoints") or {}
    return {
        "provider": body.get("provider"),
        "summary": meta.get("summary"),
        "strategy": meta.get("strategy"),
        "attempt": meta.get("attempt"),
        "candidates": endpoints.get("total"),
    }


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
        "routing": routing_of(body),
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
