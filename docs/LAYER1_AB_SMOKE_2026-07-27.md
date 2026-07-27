# Layer 1 baseline vs stateful discovery-loop smoke A/B

Date: 2026-07-27

## Protocol

- Same published organizational-intelligence brief.
- Same published Product Discovery fixture.
- Same local `gemma-4-12b-it-UD-Q6_K_XL` server process.
- Same target of six raw candidates per round.
- Embeddings disabled in both isolated SQLite databases.
- Baseline worktree: `C:\Users\Fresc\Feature_gen-layer1-ab-baseline`
- Variant worktree: `C:\Users\Fresc\Feature_gen-layer1-ralph`

This is a paired smoke test, not a statistically meaningful benchmark.

## Completed one-round comparison

| Measure | Current baseline | Stateful discovery loop |
|---|---:|---:|
| Raw candidates | 6 | 6 |
| Normalized candidates | 4 | 5 |
| Persisted pillars | 4 | 5 |
| Persisted unique families | 4 | 5 |
| Raw candidates with a durable disposition | unavailable | 6 of 6 |
| Explicit normalization drops | unavailable | 1 |
| Undispositioned ledger rows | unavailable | 0 |
| Critic novelty | 85 | 85 |
| Critic saturation | medium | medium |
| Model-call time | 942.2 seconds | 1035.4 seconds |

Baseline pillars:

1. Privacy-Preserving Evidence Architecture
2. Causal Systems Modeling
3. Simulated Intervention & Governed Action
4. Closed-Loop Learning & Impact Analysis

Variant pillars:

1. Systemic Modeling
2. Evidence Acquisition
3. Simulation & Diagnosis
4. Governance & Action
5. Learning & Feedback

## What the test supports

- The variant preserved every raw-candidate outcome. Five were accepted and one was explicitly marked `normalization_dropped`.
- The baseline collapsed six raw candidates to four normalized candidates without a durable per-candidate disposition.
- The variant persisted one more pillar/family in this run.
- The variant's run and lens state point to the exact published discovery revision.
- Critic output is stored on the active lens and cannot terminate unvisited required lenses.

## What the test does not support

- It does not yet show a materially broader product architecture. The two pillar sets are close semantic variants of the same evidence-to-learning lifecycle.
- The discovery-guided `Actors, Authority, and Decision Rights` lens did not produce an explicit enterprise administration or decision-rights pillar.
- Both critics still identified Data and Integrations as uncovered.
- The variant was about 9.9 percent slower in this sample.
- One run cannot separate loop quality from ordinary model sampling variance.

## Two-round baseline failure

The attempted two-round baseline completed round one, then failed in round two during pillar assessment after a normalization repair. The final error was:

`Structured pass failed after 2 attempts for pillar_assessment_response: llama.cpp request timed out`

The failed arm produced eight model-call records and retained its four round-one pillars. Its database is preserved at:

`C:\Users\Fresc\Feature_gen-layer1-ab-baseline\ab-results\baseline-run1.sqlite3`

## Decision

Keep the stateful loop as an experiment, not as a merge-ready replacement yet.

The result validates the smallest orchestration changes:

- a durable lens queue;
- discovery revision lineage;
- lens-local critic authority;
- complete candidate dispositions.

It does not justify additional agent orchestration. The next improvement should be prompt/routing precision: make each lens explicitly avoid regenerating already-covered generic lifecycle families and score whether its own discovery territory was actually covered. Then run at least three paired seeds across the full required-lens queue.
