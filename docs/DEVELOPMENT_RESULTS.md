# Development results — 2026-09-23

## Delivered

The v0.2 server provides a persistent inquiry record with strict typed inputs, immutable event history, precise revision references, atomic batches, idempotency, concurrent-edit checks, and import/export replay. The board invalidates dependent judgments when evidence changes; independent support survives. Claims can remain uncertain, contested, or explicitly refuted in scope after an attributed human review. No model judgment can grant that review.

Direct Jev assessment is optional. OpenRouter is the default route; native TypeSafe is explicit. Requests contain a bounded selection of source–claim pairs and case context. Independent questions share one request. Typed answer validation, overall deadlines, cancellation, and a pre-commit case-sequence check prevent failures or stale outputs from becoming saved assessments. Results preserve actual model, rubric, distribution, and request fingerprint; batch usage is stored with the idempotent response.

Check comparisons, decisions, and resolutions are available as declared records and deterministic views. They do not execute actions, prove constraints satisfied, or establish domain-level usefulness. The host still generates explanations and gathers evidence.

The original pipeline and 30 regression tests remain in the `legacy` directories. Active legacy tool names fail with migration guidance. This preserves the historical baseline without endorsing its eliminations or confidence.

## Verification

- Current unit/contract suite: see the final `uv run pytest` output for the authoritative count; this report does not treat historical tests as quality evaluation.
- Offline and live real-stdio demos both create an inquiry, record an assessment, correct the evidence, invalidate the old assessment, restart the server, and verify identical export history.
- The successful live stdio run returned `typesafe/jev-1.13-20260917`, labelled the synthetic presence/absence pair `conflicts`, and reopened it as `untested` after correction. Provider-reported request cost was $0.00003129 (745 input, 49 output tokens).
- An initial demo assertion assumed a structured payload for a bare `dict` annotation; the SDK returned text JSON. The adapter now declares `dict[str, Any]` so it advertises structured output schemas, and the demo supports both representations. This was a harness/contract issue, not lost database history.

## Live synthetic assessment pilot

Protocol and labels were saved before the scored runs: [protocol](../evals/PROTOCOL.md), [cases](../evals/cases.json), [labels](../evals/gold.json). The implementing assistant authored both examples and labels. No independent human validation or full inquiry comparison has occurred.

| Run/arm | Correct | Batch latency | Reported cost |
|---|---:|---:|---:|
| First Jev run | 16/16 | 0.743 s | $0.000250992 |
| Paired run, Jev | 15/16 | 0.715 s | $0.000250992 |
| Paired run, DeepSeek V4.1 Flash | 15/16 | 7.921 s | $0.003704184 |

Evidence: [first run](../evals/results/20260923T071303982932Z.json), [paired run](../evals/results/20260923T071428738662Z.json). Jev returned `typesafe/jev-1.13-20260917`; the baseline returned `deepseek/deepseek-v4.1-flash`. Both received the same source/claim cases and relation criteria, but used their respective Choice and chat interfaces. All requests in these reports completed. Latency is end-to-end for a single batch, not p95 or a general speed claim.

The paired run's Jev error was `belief_report`: the reference label was `supports`, but Jev chose `neutral` with confidence 0.15 (neutral 0.37, supports 0.35, unknown 0.28). The chat baseline's error was `belief_truth`: it chose `neutral` instead of reference `unknown`. The source says a person believes C without evidence that C is true; this also exposes a rubric boundary worth independently reviewing.

No labels or rubrics were changed after seeing these results. Jev's mean multiclass Brier scores were 0.089575 and 0.08675; the small synthetic sample cannot establish calibration. The generative baseline did not provide comparable probability distributions. Variation between two Jev runs is visible rather than hidden by reporting only the better run.

**Interpretation:** the direct adapter works, and Jev was faster and cheaper in this measured comparison. It did not beat the baseline's label accuracy in the paired run. These results justify continued advisory experimentation, not automatic acceptance of model judgments or a claim of improved wisdom.

## Remaining evaluation and product work

- Independently authored/reviewed cases and a full multi-turn comparison against ordinary notes, both with and without Jev.
- Actual review burden, decision outcomes, representative claim/belief/science cases, and calibrated thresholds if automation is ever proposed.
- Automatic semantic merging, dedicated deterministic refutation adapters, and optional specialized generation remain unimplemented.
- Human review and source attribution are trusted local caller reports, not authenticated attestations. Imported archives preserve those reports, not independent verification.
- SQLite schema version 1 is supported; unknown versions are rejected. There was no prior persistent schema to migrate. Inquiries are bounded to 500 records/5,000 events; large-corpus scaling has not been tested.
