# Multi-round investigation

For questions that need several looks: find an object or place in a photo, debug a visual artifact,
choose between candidates, or derive a measurement the eye cannot give directly. One call rarely
settles these; going back and forth with focused prompts and crops often does.

## Two ways to run multiple rounds

1. **Same conversation (`--thread NAME` / `look(..., thread=NAME)`):** Best when iterating on an
   image or design: ask for an inventory, challenge a questionable claim ("look closely at row 3;
   is that 8 or 3?"), attach a native-resolution detail crop on Turn 2, or switch `--model` on Turn 3
   to have a stronger model review the earlier reading with full context.
2. **Fresh independent calls (`ask` without `--thread`, or `panel`):** Best when you want an
   unbiased second opinion that is not anchored by the first model's hypothesis. Once two independent
   calls disagree, you can bring both crops into a decisive follow-up or check the disagreement in
   pixels.

Record durable findings from each round in your normal notes (`NOTES.md` or project files) as soon
as you verify them; scratch threads under `/tmp/pq_scratch/vision/threads/` are working state for the
active investigation, not a substitute for project documentation.

## The division of labour

Vision models are evidence extractors, not oracles. They are good at naming what is in a frame,
putting approximate numbers on where it sits, describing materials and relative positions, and
reading text that is actually legible. They are unreliable at free recall ("where was this taken"),
at judging which of two similar things is true without both in front of them, and at any question
whose answer depends on detail smaller than a few pixels.

Everything else should come from sources you control: map and registry queries, EXIF, sun and
shadow geometry, pixel measurements on the original file, a database, the user's own knowledge.
Build the candidate set there. Use the models to describe the frame and to test candidates, not to
invent them.

## Round structure

1. **Frame the problem with facts the model cannot see.** Date, local time, device, field of view,
   sun position, measured percentages of sky and ground, known scale references. Say which numbers
   are measured and which are assumptions.
2. **Ask for an inventory with coordinates.** "List every building, with a box as fractions of the
   image", "give the base and shadow-far point of this vase". Numbers can be checked against pixels;
   adjectives cannot.
3. **Challenge and ask what would falsify the answer.** In the next `--thread` turn (or a fresh
   call), ask what observation would rule out the leading hypothesis, then test that falsifier.
4. **Crop from the original at native resolution** into `/tmp/pq_scratch/` (or default `prep`),
   using the regions identified in Round 2, and attach the crop on the follow-up turn. Magnifying a
   blurred crop recovers nothing; if the detail is not there, "not legible" is the honest result.
5. **Compare, do not recall.** When candidates exist, put the target beside them, label the images,
   state how each was oriented and cropped, and ask which are contradicted and by what.
6. **Close with a decision record in your notes.** One line in `NOTES.md` or the deliverable: the
   claim that decided it, the measurement that supported it, and what observation would overturn it.

## Reading the answers

- **Score claims, not confidence.** Count named contradictions and checkable coordinates rather than
  self-reported confidence percentages.
- **Expect silent revisions.** A model can reverse an earlier turn without mentioning the change.
  Use `vision.py threads show <name>` to review all turns when needed, verify the deciding claim, and
  write the verified conclusion into `NOTES.md`.
- **Measure the light; do not read it.** Compute shadow centroids in pixels rather than trusting
  prose descriptions of sun direction.
- **Reasoning tokens are output tokens.** Give scene and inventory work 4000+ tokens, and 6000+ for
  a deliberate high-effort geometry pass.
- **Do not ask for text that cannot be there.** Decide from the pixel height of the text before
  paying for a transcription.

## When to stop

Stop when another call cannot change the decision, when the remaining uncertainty is below the
resolution of the source image, or when the next step is a measurement you should do yourself.
A panel of three models that disagree is a finding to report, not a reason to buy a fourth opinion;
pick the disagreement apart with pixel checks instead.
