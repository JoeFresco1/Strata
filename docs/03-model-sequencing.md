# Model Sequencing

SpecForge should support model sequencing for Layer 1, because different models can reveal different pillar families and blind spots.

## Expected behavior

- Let the user choose a sequence of local GGUF models for Layer 1.
- Run the first model as the primary explorer.
- Reload or switch to the next model as a challenger that sees the same accumulated context and attempts to expand it differently.
- Carry forward the accumulated pillar set, coverage summary, and rejected ideas between model phases.
- Track which model introduced each pillar and which lens was active when it appeared.

## Sequencing rules

- Sequencing should be explicit and bounded.
- Do not pretend all models are interchangeable.
- Do not reload models unnecessarily within a round.
- Do not start a new model phase from scratch if the point is to challenge the existing pillar families.

## Provenance

- Each pillar should retain `source_model`.
- Each generation pass should log the model name used for that pass.
- Review should expose the source model so the user can judge which model produced the strongest structure.

