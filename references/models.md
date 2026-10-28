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
  frame cost $0.000567 on `google-vertex/global/flex` and $0.000938 unpinned.
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
| `x-ai/grok-4.7` | `xai/zdr` | 2 / 6 | second opinion, blunt critique; unrated beyond one test |
| `xiaomi/mimo-v2.6-pro` | `gmicloud/bf16` | 0.37 / 0.739 | captioning and description only; boxes were wrong in testing |
| `deepseek/deepseek-v4.1-flash-1017` | `morph/fp8` | 0.103 / 0.6 | cheapest calls; spends heavily on reasoning before it answers |

## One measured test, and what it does and does not show

One synthetic card (640x480: red square, blue ellipse, large "42"), identical prompt, effort
`low`, 4000-token allowance, asked for the number and both boxes as fractions. Only one image per
model was tested, so read this as output-format evidence, not a capability ranking.

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

Earlier evidence collected on real photographs, which no single test card can reproduce: open-weight
and mid-tier models spend most of their output on reasoning and truncate when the allowance is
small; prose answers with shading or lighting arguments were the ones that failed an independent
pixel check, while numeric claims could be checked and mostly survived; and confidence percentages
were uncalibrated in both directions.

## Choosing when the task matters

Use one cheap strong model first (`gpt-6.1-terra` or `gemini-3.8-flash`), read its answer, then buy
a second opinion only if the answer turns on something you cannot verify yourself. Spend the
expensive models on the question that decides the outcome, not on a broad sweep: in the worked
geolocation task the decisive comparison cost $0.09 on Gemini 3.1 Pro, while $0.96 on the most
expensive model produced a fine description and no discriminating claim.

Reasoning effort moves cost more than model choice does. `low` is enough for inventory and reading;
reserve `high` for geometry, and give it 6000 or more output tokens so the reasoning does not eat
the answer.
