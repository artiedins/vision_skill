# Model selection and evidence

The fixed allow-list is in `skills/vision_skill/scripts/vlib/config.py`. Use
`python3 skills/vision_skill/scripts/vision.py models --refresh` for current availability, image modality and catalog
prices. A catalog listing is not a guarantee that an account can use a particular endpoint.
Never invent a replacement slug or substitute a model outside the allow-list.

## Starting choices

These recommendations draw on a 2026-09-27 research snapshot. They are task-selection heuristics,
not guarantees on new images. The underlying sources measure different things:

- [Roboflow Vision Evals](https://playground.roboflow.com/evals): detection, counting,
  identification, OCR, extraction and visual reasoning.
- [LMArena vision](https://arena.ai/leaderboard/vision): human pairwise preference. A nearby
  model-family entry is not a measurement of every later version.
- [Artificial Analysis](https://artificialanalysis.ai/): published MMMU-Pro multimodal reasoning.

| allowed slug | starting use | relevant result in the research snapshot |
| --- | --- | --- |
| `anthropic/claude-fable-5` | OCR, an alternative Fable reader | OCR 94.0, identification 100.0 |
| `openai/gpt-6-astra` | difficult localisation and visual reasoning | detection 82.1 mAP@50, reasoning 87.2 |
| `google/gemini-3.1-pro-preview` | stated-class identification, structured data | identification 100.0, extraction 95.9 |
| `anthropic/claude-fable-5.1` | OCR and diagrams | OCR 94.0 |
| `google/gemini-3.8-flash` | plots, tables, affordable general first pass | extraction 97.3, detection 68.1 |
| `anthropic/claude-opus-5.5` | general reasoning and design discussion | MMMU-Pro 87.7, Roboflow overall #3 |
| `openai/gpt-6-sol` | general vision, less costly object localisation | detection 74.7 mAP@50 |
| `openai/gpt-6.1-sol` | general vision, object localisation; upgrade over GPT-6 Sol | AA intelligence index 51.8; no task-specific vision benchmark yet |
| `meta/muse-spark-1.2` | OCR, a lower-cost second reader | OCR 93.6 |
| `z-ai/glm-5.3-flash` | rough bulk descriptions and pre-filtering | weaker task evidence than the premium group |
| `openai/gpt-6-luna` | simple labels with explicit uncertainty | limited task-specific evidence |

A 100.0 identification score applies to the benchmark, not every real-world class. Published
design-generation rankings are not tests of colour perception or aesthetic judgement.
Recommendations for design, image quality and hard cross-image correspondence have weaker
evidence than OCR/extraction/localisation recommendations.

## Costs depend on the whole request

The following are historical observations from an earlier implementation run, not current quotes
or measurements repeated for each task. Most used one 1568x1176 image, low effort, a 600-token
output allowance and a two-sentence prompt. Astra used a larger image and allowance, so it is not
a controlled comparison with the others.

| model short name | reported cost per call, USD |
| --- | --- |
| claude-fable-5 | 0.0285 |
| gpt-6-astra | 0.0713 (2048 px frame, 1500-token allowance) |
| gemini-3.1-pro-preview | 0.0091 |
| claude-fable-5.1 | 0.0294 |
| gemini-3.8-flash | 0.0010 |
| claude-opus-5.5 | 0.0139 |
| gpt-6-sol | 0.0061 |
| muse-spark-1.2 | 0.0043 |
| glm-5.3-flash | 0.0004 |
| gpt-6-luna | 0.0003 |

Use current `usage.cost` for accounting. Image tokenisation, output length, reasoning effort,
provider routing and caching all affect the bill. The historical Gemini input-token counts were
lower for that one image, not proof of a fixed discount for all resolutions or tasks.

The CLI defaults to `--effort high`. Lower it for bulk work where the extra reasoning does not
change the answer; the measured price difference between low and high effort exceeded the
difference between models. `default` omits the effort field. Some endpoints, including previously
tested GLM endpoints, require reasoning and reject `none`; the CLI reports that error instead of
silently changing settings. Reasoning tokens count as output tokens, so a high effort with a
small output allowance can consume the allowance before an answer is returned. Catalog 2026-10-03:
`openai/gpt-6.1-sol` has mandatory reasoning (efforts max/xhigh/high/medium/low, default medium),
takes text, image and file input, and lists $0.000002 prompt / $0.00001 completion per token.

Several models advertise native video, but this CLI sends still images only. See the video-frame
recipe for explicit sampling and timing limitations.
