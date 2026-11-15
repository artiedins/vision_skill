# Vision skill

A stand-alone skill for image understanding and multi-turn visual conversation across sixteen allowed
OpenRouter models. Each model is pinned to one provider endpoint (`provider.only` with
`allow_fallbacks: false`), so every call either reaches its pinned endpoint or fails loudly. It
includes agent instructions, a Python CLI, multi-turn conversation threads, local crop/resize
helpers, and per-call cost records. It does not generate images or send native video; sample video
frames first.

## Credentials

Populate `OR_API_KEY` with an inference key from
[OpenRouter key settings](https://openrouter.ai/settings/keys). Optional `OR_MGMNT_KEY` reads
account-level credit and daily usage when needed; the tool never creates, edits, or deletes keys.

The CLI checks `.env` in the current working directory, the owning project root (when installed at
`<project>/skills/vision_skill`), `/workspace/.env`, and the skill directory, falling back to
environment variables `OR_API_KEY` and `OR_MGMNT_KEY`. `--env-file` selects an explicit file.

Pillow is required. `rawpy` (camera raw), `pillow-heif` (HEIC) and `ffmpeg` (video frames) are
optional extensions used only when their input formats appear.

## Quick start

```sh
python3 skills/vision_skill/scripts/vision.py status
python3 skills/vision_skill/scripts/vision.py models
python3 skills/vision_skill/scripts/vision.py prep photo.jpg
python3 skills/vision_skill/scripts/vision.py ask --thread inspect --model openai/gpt-6.1-terra \
  --effort low --max-tokens 2000 --image photo.jpg \
  --prompt "Describe the visible objects and note anything uncertain."
python3 skills/vision_skill/scripts/vision.py ask --thread inspect \
  --prompt "Give fractional bounding boxes for the two objects on the right."
python3 skills/vision_skill/scripts/vision.py cost
```

Commands: `status`, `models`, `probe`, `info`, `prep`, `ask`, `panel`, `threads`, `batch`, `start`,
`cost`, `spend`. Global flags (`--state-dir`, `--env-file`, `--timeout`) go before the command.

For an agent, start with [SKILL.md](SKILL.md). See [recipes](references/recipes.md) for object
localisation, colour/design, OCR, correspondences, quality triage, plot analysis and candidate
elimination, and [workflow](references/workflow.md) for multi-round investigations.

## Scratch state (no workspace clutter)

By default, state lives outside project directories at `/tmp/pq_scratch/vision` (fallback:
`<tempdir>/vision_skill_<uid>`), overridable via `VISION_STATE_DIR` or `--state-dir DIR`. It holds
`ledger.jsonl`, `session.json`, `runs/`, `threads/`, `prepared/`, 6-hour catalog/endpoint caches,
and `pending/` markers for in-flight requests. Durable conclusions belong in the project's normal
notes and deliverables rather than `vision_runs/` folders inside workspaces.

- Paths inside `ledger.jsonl` and thread files are stored portably relative to `state_dir` or `cwd`
  when inside them.
- `ask --thread NAME` (and `ask --continue`) saves multi-turn conversation history and snapshots each
  turn's normalized images under `threads/<name>_media/`, so reusing a screenshot filename such as
  `/tmp/pq_browse_files/shot.png` on a later turn never corrupts earlier turns.
- `threads list`, `threads show <name>`, and `threads clear <name>|--all` inspect or reset threads.
- Reported cost comes from each response's `usage.cost`. `cost` totals the local ledger without
  requiring a management key; `spend` reads account-wide daily usage from OpenRouter.

## Interrupted requests

POST requests are never retried automatically. A marker under `pending/` is written before sending
and removed on explicit 4xx rejection or once billed cost is recorded; leftover markers after a
timeout or 5xx remain as evidence without blocking subsequent calls.

## Privacy and image behaviour

Uploads apply EXIF orientation, convert embedded colour profiles to sRGB, flatten transparency onto
white, strip metadata, re-encode JPEGs (`quality=92`), and send PNG/WebP/still GIF inputs losslessly
as PNG. `prep` writes JPEG derivatives and refuses overwrites. Metadata stripping is not visual
redaction.

No tests, test images, credentials or personal data ship with the skill. Licensed under
[Apache-2.0](LICENSE).
