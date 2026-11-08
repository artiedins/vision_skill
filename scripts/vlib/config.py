#!/usr/bin/env python3
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Model:
    slug: str
    label: str
    endpoint: str
    tier: str
    note: str


# Every model is pinned to one OpenRouter endpoint tag. The request sets provider.only to that
# tag with allow_fallbacks false, so a call either reaches this endpoint or fails loudly.
# A tag without a region segment also matches that provider's regional siblings (for example
# amazon-bedrock includes amazon-bedrock/us-east-1). Pass the region form to narrow it further.
ALLOWED = [
    Model("deepseek/deepseek-v4.1-flash-1017", "DeepSeek V4.1 Flash", "morph/fp8", "cheap", "Cheap bulk description, pre-filtering, rough captioning."),
    Model("xiaomi/mimo-v2.6-pro", "MiMo V2.6 Pro", "gmicloud/bf16", "mid", "Unrated here: general description, second opinion."),
    Model("openai/gpt-6.1-sol", "GPT-6.1 Sol", "openai/flex", "mid", "Landmark and object inventory with fractional boxes; reasoning is mandatory."),
    Model("anthropic/claude-opus-5.5", "Claude Opus 5.5", "amazon-bedrock", "premium", "Geometry, shadow and camera reasoning; slowest and dearest per call."),
    Model("google/gemini-4-argon", "Gemini 4 Argon", "google-vertex/global", "premium", "Strongest all-round reading; start here when the answer must be right."),
    Model("openai/gpt-6.1-terra", "GPT-6.1 Terra", "openai/flex", "mid", "Screenshot, interface and document-heavy reading."),
    Model("google/gemini-3.8-flash", "Gemini 3.8 Flash", "google-vertex/global/flex", "cheap", "Plots, tables, bulk inventory; the usual first pass."),
    Model("x-ai/grok-4.7", "Grok 4.7", "xai/zdr", "mid", "Unrated here: general description, blunt critique."),
    Model("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro", "google-vertex/global/flex", "mid", "Constrained comparison between named candidates; check its confidence numbers."),
]
BY_SLUG = {m.slug: m for m in ALLOWED}
SHORT = {m.slug.split("/")[1]: m.slug for m in ALLOWED}


def resolve_model(name):
    return SHORT.get(name, name)


def is_allowed(name):
    return resolve_model(name) in BY_SLUG


def model_of(name):
    return BY_SLUG.get(resolve_model(name))


def read_env_file(path):
    values = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            raise ValueError(f"invalid .env assignment at line {number}")
        key, value = line.split("=", 1)
        # Parse quotes and comments, never execute or expand shell expressions.
        tokens = shlex.split(value, comments=True)
        if len(tokens) > 1:
            raise ValueError(f"quote values containing spaces in .env line {number}")
        values[key.strip()] = tokens[0] if tokens else ""
    return values


def find_env_file(explicit=None):
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"explicit .env file does not exist: {path}")
        return path
    # /workspace is the project root inside run_agent.sh, so a key placed there
    # is found from any subdirectory the agent happens to be working in
    return next((p for p in (Path.cwd() / ".env", Path("/workspace/.env"), SKILL_ROOT / ".env") if p.is_file()), None)


@dataclass
class Config:
    api_key: str = ""
    mgmt_key: str = ""
    env_file: Path = None
    state_dir: Path = None
    timeout: int = 300

    def runs_dir(self):
        return self.state_dir / "runs"


def load_config(env_file=None, state_dir=None, timeout=None):
    file = find_env_file(env_file)
    values = read_env_file(file) if file else {}

    # .env first, then a variable of the same name in the process environment.
    def setting(name):
        return values.get(name) or os.environ.get(name) or ""

    seconds = 300 if timeout is None else timeout
    if seconds <= 0:
        raise ValueError("timeout must be positive")
    state = state_dir or "vision_runs"
    return Config(
        api_key=setting("OR_API_KEY"),
        mgmt_key=setting("OR_MGMNT_KEY"),
        env_file=file,
        state_dir=Path(state).expanduser().resolve(),
        timeout=seconds,
    )
