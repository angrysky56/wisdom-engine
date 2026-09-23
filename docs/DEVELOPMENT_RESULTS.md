# Development results — 2026-09-23

## Delivered

The v0.2 server provides a persistent inquiry record with strict typed inputs, immutable event history, precise revision references, atomic batches, idempotency, concurrent-edit checks, and import/export replay. The board invalidates dependent judgments when evidence changes; independent support survives. Claims can remain uncertain, contested, or explicitly refuted in scope after an attributed human review. No model judgment can grant that review.

Direct Jev assessment is optional. OpenRouter is the default route; native TypeSafe is explicit. Requests contain a bounded selection of source–claim pairs and case context. Independent questions share one request. Typed answer validation, overall deadlines, cancellation, and a pre-commit case-sequence check prevent failures or stale outputs from becoming saved assessments. Results preserve actual model, rubric, distribution, and request fingerprint; batch usage is stored with the idempotent response.

Check comparisons, decisions, and resolutions are available as declared records and deterministic views. They do not execute actions, prove constraints satisfied, or establish domain-level usefulness. The host still generates explanations and gathers evidence.

The original pipeline and 30 regression tests remain in the `legacy` directories. Active legacy tool names fail with migration guidance. This preserves the historical baseline without endorsing its eliminations or confidence.

## Verification

- Current unit/contract suite: 78 tests, including 30 preserved legacy tests. This verifies implementation behavior, not reasoning quality.
- Offline and live real-stdio demos both create an inquiry, record an assessment, correct the evidence, invalidate the old assessment, restart the server, and verify identical export history.
- The successful live stdio run returned `typesafe/jev-1.13-20260917`, labelled the synthetic presence/absence pair `conflicts`, and reopened it as `untested` after correction. Provider-reported request cost was $0.00003129 (745 input, 49 output tokens).
- An initial demo assertion assumed a structured payload for a bare `dict` annotation; the SDK returned text JSON. Active tools now use explicit Pydantic output contracts, validated before return and advertised to clients. The demo supports structured content and text JSON. This was a harness/contract issue, not lost database history.
- Archive timestamps now reject invalid or timezone-free values before any writes. Regression tests reproduced the prior acceptance gap, then verified rejection through storage and the MCP import boundary.
- Source and wheel builds succeed. The source distribution explicitly includes project files and excludes unrelated workspace tool symlinks and private `.env` files.

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

The original reports retain per-case results. Later reporting adds confusion counts, class recall, macro accuracy (mean recall over represented reference classes), and explicit missing-cost flags. Original raw artifacts were not rewritten.

## Controlled two-turn revision pilot

The separately [registered protocol](../evals/REVISION_PROTOCOL.md) compares notes, a current ledger board, and the ledger with Jev. Each arm uses the same host model, source events, semantic rubric, and four synthetic cases: correction to another process, withdrawing one of two independent sources, changing a claim's meaning, and receiving conflicting evidence. The scripted initial assessments are supplied to every arm. This tests controlled updating rather than autonomous investigation.

Version 1 had four output-validation failures across twelve trajectories. Completed trajectories answered correctly, but the harness did not retain the invalid replies or their costs. That comparison is inconclusive. The [original artifact](../evals/results/20260923T182019550973Z-revision.json) remains unchanged.

Version 2 supplied the existing reply schema explicitly and retained raw replies, validation details, and usage before validation. It repeated every arm with unchanged cases and reference labels. [Full version 2 result](../evals/results/20260923T182630147427Z-revision.json):

| Arm | Correct initial labels | Valid, correct final labels | Invalid final replies | Reported host cost | Jev cost |
|---|---:|---:|---:|---:|---:|
| Notes | 4/4 | 2/4 | 2 | $0.002481372432 | — |
| Ledger | 4/4 | 2/4 | 2 | $0.004075285896 | — |
| Ledger + Jev | 4/4 | 4/4 | 0 | $0.007217327502 | $0.00028749 |

All 24 version 2 host replies returned usage. Four changed the required `conclusion` key (for example, `conclusion R`), and strict validation correctly rejected them. Their prose was not used to recover or score labels. All schema-valid answers were correct. The observed advantage in completion for the Jev arm does **not** establish a reasoning advantage: failures moved between arms across versions, the sample is tiny, and it is not independently authored or randomized. No further paid rerun was used to seek a favorable result.

Host timings include semaphore queue wait, while the 45-second host timeout starts after acquiring a slot; these figures are not the product adapter's latency contract. The product Jev adapter separately bounds its whole call including queueing. All pilot stores were temporary; no saved user inquiries were modified.

## Remaining evaluation and product work

- Independently authored/reviewed cases and a full multi-turn comparison against ordinary notes, both with and without Jev. The controlled pilot above does not satisfy this requirement; a future protocol should verify native schema support before scoring all arms.
- Actual review burden, decision outcomes, representative claim/belief/science cases, and calibrated thresholds if automation is ever proposed.
- Automatic semantic merging, dedicated deterministic refutation adapters, and optional specialized generation remain unimplemented.
- Human review and source attribution are trusted local caller reports, not authenticated attestations. Imported archives preserve those reports, not independent verification.
- SQLite schema version 1 is supported; unknown versions are rejected. There was no prior persistent schema to migrate. Inquiries are bounded to 500 records/5,000 events; large-corpus scaling has not been tested.
