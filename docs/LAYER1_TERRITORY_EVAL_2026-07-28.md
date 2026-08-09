# Layer 1 territory exploration evaluation

Date: 2026-07-28

> Historical evaluation note: this interim recommendation was superseded by a
> completed isolated-clone real-project comparison. The durable summary below
> records the decision without publishing raw project/model transcripts.

## Final real-project decision

Adopt divergent exploration as the canonical generated Layer 1 workflow while
retaining explicit human architecture selection and application gates.

| Metric | Existing Gemma | Divergent Gemma | Divergent Qwen |
| --- | ---: | ---: | ---: |
| Raw candidates | 75 | 229 | 257 |
| Unique semantic families | 14 | 219 | 238 |
| Generic repetition | 56.0% | 24.6% | 24.4% |
| Candidate usefulness | 4.0% | 93.4% | 93.8% |
| Operational capabilities | 0 | 44 | 50 |
| Retained non-pillar territories | 0 | 212 | 226 |

Both divergent runs completed every required Product Discovery lens, the
adversarial pass, and multiple unselected architecture options. The comparison
therefore attributes the material quality gain to the breadth-first workflow,
not candidate count or model size alone. Raw responses, local paths, database
dumps, and runtime logs remain local evaluation artifacts and are intentionally
excluded from the public repository.

## Decision

Keep the new exploration workflow as an explicit experimental Layer 1 mode.
Do not replace the existing default yet. The early evidence shows a large
semantic-breadth improvement, but local runtime and structured-output sizing
still need deliberate product controls.

## Controlled fixture

Both arms use fixture hash
`5753b620a75a2e597ddf8c4eb1b8ddd0ba30c847adee49317e13f631c4c52055`
and the same three Product Discovery lenses:

1. Actors, Authority, and Decision Rights
2. Enterprise Administration and Operations
3. Data, Integrations, and Evidence Quality

The divergent arm uses independent calls, 15 raw candidates per lens,
contrastive exclusions, prompt version 2, required discovery attribution, and
no pillar synthesis inside the divergence call.

## Confirmed results

| Arm | Raw | Semantic families | Lens adherence | Generic repetition | Usefulness | Malformed |
|---|---:|---:|---:|---:|---:|---:|
| Existing Gemma | 18 | 5 | 0.3333 | 0.7222 | 0.5000 | 0.0000 |
| Divergent Gemma, 8k diagnostic | 15 preserved before failure | diagnostic only | diagnostic only | diagnostic only | diagnostic only | schema truncation |
| Divergent Gemma, 10k/2400s diagnostic | 30 preserved before timeout | 18 | 0.6667 | 0.0000 | 1.0000 | 0.0000 |
| Divergent Gemma, final | 45 | 34 | 1.0000 | 0.0000 | 1.0000 | 0.0000 |
| Divergent Qwen control | 45 | 26 | 1.0000 | 0.0889 | 0.9111 | 0.0000 |

Additional coverage and runtime:

| Arm | Actor coverage | Enterprise obligations | Operational capabilities | Elapsed |
|---|---:|---:|---:|---:|
| Existing Gemma | 6 | 3 | 1 | 21m 2s |
| Divergent Gemma, final | 5 | 3 | 9 | 1h 27m 39s |
| Divergent Qwen control | 5 | 3 | 13 | 43m 57s |

The existing arm repeated five of six pillar names across multiple lenses. The
divergent diagnostics produced concrete territory such as schema mapping,
entity resolution, source-reliability scorecards, evidence decay,
privacy-preserving intake, time-bound delegation, just-in-time authority
elevation, multi-actor concurrence, emergency kill-switches, and quantitative
authority limits.

## Sizing evidence

- Eighteen full-attribution candidates could not reliably fit the tested
  8,000-token structured-output envelope.
- One 15-candidate lens also crossed 8,000 output tokens.
- One valid response exceeded the initial 2,400-second HTTP timeout.
- The final controlled setting is therefore 15 candidates, 10,000 output
  tokens, and a 3,600-second timeout.
- These are evaluation settings. The product policy remains configurable and
  the production target remains 18.

The checkpoint design worked as intended: completed raw candidates survived
later schema and timeout failures, and every failure retained its explicit
attempt state.

## Model control

The stronger model did not produce more semantic families than Gemma: it
produced 26 versus Gemma's 34. Both linked all three enterprise obligations.
Qwen made more of those links through explicit affected-ID fields and produced
13 operational capabilities versus Gemma's 9. It also completed the fixture in
about half the time after the runtime was configured for one slot and 14 GPU
layers.

This means the breadth gain is primarily attributable to the divergent
workflow, not simply a larger model. Model capability still matters for
classification discipline, obligation coverage, and runtime.

Exact model provenance:

- Gemma: 10,685,012,800 bytes,
  SHA-256 `70d04059c74be85c5e709921f05acac412b8b8f24f3ee7dd07e91ddc5f4d4de8`
- Qwen: 22,663,387,424 bytes,
  SHA-256 `0b21525e972670ed59e1812e170b27c26355381f0656ecc4e25617ece7dac58b`

## Interpretation

The experiment falsifies the idea that this model can only produce the
old five-part lifecycle. Quantity, contrastive exclusion, independent context,
and required source attribution materially change its output. It does not yet
prove that high-volume exploration should be mandatory: latency is substantial,
and broader candidate sets still require human classification and later
architecture synthesis.

The practical next product step is to keep and refine this branch, but not flip
the default yet:

1. retain the existing fast pillar path;
2. offer territory exploration as an intentional breadth pass;
3. preserve every candidate and disposition;
4. let the user synthesize pillars only after reviewing coverage;
5. show source attribution separately from affected-context attribution in review;
6. validate the mode with a real user project before making it the default.
