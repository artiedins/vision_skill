# Model selection and evidence

The allow-list and its pinned endpoints live in `scripts/vlib/config.py`. Each model has exactly
one endpoint tag, and every request sets `provider.only` to that tag with `allow_fallbacks: false`,
so a call either reaches that endpoint or fails. `models` prints the pin, whether it is still in
OpenRouter's live endpoint list, that endpoint's `health` status (`0` is normal; nonzero is a
provider-side status flag rather than a routing block), and its live per-million-token prices;
`models --refresh` skips the six-hour cache.

## How endpoint pinning and pricing behave

- A pin that does not exist produces HTTP 404 naming the providers that do serve the model, for
  example `your request's provider.only preference permits only: nonexistent-provider`. That is the
  intended loud failure, not a reason to widen the list.
- A pin can also be rejected by **account data policy**, which the endpoint list does not show. On
  this account every `google-ai-studio` endpoint is removed with `ZDR violation (account settings)`,
  which is why the Gemini pins are all `google-vertex`. Only a paid call reveals this, so run
  `probe` after changing account settings.
- A tag without a region segment matches that provider's regional siblings: `amazon-bedrock`
  includes `amazon-bedrock/us-east-1` and `amazon-bedrock/eu-west-1`. Use the region form when the
  region matters.
- `service_tier` endpoints (`flex`, `priority`) are separate targets and are usually priced
  differently from their standard sibling. The pin decides the price: the same Gemini 3.8 Flash
  prompt and image cost $0.0004766 on `google-vertex/global/flex` and $0.000938 unpinned.
- **Static vs floating endpoint prices:** Direct provider pins (`openai/flex`, `google-vertex/*`,
  `amazon-bedrock`, `xai/zdr`) keep fixed rate-card prices until a provider changes its tariff,
  whereas marketplace inference pins such as `morph/fp8` (`deepseek-v4.1-flash-1017`, `kimi-k3.1-pro`)
  and `gmicloud/*` adjust per-million-token rates intraday (for example `morph/fp8` moved from
  `0.089 / 0.50` to `0.072 / 0.641` on DeepSeek V4.1 Flash and `0.692 / 8.82` to `0.721 / 10.809`
  on Kimi K3.1 Pro on 2026-11-15). Treat the table below as a dated snapshot, `models --refresh` as
  the live catalog rate, and each response's `usage.cost` in the ledger as the billed authority.

## The sixteen models, snapshot 2026-11-15

Prices below are the pinned endpoint's catalog price per million tokens (in / out) recorded during
the 2026-11-15 scratch benchmark and full 16-model paid `probe` (`$0.0217` total, run in isolated
`/tmp/pq_scratch` state rather than inside any project workspace). On this account,
`anthropic/claude-fable-5.2` is pinned to `google-vertex/global` because `amazon-bedrock` is
BYOK-only for Fable 5.2.

| model | pinned endpoint | $/Mtok (snapshot) | starting use |
| --- | --- | --- | --- |
| `openai/gpt-6-luna` | `openai/flex` | 0.05 / 0.25 | ultra-cheap bulk passes; accurate plot numbers and 0.967 UI button IoU at ~$0.00012/call |
| `z-ai/glm-5.3-flash` | `gmicloud/fp8` | 0.075 / 0.25 | ultra-cheap open-weight pass (~$0.00012/call); fast prose and plot checks, looser boxes (0.841 IoU) |
| `deepseek/deepseek-v4.1-flash-1017` | `morph/fp8` | ~0.07-0.09 / 0.50-0.64 (live) | cheap bulk description; reasoning ate a 2500-token cap on a real photo and returned nothing |
| `google/gemini-3.8-flash` | `google-vertex/global/flex` | 0.375 / 1.875 | bulk passes: plots, tables, first-pass inventory (~$0.0006/call; flex latency can spike) |
| `xiaomi/mimo-v2.6-pro` | `gmicloud/bf16` | 0.326 / 0.652 | captioning only: boxes failed the card test, exhausted 2500 tokens on a photo, and stalled 293s on probe |
| `openai/gpt-6.1-terra` | `openai/flex` | 0.5 / 2.5 | default general `look` work (~$0.0011/call): BenchLM 77.4, exact coordinates (0.982-0.99 IoU), low reasoning overhead |
| `moonshotai/kimi-k3.1-pro` | `morph/fp8` | ~0.69-0.72 / 8.82-10.81 (live) | strongest open-weight multimodal reader (BenchLM 72.4, 0.982 UI IoU) for cross-family comparison |
| `openai/gpt-6.1-sol` | `openai/flex` | 1 / 5 | dense inventory, localisation (0.982-0.99 IoU), and chart analytics (Plotly 43/43); reasoning is mandatory |
| `google/gemini-3.1-pro-preview` | `google-vertex/global/flex` | 1 / 6 | constrained comparison between named candidates |
| `google/gemini-4-hydrogen` | `google-vertex/global` | 1.5 / 7.5 | fast Gemini 4 reader (Chartography 66.6%, Plotly 43/43, AA Index 54 Xhigh / 51 High / 41 Med; no Vertex flex pin yet) |
| `x-ai/grok-4.7` | `xai/zdr` | 2 / 6 | second opinion and blunt critique; refuses headings instead of inventing them |
| `anthropic/claude-sonnet-5.5` | `amazon-bedrock` | 2 / 10 | UI and computer-use specialist (OSWorld-2.1 83.9%, BenchLM 78.9, 1.7-2.3s latency, 0.981 UI IoU) |
| `google/gemini-4-argon` | `google-vertex/global` | 2 / 10 | strong Gemini 4 reading (AA Index 50); superseded on intelligence at equal price by `gemini-4-carbon` |
| `google/gemini-4-carbon` | `google-vertex/global` | 2 / 10 | highest-intelligence Gemini 4 flagship (AA Index 60) at the same `$2/$10` price as Argon |
| `anthropic/claude-opus-5.5` | `amazon-bedrock` | 4 / 20 | geometry, shadow and camera reasoning, awkward judgement calls (BenchLM 85.1) |
| `anthropic/claude-fable-5.2` | `google-vertex/global` | 8 / 40 | highest overall multimodal accuracy (BenchLM #1 at 90.4); reserve for decisive tie-breakers |

## Three measured tests

Neither is a capability ranking: each uses one image per model. Read the card test as output-format
and coordinate evidence, and the photograph test as evidence about scene reading, reasoning cost and
the two questions models answer badly (heading, light direction).

### Test 1: a synthetic card

One synthetic card (640x480: red square, blue ellipse, large "42"), identical prompt, effort `low`,
4000-token allowance, asked for the number and both boxes as fractions.

| model | number | IoU square | IoU ellipse | cost | seconds | reasoning tokens |
| --- | --- | --- | --- | --- | --- | --- |
| `gpt-6.1-sol` | 42 | 0.99 | 0.99 | $0.00070 | 1.8 | 0 |
| `claude-opus-5.5` | 42 | 0.99 | 0.99 | $0.00342 | 1.9 | 0 |
| `gpt-6.1-terra` | 42 | 0.99 | 0.99 | $0.00050 | 2.2 | 58 |
| `gemini-3.8-flash` | 42 | 0.98 | 0.98 | $0.00149 | 101 | 498 |
| `gemini-3.1-pro-preview` | 42 | 0.96 | 0.97 | $0.00156 | 190 | 0 |
| `deepseek-v4.1-flash` | 42 | 1.00 | 0.80 | $0.00069 | 6.5 | 1053 |
| `grok-4.7` | 42 | 0.78 | 0.78 | $0.00367 | 5.2 | 305 |
| `gemini-4-argon` | 42 | 0.70 | 0.98 | $0.00307 | 5.3 | 0 |
| `mimo-v2.6-pro` | 42 | 0.00 | 0.19 | $0.00059 | 8.3 | 298 |

What it supports: every model read the number and returned parseable JSON; three models returned
boxes accurate to about 1% and agreed with each other to four decimals; Grok's boxes carried a
consistent +0.02 bias on both axes, which is the kind of error a pixel check catches and a prose
answer hides; Gemini 4 Argon extended one box into the number; MiMo returned boxes that look like
grid guesses; DeepSeek produced a pixel-exact square and a loose ellipse while spending 1053
reasoning tokens at low effort.

Latency on the `flex` pins varied by two orders of magnitude: the same Gemini 3.8 Flash prompt took
2 s, 48 s and 101 s on different calls, and Gemini 3.1 Pro took 190 s. Raise `--timeout` before
concluding a flex call has failed.

### Test 2: a real photograph

The photograph is the frame behind the geolocation example in `references/workflow.md`, prepared at
1400 px: a 3264x2448 phone-camera frame taken on a hillside, looking down a valley with a village and
warehouses below. Identical six-part prompt (foreground with coordinates, every building with a
roof-centre coordinate, terrain, light, compass heading, falsifier), effort `low`, 2500-token
allowance, one call per model, $0.0822 for the panel.

The scoring facts were measured from the pixels of that file, not taken from any model: orange
flower mass at (0.10, 0.87), same class spread over x 0.06-0.16, y 0.83-0.92; the orange-banded
warehouse band at x 0.48-0.61, y 0.54-0.59 (1014 px, the largest orange object below the skyline,
against 42 px in the village at x 0.18-0.24); saturated blue roofs concentrated in the right half at
y 0.47-0.55 (332 of 371 blue pixels at a coarse scale), with small blue village roofs at x 0.13-0.24;
a hazy far ridge at x 0.75-1.00, y 0.33-0.38; a high left ridge cresting at y 0.18 around x 0.2-0.35.
Independent truth for light and heading comes from the EXIF clock and sun geometry: 10:42 local
time, sun azimuth 147.5, altitude 44.7, camera facing roughly west, so shadows run to the image
right.

| model | cost | sec | answer | flowers at (0.10, 0.87) | orange band at (0.54, 0.56) | shadows right | heading |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `gpt-6.1-sol` | $0.00818 | 19 | 46 roofs with boxes | prose only | building yes, orange no | yes | refused |
| `claude-opus-5.5` | $0.03576 | 20 | full, richest prose | yes, (0.13, 0.91) | yes | yes | **20 deg** |
| `gemini-4-argon` | $0.01217 | 19 | full, 23 roofs | yes, (0.13, 0.91) | yes | **no, shadows left** | **340 deg** |
| `gpt-6.1-terra` | $0.00245 | 9 | 20 roofs | prose only | building yes, orange no | yes | refused |
| `gemini-3.8-flash` | $0.00146 | 23 | 11 roofs | yes, (0.10, 0.88) | yes | **no, shadows left** | **30 deg** |
| `grok-4.7` | $0.01416 | 27 | 10 roofs | "flower pots" | yes | yes | refused |
| `gemini-3.1-pro-preview` | $0.00389 | 24 | 20 roofs | prose only | building yes, orange no | yes | refused |
| `deepseek-v4.1-flash` | $0.00162 | 23 | **none** | - | - | - | - |
| `mimo-v2.6-pro` | $0.00247 | 76 | **none** | - | - | - | - |

What it supports:

- **A real scene costs far more reasoning than a test card.** At the same effort and a 2500-token cap,
  DeepSeek and MiMo spent all 2500 tokens on reasoning and returned `content: null` with
  `finish_reason: length`, fully charged. On the card that cap still left DeepSeek answering, using
  1053 reasoning tokens. Sol needed 51 reasoning tokens for the photograph, Terra 45, Opus 267, Grok
  1401.
- **Every model that gave a compass heading was wrong**, including Opus 5.5: it said 20 (hedged as
  low confidence), Gemini 4 Argon 340, Gemini 3.8 Flash 30, against a camera facing about 270. The
  four that refused (Sol, Terra, Grok, Gemini 3.1 Pro) were right to refuse. Supply the sun position
  or a known bearing in the prompt.
- **Light direction is the least reliable prose claim.** Two of seven reversed it: Argon put the sun
  behind-right with shadows left, Flash front-right with shadows left, and the photograph runs the
  other way. Shadow centroids can be measured from pixels, which is what settled the heading in the
  geolocation task.
- **Granularity is not discrimination.** Sol returned the longest inventory, 46 roof centres at three
  decimal places, and never flagged the orange bands on the building at (0.54, 0.56) that the whole
  matching test rested on. Ask for the feature you intend to match on.
- **Coordinates several vendors repeat are probably real.** Repetition narrows a coordinate without
  guaranteeing it.
- **The pins held.** Each call reported the provider its pin names (Morph, GMICloud, OpenAI, Amazon
  Bedrock, Google, xAI).

### Test 3: matplotlib plot defects and UI checkout card (2026-11-15)

Nine value-frontier models were tested in `/tmp/pq_scratch` at `--effort low --max-tokens 1600`
(`$0.0413` total across 18 calls) on two 2026-11-15 synthetic targets: (A) a 1200x750 matplotlib
validation plot containing two exact series values (`peak=87.4%`, `ep30_base=80.4%`), a label
straddling both the `y=85.0%` dashed threshold line and the `Hydrogen-LoRA` curve, and a batch-size
note sitting directly on the bottom x-axis spine; and (B) a 1280x800 checkout UI screenshot
(`#INV-9042`, `$42.50`, disabled wire button, and primary green pay button at
`[0.6562, 0.3375, 0.9297, 0.4175]`).

| model | plot cost | plot sec | plot rtok | plot defects caught | UI cost | UI sec | UI IoU |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `gpt-6-luna` | $0.00013 | 3.5 | 179 | line + axis | $0.00012 | 5.1 | 0.967 |
| `glm-5.3-flash` | $0.00011 | 4.0 | 1 | line + curve + axis | $0.00013 | 2.2 | 0.841 |
| `gemini-3.8-flash` | $0.00057 | 12.1 | 0 | line + axis | $0.00063 | 12.6 | 0.970 |
| `gpt-6.1-terra` | $0.00110 | 10.3 | 94 | line + curve + axis | $0.00108 | 11.9 | 0.982 |
| `kimi-k3.1-pro` | $0.00601 | 6.6 | 526 | line + axis | $0.00341 | 2.5 | 0.982 |
| `gpt-6.1-sol` | $0.00188 | 4.2 | 33 | line + axis | $0.00199 | 2.6 | 0.982 |
| `gemini-4-hydrogen` | $0.00538 | 3.6 | 407 | line + axis | $0.00426 | 2.5 | 0.974 |
| `claude-sonnet-5.5` | $0.00381 | 2.3 | 0 | line + curve + axis | $0.00406 | 1.7 | 0.981 |
| `gemini-4-carbon` | $0.00327 | 4.5 | 0 | line + axis | $0.00341 | 4.5 | 0.962 |

All nine models read `87.4%`, `80.4%`, `#INV-9042`, and `$42.50` accurately. `gpt-6.1-terra`
(`~$0.0011/call`) combined exact coordinates (`0.982` IoU), low reasoning overhead, and strong
general multimodal ranking (BenchLM `77.4`), making it the strongest default for `look` calls at
`--effort low`. `gpt-6-luna` (`~$0.00012/call`) delivered 9x cheaper bulk checks with `0.967` IoU.
In the `$1.50-$2.00` input bracket, `gemini-4-hydrogen` (`2.5-3.6s`) is fast on standard Vertex for
chart-heavy work, `claude-sonnet-5.5` (`1.7-2.3s`) leads UI speed and subtle overlap detection, and
`gemini-4-carbon` matches `gemini-4-argon` on price while leading it by 10 points on Artificial
Analysis Intelligence Index (`60` vs `50`).

## Choosing when the task matters

Use one cheap strong model first (`gpt-6.1-terra` for general UI/plot/coordinate checks,
`gemini-3.8-flash` or `gpt-6-luna` for bulk sweeps), read its answer, follow up in the same
`--thread` if a crop or sharper question can settle it, and bring in a second opinion
(`gemini-4-hydrogen` or `gpt-6.1-sol` on charts, `claude-sonnet-5.5` on dense UI, `gemini-4-carbon`,
`claude-opus-5.5`, or `claude-fable-5.2` on hard scenes) when the decision turns on an ambiguity you
cannot measure directly in pixels.

Reasoning effort moves cost more than model choice does. `low` is enough for inventory and reading;
reserve `high` for geometry, and give it 6000 or more output tokens so reasoning does not eat the
answer.
