# Vision skill

A stand-alone skill for image understanding and multi-turn visual conversation across the allowed
OpenRouter vision models. Each model is pinned to one provider endpoint (`provider.only` with
`allow_fallbacks: false`), so every call either reaches its pin or fails loudly. It includes agent
instructions, a Python CLI, multi-turn threads, local crop and resize helpers, per-call cost records,
and offline tests. It does not generate images or send native video; sample frames first.

## Credentials

Populate `OR_API_KEY` with an inference key from
[OpenRouter key settings](https://openrouter.ai/settings/keys). The optional `OR_MGMNT_KEY` reads
account-level credit and daily usage; the tool never creates, edits or deletes keys.

The CLI checks `.env` in the working directory, the owning project root (when installed at
`<project>/skills/vision_skill`), `/workspace/.env` and the skill directory, then falls back to
`OR_API_KEY` and `OR_MGMNT_KEY` in the environment. `--env-file` selects an explicit file.

Pillow is required. `rawpy` (camera raw), `pillow-heif` (HEIC) and `ffmpeg` (video frames) are
optional extensions used only when those inputs appear.

## Quick start

```sh
python3 skills/vision_skill/scripts/vision.py status
python3 skills/vision_skill/scripts/vision.py models
python3 skills/vision_skill/scripts/vision.py prep photo.jpg
python3 skills/vision_skill/scripts/vision.py ask --thread inspect --model openai/gpt-6.1-terra \
  --effort low --image photo.jpg \
  --prompt "Describe the visible objects and note anything uncertain."
python3 skills/vision_skill/scripts/vision.py ask --thread inspect \
  --prompt "Give fractional bounding boxes for the two objects on the right."
python3 skills/vision_skill/scripts/vision.py cost
```

Commands: `status`, `models`, `probe`, `info`, `prep`, `ask`, `panel`, `threads`, `batch`, `start`,
`cost`, `spend`. Global flags (`--state-dir`, `--env-file`, `--timeout`) go before the command.
`panel` and `batch` accept `--max-spend` and stop starting new calls once spend reaches that limit.

For an agent, start with [SKILL.md](SKILL.md). [models](references/models.md) covers pins, live
prices and measured accuracy, [prompting](references/prompting.md) covers prompt craft and
coordinates, [workflow](references/workflow.md) covers multi-round investigations, and
[recipes](references/recipes.md) holds worked examples.

## Scratch state

By default, state lives outside project directories at `/tmp/pq_scratch/vision` (falling back to
`<tempdir>/vision_skill_<uid>`). Override this with `VISION_STATE_DIR` or `--state-dir DIR`. It holds
`ledger.jsonl`, `session.json`, `runs/`, `threads/`, `prepared/`, six-hour catalog and endpoint
caches, and `pending/` markers for in-flight requests. Conclusions belong in the project's notes and
deliverables rather than in `vision_runs/` folders inside workspaces.

- Paths inside `ledger.jsonl` and thread files are stored relative to `state_dir` or `cwd` whenever
  they fall under either directory.
- `ask --thread NAME` (and `ask --continue`) keeps conversation history and snapshots each turn's
  normalized images under `threads/<name>_media/`. Snapshots are sent byte-for-byte on later turns,
  so reusing a screenshot filename never corrupts an earlier turn and never adds a JPEG generation.
- `threads list`, `threads show <name>` and `threads clear <name>|--all` inspect or reset threads.
- Reported cost comes from each response's `usage.cost`. `cost` totals the local ledger without a
  management key; `spend` reads account-wide daily usage from OpenRouter.

## Interrupted requests

POST requests are never retried automatically. A marker under `pending/` is written before sending
and removed on explicit 4xx rejection or once billed cost is recorded. Leftover markers after a
timeout or 5xx stay as evidence and do not block later calls.

## Privacy and image behavior

Uploads apply EXIF orientation, convert embedded color profiles to sRGB, flatten transparency onto
white, strip metadata, re-encode JPEGs at `quality=92`, and send PNG, WebP and still GIF inputs
losslessly as PNG. `prep` writes PNG for lossless sources and JPEG otherwise, and refuses to
overwrite. Stripped metadata does not hide visible faces, addresses or text.

## Tests

```sh
python3 skills/vision_skill/tests/test_skill.py
```

Fourteen offline tests cover JSON extraction, cost formatting, token budgets, `prep` formats and
manifests, thread snapshot reuse, batch resume accounting, and completion handling. The tests require
no network access or credentials, and no test images ship with the skill. Licensed under
[Apache-2.0](LICENSE).
