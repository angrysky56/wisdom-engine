# Wisdom Engine: inquiry that can correct itself

Revised 2026-09-23 after inspecting commit `2d27092` and current research.
Status: **v0.2 development implementation available; effectiveness remains unproven**.
Claude's proposal is preserved [unchanged here](docs/PLAN.claude-2026-09-23.md).
The [review and sources](docs/DESIGN_REVIEW.md) distinguish findings from recommendations.

## 1. Purpose

Help a person and their AI investigate a question, notice weak assumptions, revise conclusions when evidence changes, and choose responsible actions under uncertainty.

The useful promise is: **“Show what we know, why we think it, what could change it, and what we can responsibly do next.”**

Keep the original spirit: investigate mechanisms, question attractive stories, expose constraints, and learn by finding errors. Broaden the application beyond debugging. Scientific explanations, disputed claims, social beliefs, and practical decisions require different reasoning; they should share a record without being forced into a contest for one true cause.

Wisdom here means good inquiry and accountable judgment. It is not a numerical score, machine moral authority, or a guarantee that the remaining explanation is true.

## 2. Three possible directions

| Direction | What earns its place | Main weakness | Recommendation |
|---|---|---|---|
| Better reasoning prompt / skill | Almost no infrastructure; host supplies alternatives and checks | Context can lose provenance and earlier corrections | Useful baseline and fallback |
| Persistent inquiry workbench | Durable evidence, explicit dependencies, revision, comparisons, next checks | Requires disciplined records; interpretations can still be wrong | **Recommended core** |
| Autonomous discovery engine | Searches and runs experiments with little intervention | Expensive orchestration and weakly validated authority | Defer until individual capabilities demonstrate value |

Claude's rival board is a useful view within the recommended direction. Underneath, use a small record of claims and their dependencies, borrowing from established truth-maintenance systems. SQLite tables and deterministic projections suffice for the first experiment; a formal solver or general knowledge graph is unnecessary initially.

**The host agent supplies reasoning. The engine preserves provenance, validates structure, tracks changes, and calculates transparent comparisons.** Optional model adapters can propose entries later. The core must work without a model, provider account, network connection, or another project.

## 3. Changes to Claude's proposal

1. **Observed does not mean correctly interpreted.** A real log plus a model's incorrect inference must not eliminate a true explanation. Separate observations from assessments.
2. **Contradicted differs from refuted.** Most evidence changes plausibility; only a necessary prediction with a verified incompatible outcome supports strict, scoped refutation.
3. **Revision is central.** Correcting evidence must invalidate dependent conclusions. An append-only log needs explicit supersession and retraction semantics.
4. **Allow multiple causes and missing explanations.** Explanations can overlap or describe different levels. One live explanation never proves the set was complete.
5. **Checks need decision relevance.** An evenly dividing question can be costly, unreliable, harmful, or irrelevant to the action at hand.
6. **Evaluate the record separately from generation.** A weak specialized generator should not kill useful evidence tracking.
7. **Retire misleading semantics early.** Keep the old system as a historical evaluation arm; don't require new users to pass through unsupported confidence and elimination steps.

## 4. The record

All records have IDs, case ID, author/origin, timestamps, and revision links. Sources retain a locator plus the relevant excerpt or captured result, collection time, and scope. A URL alone does not verify a statement.

| Record | Contents |
|---|---|
| Case | Question; kind (`cause`, `claim`, `belief`, `decision`); scope/time; context; optional incumbent; decision to inform; unresolved gaps |
| Observation | Report or measurement; artifact/source; acquisition method; observed time; process/subject/environment; quality limitations; source/dependency group |
| Claim | Explanation, assumption, interpretation, or belief driver; scope; origin; component/alternative relationships |
| Prediction | Claim revision; observable outcome; required assumptions; test conditions; necessary versus merely expected implication |
| Assessment | Observation and claim revisions; `supports`, `conflicts`, `neutral`, or `unknown`; rationale; interpretation author; assumptions; review state |
| Check | Procedure; possible outcomes; predictions by scenario; cost/time; access requirements; consequences; decision it could change |
| Decision | Options; affected people; hard constraints; assumptions; consequences by scenario; chosen action; reason; reversal/review trigger |
| Resolution | Evidence-supported outcome; unresolved or multiple causes where appropriate; reviewer; scope; follow-up |

An observation records a report about the world, not guaranteed truth. An agent may attach a real tool result but must not turn a prediction into an observation. Enforce origins at ingestion without claiming independent authentication of every artifact.

Keep raw observations separate from summaries and assessments. Two summaries of one log share a source group. Unknown dependence remains unknown; several links are not automatically independent evidence. Do not add support counts as probabilities.

### Revision rules

- Conclusions cite exact record revisions. Corrections create revisions; history remains available.
- Retraction invalidates affected derived results; it does not assert their opposites. Independent valid grounds can still support the same conclusion.
- Assumption changes trigger recomputation. Material changes to a claim create a new revision; old tests cannot silently validate new wording.
- Proposed merges preserve originals and provenance. Similar wording alone cannot automatically merge causes.
- Model suggestions stay labelled suggestions. Host submission is not human review. Another model's agreement is an assessment, not independent observation.
- Resolutions can reopen. “Action taken” and “cause established” are separate events.

### Status rules

Evidence status is `untested`, `open`, `contested`, or `refuted_in_scope`. Lifecycle states such as `withdrawn` and `superseded` are separate.

Model conflicts default to `contested`. Strict refutation requires all of:

1. A specific necessary prediction with scope and assumptions, recorded before the outcome or explicitly labelled retrospective.
2. An active observation of an incompatible outcome under applicable conditions.
3. Incompatibility checked by a typed deterministic rule with accepted premises, or explicitly reviewed by a person. Record which: human judgment remains fallible.
4. Every required dependency is active and applicable. Removing any premise invalidates that particular refutation.

An unfulfilled probabilistic prediction is a conflict, not logical refutation. Absence of evidence matters only with a specified detection opportunity. If every explanation is refuted, reopen the framing, measurements, assumptions, and search. Do not fabricate a winner.

Always display **“Could the observation be misleading?”** and **“What explanations have we missed?”** These are coverage checks, not mandatory rival slots. Add a concrete measurement-error explanation when justified. Add an incumbent only when one was actually proposed.

## 5. What the user sees

The ordinary view is a short inquiry brief:

- **Observed:** reports with source links and limitations.
- **Current interpretation:** possibilities, disagreements, and the assumptions doing the most work.
- **What changed:** which observation or correction changed which conclusion.
- **Next useful check:** procedure, distinguishing outcomes, effort, and why the answer matters.
- **Action now:** an option acceptable under stated uncertainties, or what prevents a responsible decision.
- **Revisit when:** a concrete result, deadline, or changed condition.

Expose the full board and history on request. No universal confidence meter. Live-rival count alone is not progress toward truth.

### Worked example: a process cannot see a credential

This is an **illustrative scenario, not a verified historical incident**.

E1: a tool reports `missing_key` from process P at time T. E2: someone reports exporting the credential in a shell configuration file. E2 does not establish P's environment.

Possibilities include P not inheriting the variable, code expecting a different name, or a stale process/configuration. Some can coexist. “The user believes it is configured” is a belief interpretation, not an independently established cause.

Check **presence and variable names only** in P's actual environment without printing the secret. Presence challenges the narrow claim “the variable is absent in P”; it does not establish credential validity or which name the code reads.

If the check later turns out to have inspected process Q, supersede the observation and invalidate dependent conclusions. The engine's proposed value is propagating this correction consistently across the inquiry.

## 6. Comparisons and next checks

### Board

Show assessments with provenance; missing cells are `unknown`. Prefer sparse, relevant assessments over a model call for every evidence–claim pair. Display coverage so an incomplete board cannot look fully checked.

Default ordering groups explanations by status and shows unresolved conflicts, untested predictions, and missing assessments. It does **not** treat conflict counts as likelihoods: specific explanations often expose more testable risks than vague ones. Label any host-supplied priority as that host's judgment. Ties and incomparability are legitimate.

Include sensitivity: which conclusions lose their stated support if one source group or assumption is removed? This is dependency analysis, not a probability update.

### Check selection

Apply declared hard constraints first, including harm, consent, privacy, permissions, and irreversibility where relevant. Compare eligible checks by decision relevance, reliability limitations, discrimination, cost, and time. Show trade-offs; abstain when essential inputs are missing. Do not hide arbitrary weights in a “wisdom score.”

For a deliberately declared set of mutually exclusive scenarios, an optional transparent heuristic is:

`separation coverage = pairs with known, disjoint predicted outcome sets / all scenario pairs`

Unknown predictions contribute no separating pairs; show prediction coverage alongside the score. Shared “inconclusive/error” outcomes prevent treating those scenarios as fully separated. With fewer than two scenarios the score is unavailable. This is **not** expected information gain or a probability. It depends on declared predictions and does not account for omitted scenarios.

For overlapping causes, use explicit joint scenarios when practical or a qualitative comparison. Never silently treat concurrent causes as mutually exclusive worlds. Avoid exponential automatic scenario expansion.

Introduce Bayesian information gain only when priors, likelihoods, dependence, and measurement error have defensible representations and calibration tests. [BED-LLM](https://arxiv.org/abs/2508.21184) motivates adaptive information gathering; its results do not validate our heuristic.

## 7. Acting responsibly under uncertainty

Action need not wait for a unique diagnosis. A reversible inspection can help across several explanations; deleting data might be unacceptable under even one plausible scenario.

Use Ty's ethical ordering: honor prohibitions on harm and other hard duties; consider wisdom, integrity, empathy, fairness, and beneficence; compare benefits and costs among admissible options. A favorable total cannot cancel a hard constraint. Unknown impacts remain unresolved, not “safe.” The system exposes consequences and conflicts; it cannot guarantee all unintended harms have been anticipated.

Record whose interests are affected and disagreements about acceptable outcomes. Include reversible steps, monitoring, and stop conditions where appropriate. Social dynamics can be causal mechanisms; do not automatically prefer physical explanations or dismiss a belief because of its origin.

Borrow the question “which actions withstand different plausible conditions?” from [Robust Decision Making](https://www.rand.org/pubs/tools/TL320/tool/robust-decision-making.html). A small scenario table is our proposed adaptation, not RAND's full method. Scenario counts are not outcome probabilities.

## 8. Implementation shape

Retain Python and `uv` for this existing Python project. Verify current releases/APIs before implementation, declare direct dependencies, and update the lockfile. No large package, model download, or sudo operation is needed for the core.

- **Domain layer:** validated records, references, scoped status rules, revision propagation, comparison functions.
- **SQLite:** append-only events plus transactional projections; schema migrations; event sequence numbers; idempotency keys; optimistic revision checks for concurrent clients. Export/import preserves provenance and history. Reject cross-case references and malformed batches atomically.
- **MCP adapter:** initial tools `open_case`, `record_observation`, `add_claim`, `record_assessment`, `revise_record`, `get_case`, `export_case`. Later tools `add_check`, `compare_checks`, `record_decision`, `resolve_case`, `import_case`. Version schemas, bound batches, and return structured errors.
- **Host guidance:** reusable prompt for alternative frames, assumptions, predictions, critiques, and structured submissions. The server never executes commands embedded in evidence or proposed checks.
- **Optional generator:** accepts a snapshot and proposes records; never changes evidence status directly. No mandatory judge or cross-project dependency.

Use `WISDOM_DATA_DIR` with a documented stable per-user default such as `~/.local/share/wisdom-engine`, expanded at runtime. Explicit paths support portable cases. Test launches from different working directories against the same configured store. Keep transport local by default and secrets out of records/logs. Normal history is append-only; explicit user-directed case deletion is a separate lifecycle operation.

Core calls should be short and bounded, with pagination and batch limits. Optional model operations need an overall deadline including queueing, probes, retries, validation, and cancellation. Per-request timeouts are insufficient. Concept listing, elaboration, and deduplication have sequential dependencies: expose resumable steps or test a single-call variant. Bound concurrency; local models may serialize requests. Target under 50 seconds for the relevant host, then measure actual stdio calls. [MCP Tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks) is optional and experimental in that specification.

## 9. Evaluation: three separate questions

Pre-register splits, prompts, models, budgets, metrics, review process, practical benefit thresholds, and stopping rules **before scored runs**. Nothing below claims measured performance.

### A. Does the record preserve reasoning correctly?

Deterministic tests cover corrections, independent supports, wrong scope/process/time, duplicate sources, changed wording, model-only conflicts, unobserved predictions, unknown relations, multiple causes, all/no candidates, reopening, cycles, invalid references, restart/replay, migration, retries, concurrent edits, cancellation, and atomic rollback. Test strict schemas, including string `"false"`, missing fields, non-object JSON, and unknown IDs. Failures must not become successful empty results.

Gate: all invariants pass, including **zero model-only hard refutations** and correct invalidation/recovery for every scripted revision. This proves bookkeeping, not wise reasoning.

### B. Does it help an agent investigate over time?

Compare the same host/model with the same cases, observations, tools, and total investigation budget:

| Arm | Purpose |
|---|---|
| P0: chat + structured inquiry prompt | Cheapest useful baseline |
| P1: same prompt + editable structured notes | Tests whether ordinary durable notes suffice |
| W1: same prompt + Wisdom Engine | Tests validation and dependency tracking's incremental value |

Replay evidence in time order. Include corrections, duplicated sources, incomplete explanations, multiple causes, and a missing true cause. Tool/simulator outcomes or documented observations supply evidence; evaluators cannot invent favorable results. All arms receive the same correction opportunities and budget.

Measure unsupported conclusions, missed revisions, traceability, false refutations, justified resolutions, useful checks, decisions against declared constraints, review burden, tokens/cost, and total elapsed time. Include appropriate abstention; never committing must not win solely through zero false refutations. Blind reviewers to arm where feasible.

Begin with labelled fixtures for harness development, then at least 20 held-out cases with independently authored cases and separate reporting for synthetic/public/private sources. Claude's anecdotal incident list remains **unverified candidate material** until its owner confirms causes and evidence chronology. Do not invent confirmations. Public postmortems can leak answers through training data; different authorship does not fix that. Use redacted initial packets, separate resolutions, and fresh controlled cases where possible.

Run multiple trials to reveal variability; calculate uncertainty by case, not as if repeated runs were independent cases. Report denominators, failures, missing costs, per-case outcomes, and uncertainty intervals. Twenty cases are a pilot, not a general efficacy claim. Pre-register a larger follow-up for promising but inconclusive results.

Gate: W1 must show a predeclared practically meaningful improvement over P1 on revision/justification or useful decisions, within agreed overhead, with no unresolved invariant failure. Otherwise simplify to notes plus a prompt, or retain only components with demonstrated benefit. Small ambiguous differences are not wins.

### C. Does specialized generation add value?

Evaluate independently after the core trial if still useful:

- B0: frozen current three-perspective generator; historical three-output baseline.
- B1: one prompt listing eight distinct causes.
- B2: one strong structured prompt with eight causes, assumptions, predictions, and checks.
- N1: concept-first generation with eight final slots and an explicit total budget.

Report recall at equal k where applicable, specificity, nonredundancy, discriminating predictions, false assertions, and complete cost/latency. B0's recall@3 is not recall@8. Include equal-output and budget-matched comparisons. Generic rivals cannot inflate counts or consume hidden extra slots. Equivalence labels need a rubric and blinded review; audit at least 25% plus disagreements and failures.

Keep N1 only if it improves on B2 at acceptable cost. Verbalized probabilities are optional experimental metadata, never default priors or confidence. N1's failure does not decide W1's usefulness.

## 10. Delivery sequence and exit gates

| Stage | Deliverable and demo | Gate / fallback |
|---|---|---|
| 0. Honest baseline | Freeze old behavior; inquiry prompt, evaluation protocol, labelled fixtures; mark unsupported README claims | Provenance and metric review; no fabricated real-case labels |
| 1. Revisable record | Models, SQLite, initial MCP tools; correction across a restart without an LLM | Invariants, schema contracts, actual stdio smoke test, export/replay parity |
| 2. Useful inquiry | Board, checks, sensitivity; P0/P1/W1 investigations | Benefit over notes; simplify if overhead outweighs value |
| 3. Decisions and breadth | Decision records and claim/belief/scientific examples | Evaluate these domains separately; debugging success does not validate them |
| 4. Optional generation | Concept-first adapter; B0/B1/B2/N1 comparison | Retain measured gains only |
| 5. Learning from outcomes | Reports of useful predictions/checks with selection-bias caveats | Retrieval/training needs its own held-out evaluation |

Every stage produces a runnable demo and appropriate tests. Run `uv run pytest` before any commit. Use type hints, docstrings, and comments explaining invariants. Check dependency documentation at implementation time.

Migration must be explicit. Keep `generate_hypotheses` only as a labelled experimental suggestion endpoint if useful. Do not silently replace `apply_via_negativa` with a board accepting different inputs: provide a versioned adapter or actionable deprecation error. Remove survival “confidence” and unqualified “actionable truth” from the new API. Compatibility must signal semantic changes, not invent substitute numbers. Old philosophical elimination tests belong to the frozen historical arm, not the new acceptance gate.

## 11. Current status

The v0.2 record and direct Jev evidence-assessment adapter are implemented. The old pipeline is retained as a historical fixture; its tool names now provide migration errors. The active server supports case records, revision propagation, evidence boards, declared check/decision/outcome records, and portable history. See [development results](docs/DEVELOPMENT_RESULTS.md) and [README](README.md) for runnable demos and current limits.

Following Ty's approval of direct Jev integration, a narrow assessor experiment was brought forward independently of specialized generation. The same-author synthetic pilot has 16 cases. Jev scored 16/16 once and 15/16 in a paired run; the generative baseline scored 15/16. This does not meet the independent multi-turn evaluation gates above. Board/check/decision functionality is implemented provisionally so those workflows can be tested; its existence is not a claim that Stages 2–3 passed their effectiveness gates.

A controlled four-case, two-turn notes/ledger/ledger-plus-Jev pilot is also recorded, including both protocol versions and validation failures. In version 2, all valid answers were correct, but corrupted output field names prevented four trajectories from completing. This is not a clean reasoning comparison or evidence that the effectiveness gates passed.

No improvement in real user outcomes is established. The next evaluation is the full notes-versus-record comparison, with and without Jev, using independently reviewed cases and realistic correction/decision sequences. Specialized generation, automatic merging, formal refutation adapters, and learning from outcomes remain deferred.
