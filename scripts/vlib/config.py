#!/usr/bin/env python3
import os
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRATCH_ROOT = Path("/tmp/pq_scratch")


@dataclass
class Model:
    slug: str
    label: str
    endpoint: str
    tier: str
    note: str
    default_look: bool = False


# Every model is pinned to one OpenRouter endpoint tag. The request sets provider.only to that
# tag with allow_fallbacks false, so a call either reaches this endpoint or fails loudly.
# A tag without a region segment also matches that provider's regional siblings (for example
# amazon-bedrock includes amazon-bedrock/us-east-1). Pass the region form to narrow it further.
ALLOWED = [
    Model("openai/gpt-6-luna", "GPT-6 Luna", "openai/flex", "cheap", "Ultra-cheap OpenAI vision pass; check coordinates and small-text fidelity before relying on it."),
    Model("z-ai/glm-5.3-flash", "GLM 5.3 Flash", "gmicloud/fp8", "cheap", "Low-cost open-weight vision pass; budget extra tokens if reasoning is verbose."),
    Model("deepseek/deepseek-v4.1-flash-1017", "DeepSeek V4.1 Flash", "morph/fp8", "cheap", "Cheap bulk description, pre-filtering, rough captioning."),
    Model("google/gemini-3.8-flash", "Gemini 3.8 Flash", "google-vertex/global/flex", "cheap", "Plots, tables, bulk inventory; cheap reliable matplotlib layout check at low effort."),
    Model("xiaomi/mimo-v2.6-pro", "MiMo V2.6 Pro", "gmicloud/bf16", "mid", "Captioning and general description; boxes were inaccurate on the card test."),
    Model("openai/gpt-6.1-terra", "GPT-6.1 Terra", "openai/flex", "mid", "Default general work: fast screenshot, UI, document, and exact-coordinate reading.", default_look=True),
    Model("moonshotai/kimi-k3.1-pro", "Kimi K3.1 Pro", "morph/fp8", "mid", "Strongest open-weight multimodal reader for cross-family comparison."),
    Model("openai/gpt-6.1-sol", "GPT-6.1 Sol", "openai/flex", "mid", "Dense landmark/object inventory, exact fractional boxes, and chart analytics; reasoning is mandatory."),
    Model("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro", "google-vertex/global/flex", "mid", "Constrained comparison between named candidates; check its confidence numbers."),
    Model("google/gemini-4-hydrogen", "Gemini 4 Hydrogen", "google-vertex/global", "mid", "Fast Gemini 4 multimodal/agentic reader; strong on charts and structured visual reasoning."),
    Model("x-ai/grok-4.7", "Grok 4.7", "xai/zdr", "mid", "General description and blunt second opinion; refuses ungrounded headings."),
    Model("anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5", "amazon-bedrock", "mid", "Desktop/web UI reading, dense screenshots, and grounded visual reasoning."),
    Model("google/gemini-4-argon", "Gemini 4 Argon", "google-vertex/global", "premium", "Strong all-round Gemini 4 reading; compare with Gemini 4 Carbon at the same price."),
    Model("google/gemini-4-carbon", "Gemini 4 Carbon", "google-vertex/global", "premium", "Highest-intelligence Gemini 4 model for hard visual, scientific, and document reasoning."),
    Model("anthropic/claude-opus-5.5", "Claude Opus 5.5", "amazon-bedrock", "premium", "Geometry, shadow and camera reasoning, awkward judgement calls."),
    Model("anthropic/claude-fable-5.2", "Claude Fable 5.2", "google-vertex/global", "premium", "Top-tier multimodal accuracy for decisive tie-breakers; dearest per call."),
]
BY_SLUG = {m.slug: m for m in ALLOWED}
SHORT = {m.slug.split("/")[1]: m.slug for m in ALLOWED}

# ### HUMAN_REVIEW
# Set (model, endpoint) image_bytes and request_bytes only after verifying provider limits.
# Empty policies preserve the standalone default; no universal 3.6MiB cap is assumed.
UPLOAD_LIMITS = {}


def resolve_model(name):
    return SHORT.get(name, name)


def is_allowed(name):
    return resolve_model(name) in BY_SLUG


def model_of(name):
    return BY_SLUG.get(resolve_model(name))


def default_model():
    chosen = next((m.slug for m in ALLOWED if m.default_look), None)
    return chosen or (ALLOWED[0].slug if ALLOWED else "")


def default_state_dir():
    # Keep catalog caches (~1.7 MB), spend ledgers, and multi-turn scratch threads outside project
    # workspaces by default so `look` and `vision.py` never litter workspaces with `vision_runs/`
    # directories. Durable visual findings belong in the project's normal notes and reports.
    try:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        return SCRATCH_ROOT / "vision"
    except OSError:
        return Path(tempfile.gettempdir()) / f"vision_skill_{os.getuid()}"


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
    # Check cwd/.env first, then <project>/.env when installed under <project>/skills/vision_skill,
    # then /workspace/.env (the sandbox mount point inside run_agent.sh), then SKILL_ROOT/.env.
    candidates = [Path.cwd() / ".env"]
    if SKILL_ROOT.parent.name == "skills":
        candidates.append(SKILL_ROOT.parents[1] / ".env")
    candidates.extend([Path("/workspace/.env"), SKILL_ROOT / ".env"])
    return next((p for p in candidates if p.is_file()), None)


@dataclass
class Config:
    api_key: str = ""
    mgmt_key: str = ""
    env_file: Path = None
    state_dir: Path = None
    timeout: int = 300

    def runs_dir(self):
        return self.state_dir / "runs"

    def threads_dir(self):
        return self.state_dir / "threads"

    def prepared_dir(self):
        return self.state_dir / "prepared"


def load_config(env_file=None, state_dir=None, timeout=None):
    file = find_env_file(env_file)
    values = read_env_file(file) if file else {}

    # .env first, then a variable of the same name in the process environment.
    def setting(name):
        return values.get(name) or os.environ.get(name) or ""

    seconds = 300 if timeout is None else timeout
    if seconds <= 0:
        raise ValueError("timeout must be positive")
    state = state_dir or os.environ.get("VISION_STATE_DIR") or default_state_dir()
    return Config(
        api_key=setting("OR_API_KEY"),
        mgmt_key=setting("OR_MGMNT_KEY"),
        env_file=file,
        state_dir=Path(state).expanduser().resolve(),
        timeout=seconds,
    )
