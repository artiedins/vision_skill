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
    tier: str
    note: str


ALLOWED = [
    Model("anthropic/claude-fable-5", "Claude Fable 5", "premium", "OCR; another Fable reader."),
    Model("openai/gpt-6-astra", "GPT-6 Astra", "premium", "Object localisation and visual reasoning."),
    Model("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro", "mid", "Stated-class identification and structured data."),
    Model("anthropic/claude-fable-5.1", "Claude Fable 5.1", "premium", "OCR and diagrams."),
    Model("google/gemini-3.8-flash", "Gemini 3.8 Flash", "cheap", "Charts, tables and a general first pass."),
    Model("anthropic/claude-opus-5.5", "Claude Opus 5.5", "premium", "General reasoning and design discussion."),
    Model("openai/gpt-6-sol", "GPT-6 Sol", "mid", "General vision and object localisation."),
    Model("meta/muse-spark-1.2", "Muse Spark 1.2", "cheap", "OCR and a second opinion on design."),
    Model("z-ai/glm-5.3-flash", "GLM 5.3 Flash", "cheap", "Rough bulk descriptions and pre-filtering."),
    Model("openai/gpt-6-luna", "GPT-6 Luna", "cheap", "Simple labels; limited task-specific evidence."),
]
BY_SLUG = {m.slug: m for m in ALLOWED}
SHORT = {m.slug.split("/")[1]: m.slug for m in ALLOWED}


def resolve_model(name):
    return SHORT.get(name, name)


def is_allowed(name):
    return resolve_model(name) in BY_SLUG


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
    return next((p for p in (Path.cwd() / ".env", SKILL_ROOT / ".env") if p.is_file()), None)


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
