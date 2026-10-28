# Multi-round investigation

For questions that need several looks: find an object or place in a photo, choose between
candidates, or derive a measurement the eye cannot give directly. One call rarely settles these;
a sequence of narrow, checkable calls often does.

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

A geolocation investigation that produced this guidance found its answer this way. No model, asked
cold, named the correct place; every free guess was wrong. What worked was an inventory of buildings
with fractional coordinates, matched by code against map data, then one call that showed the
photograph beside four candidate aerials and asked which was contradicted. The cheap model that did
the comparison was first on the list of candidates the user checked, and it was the true site.

## Round structure

1. **Frame the problem with facts the model cannot see.** Date, local time, device, field of view,
   sun position, measured percentages of sky and ground, known scale references. Say which numbers
   are measured and which are assumptions. A model given no geometry will invent some: asked for a
   compass heading from a frame with no north reference, three of seven models answered 20, 30 and
   340 degrees for a camera that was facing about 270.
2. **Ask for an inventory with coordinates.** "List every building, with a box as fractions of the
   image", "give the base and shadow-far point of this vase". Numbers can be checked against pixels;
   adjectives cannot. Check the boxes before you build on them: several models are accurate to a few
   percent, and that is enough to match against imagery or to crop.
3. **Ask what would falsify the answer.** A heading, a name, a matching landmark. Then go and test
   the falsifier yourself. A model that names its own killer gives you a test; a model that only
   asserts a conclusion gives you nothing.
4. **Crop from the original at native resolution**, using the regions the model asked for, and say
   which crop is which in the prompt. Magnifying a blurred crop recovers nothing. If the detail is
   not there, the answer is "not legible", and that is a result.
5. **Compare, do not recall.** When candidates exist, put the target beside them, label the images,
   state how each was oriented and cropped, and ask which are contradicted and by what. Ask for the
   contradiction list even when one candidate looks right: the list is what makes the choice
   checkable, and it is your fallback when none of them matches.
6. **Close with a decision record.** One line: the claim that decided it, the measurement that
   supported it, and what observation would overturn it.

## Reading the answers

- **Score claims, not confidence.** In the worked task one model put 65% on the wrong district and
  100% on the right aerial; neither number meant anything. Its four named contradictions were
  better evidence than its percentage, and three of the four survived an independent check.
- **Expect silent revisions.** The same model can say "cannot resolve left or right" in one round
  and "right, 75-80%" in the next, or move a bearing by 60 degrees without mentioning the change.
  Keep every transcript, treat the newest answer as the current belief, and quote the revision when
  you report. A summary that stops at round 1 can keep an answer the model itself abandoned.
- **Prefer the answer that is checkable to the one that sounds confident.** A number you can verify,
  a named feature you can find on a map, or a stated falsifier beats fluent prose.
- **Measure the light; do not read it.** Two of seven models reversed which way the shadows run on
  the same photograph. A shadow centroid against a known base is a measurement you can make yourself
  and one the model cannot talk its way around.
- **Reasoning tokens are output tokens.** Low effort still spends hundreds of them on some models,
  and a high effort with a small token allowance returns an empty answer with
  `finish_reason: length`, fully charged. On a real photograph at effort `low`, two of nine models
  burned a 2500-token cap on reasoning and returned nothing. Give scene and inventory work 4000+
  tokens, and 6000+ for a deliberate high-effort geometry pass.
- **Do not ask for text that cannot be there.** At 400-800 m a sign is a few pixels tall. A good
  model says so and spends your money saying it; a weaker one invents a plausible transcription.
  Decide from the pixel scale before you ask.

## When to stop

Stop when another call cannot change the decision, when the remaining uncertainty is below the
resolution of the source image, or when the next step is a measurement you should do yourself.
A panel of three models that disagree is a finding to report, not a reason to buy a fourth opinion;
pick the disagreement apart with pixel checks instead. Keep a per-call cost record and compare the
marginal cost of a round with what that round changed.
