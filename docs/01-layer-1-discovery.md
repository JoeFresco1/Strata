# Layer 1 Discovery

Layer 1 is the pillar discovery layer. It should produce major product pillars, not subfeatures or implementation details.

## Expected behavior

- Start from the product idea and explore it through multiple discovery lenses.
- Broaden through several rounds until novelty drops or the critic decides the space is saturated.
- Rotate lenses such as outcomes, operations, analytics, onboarding, risk, and integrations.
- Optionally sequence multiple local models so one model explores and the next model challenges or supplements the result.
- Treat later models as challengers that should target blind spots and missing pillar families rather than re-cover known territory.
- Normalize raw candidate pillars back into true Layer 1 concepts before saving.
- Run a pillar-quality assessment pass that clusters similar items into canonical families and rejects items that are too narrow, too implementation-specific, or too broad/vague.

## Pillar rules

- Pillars should be major, strategic buckets.
- Pillars should not be UX screens, workflows, edge cases, or implementation tasks.
- Overlapping concepts should be merged into one canonical family.
- The system should keep a provenance trail with source lens, source model, and quality metadata.

## Stop conditions

- The model starts repeating the same pillar families.
- Consecutive rounds stop adding new pillar families.
- The critic reports saturation.
- Consecutive rounds add too few new concepts.
- The configured round or model-sequence budget is exhausted.

## Review behavior

- The user should review, cut, merge, rename, and prioritize the generated pillars before proceeding.
- The UI should show canonical family, quality score, distinctiveness, and strategic value.
