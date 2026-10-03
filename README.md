# Vision skill

A stand-alone skill for image understanding through ten allowed OpenRouter models. It includes
agent instructions, a Python CLI, local crop/resize helpers, saved responses and cost records.
It supports varied vision tasks rather than one application. It does not generate images or send
native video; sample video frames first.

## Credentials

The user fills `OR_API_KEY` with an inference key from
[OpenRouter key settings](https://openrouter.ai/settings/keys). Optional `OR_MGMNT_KEY` is used
only to read account credit totals when no inference key is supplied; the tool never creates,
edits or deletes account keys.

The CLI reads a `.env` in the current working directory, then a `.env` in the skill directory, and
falls back to environment variables of the same names, `OR_API_KEY` and `OR_MGMNT_KEY`.
`--env-file` selects an explicit file instead; a selected missing file is an error. The parser
supports quoted values, comments and optional `export`; it never evaluates shell expressions or
expands variables.

Pillow is required. `rawpy` (camera raw), `pillow-heif` (HEIC) and `ffmpeg` (video frames) are
optional extensions used only when their input formats appear.

## Quick start

```sh
python3 skills/vision_skill/scripts/vision.py status
python3 skills/vision_skill/scripts/vision.py models
python3 skills/vision_skill/scripts/vision.py start --note "image comparison"
python3 skills/vision_skill/scripts/vision.py prep photo.jpg --out vision_runs/prepared
python3 skills/vision_skill/scripts/vision.py ask --model google/gemini-3.8-flash \
  --image vision_runs/prepared/photo_full_1568.jpg \
  --prompt "Describe the visible objects and note anything uncertain."
python3 skills/vision_skill/scripts/vision.py cost
```

Defaults are high reasoning effort and 4,000 output tokens, including reasoning. Commands:
`status`, `models`, `info`, `prep`, `ask`, `panel`, `batch`, `start`, `cost`, `spend`.
`python3 skills/vision_skill/scripts/vision.py COMMAND --help` lists options; adjust the path if
the skill lives elsewhere. Global flags go before the command.

`cost` totals the calls recorded in the local ledger. `spend` reads OpenRouter's account activity,
by day and account-wide (so it includes jobs this ledger never made), and prints the remaining
credit; it needs `OR_MGMNT_KEY`. Workspace conventions (state directory, spend policy, credentials
path) are at the end of [SKILL.md](SKILL.md).

For an agent, start with [SKILL.md](SKILL.md). See [recipes](references/recipes.md) for object
localisation, colour/design, OCR, correspondences, image-quality assessment and plot analysis.

## State

`vision_runs/` under the **current working directory** is the default state directory. It contains
`ledger.jsonl`, `session.json`, `runs/`, a catalog cache and, during a request, `pending.json`.
Use `--state-dir DIR` to put it anywhere. All cost totals cover one state directory.

- `start` begins a new session for cost reporting; it never resets ledger totals. A first paid
  request starts a session if none exists.
- Paid commands and session changes acquire a POSIX file lock. No parallel requests share a state
  directory; a second writer exits with an error.
- Reported cost comes from each response's `usage.cost`, without per-call rounding. A
  missing/invalid cost stays unknown and is never relabelled as zero. Account usage can include
  unrelated jobs and is not the ledger's authority.
- The `cost` command is local and does not require a management key.

## Interrupted requests

POST requests are never retried automatically. A timeout, process interruption or server error may
follow a billed generation. The CLI writes `pending.json` **before** sending: it holds the
request settings, ordered image paths and hashes, and the response if one arrived, without
uploaded image bytes or credentials. Explicit request/auth rejection errors (e.g. HTTP 400/401)
remove the marker; ambiguous errors leave it. The next paid request overwrites it.

A remaining marker is evidence, not a block; nothing stops further calls. To check whether an
ambiguous call was billed, match its request ID against the ledger, or use the returned
generation ID or the account activity around the recorded time. If it was charged, record that
cost in the ledger rather than adding a duplicate record. `cost` reports any pending marker or
unknown cost as incomplete totals.

## Privacy and image behaviour

Uploads apply EXIF orientation, convert embedded colour profiles to sRGB, flatten transparency
onto white, strip metadata and send PNG bytes. `prep` writes new JPEG derivatives and refuses
existing targets. Use a PNG directly or a lossless crop for tiny text and exact pixel analysis.
A manifest records crop coordinates and transforms when requested. The 1568/2048 presets are
starting sizes, not claims about every model's native image resolution.

Metadata stripping is not visual redaction. Local transcripts contain prompts, file paths,
responses and request settings, but no credentials or uploaded image bytes.

No tests, test images, credentials or personal data ship with the skill. No license has been
selected; choose one before offering the code for reuse.
