# Evidence assessment pilot — preregistered before the first scored run

2026-09-23. This is a development diagnostic, not independent evidence of product superiority.

## Frozen material and comparison

`cases.json` has 16 synthetic cases authored by the implementing assistant. `gold.json` contains separately held reference labels from the same author. Labels are never sent to either model. The examples are deliberately simple, cover four relation labels and scope/hypothetical/causal/injection traps, and are not a representative sample of real inquiries. Cases and gold hashes are recorded in each report. Do not edit them after viewing results; label changes need a new dataset version and a documented reason.

The optional comparison baseline is one generative model request containing the same cases and evidence-relation rubric, asking for exactly the same labels. The Jev arm sends a batch of independent Choice questions. This isolates a narrow assessor comparison; it is NOT the full P1/W1 or W1/W1+Jev multi-turn agent experiment. The latter also needs decisions, corrections, review burden, and independent cases.

## Predictions and acceptance

Expectation: Jev correctly labels at least 12/16 cases with zero hard refutations. No prediction of superiority over the generative baseline is made. Semantic neutral/unknown boundaries may be difficult. A confident incorrect support or conflict is a development failure to inspect, regardless of overall accuracy. Provider/validation failure is reported as a failed run, never removed from a success denominator.

Keep Jev assessments advisory regardless of this pilot's accuracy. No confidence cutoff is tuned on these cases. Probabilities remain visible; no automatic correctness threshold is introduced. Hard refutation count must remain zero because the code prohibits model-only refutation.

Report n, per-case labels, distributions/confidence, confusion counts, macro accuracy, average multiclass Brier score, elapsed time, tokens, known cost, missing cost, model requested/returned, rubric and input hashes. Latency from one batch is not a p95 estimate. Test revision/retraction behavior separately with deterministic and real-stdio demos.

## Commands

- `uv run python -m evals.run --live`: Jev pilot with the configured provider.
- `uv run python -m evals.run --live --baseline-model MODEL_ID`: also compare a named OpenRouter chat model (additional paid request).
- `uv run python -m evals.run`: inspect dataset/protocol without network calls.

Provider defaults are OpenRouter and `~typesafe/jev-latest`; override `WISDOM_JEV_PROVIDER` / `WISDOM_JEV_MODEL` for a fixed-version repeat. Reports go to `evals/results/`. Synthetic reports can be committed intentionally. Never add private cases or credentials to this directory without reviewing their contents.

## Broader evaluation still required

Before making effectiveness claims: independently authored held-out cases, repeated paired trials, an editable-notes baseline, identical host budgets, blinded reviews, representative non-debugging cases, and actual review effort. This small same-author pilot cannot satisfy those gates in PLAN.md.
