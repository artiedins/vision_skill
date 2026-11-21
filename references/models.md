# Model choice

The allow-list lives in `scripts/vlib/config.py`. Each model has exactly one endpoint tag, and every
request sets `provider.only` to that tag with `allow_fallbacks: false`, so a call either reaches the
pin or fails.

`models` prints the pin, whether it is still in OpenRouter's endpoint list, that endpoint's `health`
flag (`0` is normal; nonzero is a provider-side status and usually means slow or failing calls), and
live per-million-token prices. `models --refresh` skips the six-hour cache.

## Pins and prices

Snapshot 2026-11-21 from `models --refresh`. Prices are the pinned endpoint's rate per million
tokens, in and out; `usage.cost` in the ledger stays the billed authority.

| model | pin | $/Mtok | role |
| --- | --- | --- | --- |
| `openai/gpt-6.1-terra` | `openai/flex` | 0.50 / 2.50 | default for `look` and most work: fast UI, screenshot, document and coordinate reading |
| `google/gemini-3.8-flash` | `google-vertex/global/flex` | 0.375 / 1.875 | cheap bulk passes and the figure check at low effort |
| `google/gemini-4-hydrogen` | `google-ai-studio/flex` | 0.75 / 3.75 | fast Gemini 4 reading; lowest Gemini 4 latency measured |
| `google/gemini-3.1-pro-preview` | `google-vertex/global/flex` | 1 / 6 | constrained comparison between named candidates |
| `google/gemini-4-argon` | `google-ai-studio/flex` | 1 / 5 | strongest all-round Gemini 4 reading |
| `google/gemini-4-neon` | `google-ai-studio/flex` | 1.50 / 7.50 | second Gemini 4 opinion for a decisive tie-break |

Flex service tiers bill at roughly half the standard rate for the same weights. For the three Gemini
4 models the only flex pin OpenRouter lists is `google-ai-studio/flex`; there is no
`google-vertex/*/flex` for them. Every pin above answered a test card on 2026-11-21.

Two facts about flex worth remembering:

- Flex latency is unpredictable. The same Gemini 3.8 Flash card has taken 2 s, 48 s and 101 s, and
  Gemini 3.1 Pro took 98 s and 190 s on different calls. Raise `--timeout` before calling a slow
  response a failure. A `look` call on Terra finishes in 2-4 s.
- An unpinned request can land on a dearer endpoint. Pinning decides the price.

## Measured accuracy and cost

99 items (Game Boy frames and out-of-distribution real-world photographs, 11 scored categories),
`--effort high`, `max_tokens 6000`, fingerprint `29b0203ed3aa9d3c`. Full tables and per-category
scores are in the owning project's `COMBINED_RESULTS.CSV` and `sightbench/results/scores.json`.

| model | macro accuracy | cost for 99 calls | median latency | invalid answers |
| --- | --- | --- | --- | --- |
| `google/gemini-4-argon` | 95.5% | $0.61 | 7.8 s | 0 |
| `google/gemini-4-neon` | 95.5% | $1.80 | 5.1 s | 1 |
| `google/gemini-4-hydrogen` | 95.1% | $0.65 | 2.6 s | 0 |
| `openai/gpt-6.1-terra` | 94.8% | $0.08 | 3.6 s | 0 |
| `google/gemini-3.1-pro-preview` | 94.5% | $1.12 | 6.4 s | 0 |
| `google/gemini-3.8-flash` | 90.7% | $0.63 | 5.7 s | 1 |

Those runs used the standard (non-flex) endpoints for the Gemini models, so flex billing is about
half of the cost column while the weights are the same. Five of the six sit inside one another's 95%
confidence intervals (88.7 to 98.4%), so price and latency decide more than the ranking:

- Terra delivers the top cluster at roughly one seventh the cost of Argon and one twentieth of Neon,
  which is why it is the default.
- Argon, Neon and Hydrogen agree on nearly all items. Neon repeats Argon's score at three times the
  cost, so it is a tie-breaker, not a daily driver.
- Gemini 3.8 Flash is the cheapest Google reader and the right choice for bulk layout checks, where
  it is weakest on fine spatial questions (Game Boy sprite facing) rather than on text or scenes.
- Where the models separate: reading a Game Boy HP bar, naming the direction a sprite faces, and
  ordering crowded small objects. Text, table, cattle-and-vehicle counting and clean photographs
  saturate near 100%.

A blind control (same model, no image) scored 27.7% on the same items, so the set measures seeing
rather than guessing.

## Provider behavior worth expecting

- A pin that no longer exists returns HTTP 404 naming the providers still serving the model. That is
  the intended loud failure; check `models --refresh` and update the list instead of widening the
  pin at call time.
- Account data policy can reject an endpoint that the endpoint list still advertises. Only a paid
  call reveals that, so run `probe` after changing account settings.
- A tag without a region segment matches that provider's regional siblings
  (`amazon-bedrock` covers `amazon-bedrock/us-east-1`, for instance). Use the region form to narrow it.
- Effort `none` is rejected by most pinned endpoints; `low` is the practical floor.

## Claims to distrust

These held across every model tested, so treat them as limits of the task, not of one model:

- **Compass headings.** Every model that gave one was wrong (20, 30 and 340 degrees against a camera
  facing about 270). The models that refused were right. Supply sun position or a known bearing.
- **Light direction.** Two of seven reversed it in prose while the shadows in the pixels ran the
  other way. Measure shadow centroids instead.
- **Self-reported confidence.** Numbers a model puts on its own answer are not calibrated.
- **Inventory length.** The longest list was not the most useful one: it missed the single feature
  the decision rested on. Ask for the feature you intend to match.
