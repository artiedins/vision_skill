# Model selection and evidence

The allow-list and its pinned endpoints live in `scripts/vlib/config.py`. Each model has exactly
one endpoint tag, and every request sets `provider.only` to that tag with `allow_fallbacks: false`,
so a call either reaches that endpoint or fails. `models` prints the pin, whether it is still in
OpenRouter's live endpoint list, that endpoint's health status and its per-million-token prices;
`models --refresh` skips the six-hour cache.

## How endpoint pinning behaves

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
- Confirm the pin took effect by comparing reported `usage.cost` with the pinned endpoint's price:
  on nine probe calls the two agreed to the last decimal on all nine once cache reads were counted
  at the cache price.

## The nine models, as of 2026-10-28

Prices are the pinned endpoint's catalog price per million tokens, in and out.

| model | pinned endpoint | $/Mtok | starting use |
| --- | --- | --- | --- |
| `openai/gpt-6.1-terra` | `openai/flex` | 0.5 / 2.5 | default general work: cheapest model that gave exact coordinates |
| `openai/gpt-6.1-sol` | `openai/flex` | 1 / 5 | inventory and localisation; reasoning is mandatory, so budget tokens |
| `anthropic/claude-opus-5.5` | `amazon-bedrock` | 4 / 20 | geometry, shadow and camera reasoning, awkward judgement calls |
| `google/gemini-4-argon` | `google-vertex/global` | 2 / 10 | strongest all-round reading; start here when the answer must be right |
| `google/gemini-3.1-pro-preview` | `google-vertex/global/flex` | 1 / 6 | constrained comparison between named candidates |
| `google/gemini-3.8-flash` | `google-vertex/global/flex` | 0.375 / 1.875 | bulk passes: plots, tables, first-pass inventory |
| `x-ai/grok-4.7` | `xai/zdr` | 2 / 6 | second opinion and blunt critique; refuses headings instead of inventing them |
| `xiaomi/mimo-v2.6-pro` | `gmicloud/bf16` | 0.37 / 0.739 | captioning only: boxes failed the card test, and it returned nothing at 2500 tokens on a photo |
| `deepseek/deepseek-v4.1-flash-1017` | `morph/fp8` | 0.103 / 0.6 | cheapest calls of all; reasoning ate a 2500-token cap on a real photo and returned nothing |

## Two measured tests

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

The photograph is the 3264x2448 iPhone frame of a hillside cemetery looking down a valley that the
geolocation task in `references/workflow.md` was solved from, prepared at 1400 px. Identical
six-part prompt (foreground with coordinates, every building with a roof-centre coordinate, terrain,
light, compass heading, falsifier), effort `low`, 2500-token allowance, one call per model, $0.0822
for the panel.

The scoring facts were measured from the pixels of that file, not taken from any model: orange
flower mass at (0.10, 0.87), same class spread over x 0.06-0.16, y 0.83-0.92; the orange-banded
warehouse band at x 0.48-0.61, y 0.54-0.59 (1014 px, the largest orange object below the skyline,
against 42 px in the village at x 0.18-0.24); saturated blue roofs concentrated in the right half at
y 0.47-0.55 (332 of 371 blue pixels at a coarse scale), with small blue village roofs at x 0.13-0.24;
a hazy far ridge at x 0.75-1.00, y 0.33-0.38; a high left ridge cresting at y 0.18 around x 0.2-0.35.
Independent truth for light and heading comes from the EXIF clock and sun geometry: 10:42 KST, sun
azimuth 147.5, altitude 44.7, camera facing roughly west, so shadows run to the image right.

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
- **Every model that gave a compass heading was wrong**, including Opus 5.5, the dearest model on the
  list: it said 20 (hedged as low confidence), Gemini 4 Argon 340, Gemini 3.8 Flash 30, against a
  camera facing about 270. The four that refused (Sol, Terra, Grok, Gemini 3.1 Pro) were right to refuse.
  A heading question with no north reference in the frame produces confident numbers, so supply the
  sun position or a known bearing in the prompt.
- **Light direction is the least reliable prose claim.** Two of seven reversed it: Argon put the sun
  behind-right with shadows left, Flash front-right with shadows left, and the photograph runs the
  other way. Shadow centroids can be measured from pixels, which is what settled the heading in the
  geolocation task.
- **Granularity is not discrimination.** Sol returned the longest inventory, 46 roof centres at three
  decimal places, and never flagged the orange bands on the building at (0.54, 0.56) that the whole
  matching test rested on. Argon, Opus, Flash and Grok named that band; Terra, Sol and Gemini 3.1 Pro
  located the building but not the feature. Ask for the feature you intend to match on.
- **Coordinates several vendors repeat are probably real.** Flowers at (0.10-0.13, 0.88-0.91), the
  orange band at (0.54, 0.55) and the haze at x 0.75-1.00, y 0.33-0.38 came back nearly identical from
  independent families and match the pixels. The left ridge centre was repeated too and was still off
  by 0.05-0.1, so repetition narrows a coordinate without guaranteeing it.
- **The pins held.** Each call reported the provider its pin names (Morph, GMICloud, OpenAI, Amazon
  Bedrock, Google, xAI), so this panel doubles as a second end-to-end check of the routing.

Earlier evidence from the geolocation project that neither test reproduces: open-weight and mid-tier
models spend most of their output on reasoning and truncate when the allowance is small; prose answers
with shading or lighting arguments were the ones that failed an independent pixel check, while
numeric claims could be checked and mostly survived; confidence percentages were uncalibrated in both
directions.

## Choosing when the task matters

Use one cheap strong model first (`gpt-6.1-terra` or `gemini-3.8-flash`), read its answer, then buy
a second opinion only if the answer turns on something you cannot verify yourself. Spend the
expensive models on the question that decides the outcome, not on a broad sweep: in the worked
geolocation task the decisive comparison cost $0.09 on Gemini 3.1 Pro, while $0.96 on the most
expensive model produced a fine description and no discriminating claim.

Reasoning effort moves cost more than model choice does. `low` is enough for inventory and reading;
reserve `high` for geometry, and give it 6000 or more output tokens so the reasoning does not eat
the answer.
