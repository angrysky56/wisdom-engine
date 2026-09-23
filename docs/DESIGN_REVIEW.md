# Review of Claude's Wisdom Engine proposal

Reviewed 2026-09-23 against current commit `2d27092`, all source modules, the test suite, and the primary sources below. This is a design review. No new runtime or model-quality evaluation was implemented. The original proposal is [preserved here](PLAN.claude-2026-09-23.md); the [revised plan](../PLAN.md) contains the recommendation.

## Findings from current code

| Finding | Evidence | Implication |
|---|---|---|
| Requested falsification conditions are lost | `engine.py`, `_build_hypothesis` and `unroll_depths`; `models.py`, `Hypothesis` | Keep predictions as durable first-class records |
| Generated evidence has no observational provenance | Prompt `evidence` arrays flow into `Hypothesis.evidence` | A model prediction can look like collected evidence |
| Model judgments alone eliminate hypotheses | `apply_via_negativa`, stages A–C | Failures in interpretation can become confident exclusions |
| “Confidence” is surviving/total | `synthesize_truth`, lines 548–550 and 595 | Neither probability of truth nor calibration |
| Returned “strongest” is first surviving mechanism | `engine.py`, lines 507–510 | With multiple mechanisms, it need not match the model-selected mechanism |
| No persistent case or revision model | `models.py` and `server.py` | No reliable way to propagate corrections across calls |
| Tool budget is not an end-to-end deadline | `llm.py` has 120-second HTTP timeouts; engine chains stages | The proposed 50-second contract requires a redesign and actual host testing |
| Failure handling is narrower than the README claims | JSON parsing is followed by permissive `.get` defaults and truthiness checks | Valid JSON can still silently produce invalid reasoning records |

Current baseline: **30/30 tests passed**, `uv run pytest`, Python 3.13.2, on this checkout. These are software tests with mocked model calls; they do not establish factual accuracy, diversity, calibrated confidence, or actual client latency. Claude's earlier live calls and incident diagnoses were not rerun or independently confirmed in this review.

Additional offline probes called existing engine functions with deliberately malformed model outputs, without credentials or network calls:

| Probe | Observed result |
|---|---|
| All generation calls return `{}` | Three hypotheses returned, all with empty text |
| A judgment returns `{}` | Candidate survives despite no explicit valid judgment |
| Judgment returns `{"degenerating": "false"}` | Candidate is eliminated because a nonempty string is truthy |

These are current defects, not hypothetical risks. Strict response schemas must precede state changes in the new design. Existing transport-failure tests are worth retaining; tests expecting philosophical model eliminations should not dictate the new semantics.

## Where Claude's plan improves the project

Keep its insistence on observed evidence, durable predictions, empirical comparison with a cheap prompt, honest failure reporting, source independence from other repositories, and abandonment of unsupported philosophical labels. The distinction between explaining a phenomenon and explaining belief in it is useful, while social processes can also genuinely cause phenomena.

## Where the proposal needs correction

1. **An observed fact is not a verified contradiction.** The proposed LLM matrix still lets model interpretation control elimination. Require scoped necessary predictions, applicable premises, and a checkable or reviewed incompatibility. Otherwise show a conflict and uncertainty.
2. **A flat rival contest can misrepresent reality.** Causes can cooperate. An “incumbent” need not exist. Observation errors can coexist with real failures. Keep coverage prompts for measurement error and missing causes instead of two mandatory pseudo-hypotheses.
3. **Counts can reward vagueness.** A broad hypothesis predicts little and attracts few conflicts. Duplicated evidence can overwhelm a count-based ordering. Show specificity, assessment coverage, source dependence, and conflicts without calling them likelihoods.
4. **Partition entropy has demanding assumptions.** It resembles information gain only under assumptions about exclusivity, prior weights, and reliable outcome predictions. Equal partitions are not necessarily useful checks. Costs, inconclusive outcomes, missing predictions, and action relevance matter.
5. **The latency requirements contradict the proposed pipeline.** Concept generation must finish before per-concept elaboration, which must finish before deduplication. Per-cell scoring also scales with evidence × rivals. Parallelism cannot remove dependencies or a local model's queue.
6. **Generation quality is the wrong gate for the whole product.** A record can help even if the host already generates good alternatives. Compare persistent records with editable notes, then evaluate specialized generation separately.
7. **The proposed evaluation misses key distinctions.** Three outputs versus eight is not equal-k recall. A one-line prompt is weaker than a prompt producing the same structured predictions. A different author does not prevent public-data contamination. Time, failed requests, retries, and all generation stages count toward budget. Twenty cases cannot justify broad claims from small differences.
8. **Append-only storage is incomplete without revision rules.** Changes must invalidate stale assessments and propagate through dependency chains. Resolution should allow multiple causes, insufficient evidence, and later reopening.
9. **Wisdom includes action and values.** An investigation can leave the cause unsettled while supporting a reversible action. Ethical constraints and affected parties must be explicit; utility arithmetic cannot define moral acceptability.

## Research checked and how far it supports the design

These sources motivate experiments and reusable patterns. None validates the proposed Wisdom Engine as a whole. Abstract-level numerical findings are reported as the authors' results; they were not independently reproduced here.

| Source | What it supports | Limit on transfer |
|---|---|---|
| [Heuer, Psychology of Intelligence Analysis, ch. 8](https://www.cia.gov/resources/csi/static/Pyschology-of-Intelligence-Analysis.pdf) | Alternative hypotheses, diagnostic evidence, sensitivity to misleading evidence, and revisiting conclusions | A matrix does not establish objective weights or validate LLM cell judgments |
| [Dhami, Belton & Mandel, 2019](https://pureportal.strath.ac.uk/en/publications/the-analysis-of-competing-hypotheses-in-intelligence-analysis/) | In a study of 50 intelligence analysts, ACH showed mixed effects on confirmation bias and possible increased inconsistency/error | More specific evidence than a generic claim that ACH lacks validation; not proof every structured board is harmful |
| [Dhami et al., 2024](https://strathprints.strath.ac.uk/89640/) | Task presentation affected bias in a study with 161 participants; the conventional ACH orientation did not show the benefits of the alternative orientation | Interface matters; this does not establish effects on LLM agents or our proposed UI |
| [de Kleer, An assumption-based TMS, 1986](https://www.sciencedirect.com/science/article/pii/0004370286900809) | Established machinery for recording assumptions behind conclusions | Borrow dependency tracking; do not claim natural-language assessments gain formal validity |
| [RAND, Robust Decision Making](https://www.rand.org/pubs/tools/TL320/tool/robust-decision-making.html) | Examine actions across plausible conditions and identify failure conditions; scenario counts generally should not be interpreted as probabilities | A small qualitative table is an adaptation, not full RDM; ethical admissibility remains an explicit user constraint |
| [Mixture of Concepts, arXiv:2412.13422](https://arxiv.org/abs/2412.13422) | Concept-guided generation improved diversity/performance on inductive-reasoning benchmarks; NAACL 2025 | Does not prove better real-incident diagnosis; retain as an optional experimental arm |
| [BED-LLM, arXiv:2508.21184](https://arxiv.org/abs/2508.21184) | Uses a probabilistic model for expected information gain; reports tests on 20 Questions and preference inference; ICLR 2026 | Our simple separation heuristic is not this probabilistic method |
| [HypoBench, arXiv:2504.11524](https://arxiv.org/abs/2504.11524) | Evaluates hypothesis quality along multiple dimensions; reports 38.8% recovery in harder synthetic settings | That percentage is not an expected recall target for debugging or this project |
| [Verbalized Sampling, arXiv:2510.01171](https://arxiv.org/abs/2510.01171) | Authors report 1.6–2.1× creative-writing diversity; abstract also discusses other tasks | Verbalized response probabilities are not established causal priors; don't confuse diversity with truth |
| [Towards Diverse Scientific Hypothesis Search, arXiv:2606.10587](https://arxiv.org/abs/2606.10587) | Studies diversity under fixed validation budgets in molecular, equation, and algorithm discovery; ICML 2026 | Useful budget principle, not evidence that evolutionary search belongs in this small server |
| [MCP Tasks, specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks) | Defines negotiated support for durable task execution and result retrieval; explicitly experimental | Client support must be verified; not a universal solution to a host's tool timeout |

## Why the revised recommendation fits

The proposed record makes claims easier to inspect and correct without restricting inquiry to a fixed set of physical mechanisms. It preserves the project's ambition while giving its software a concrete job: prevent lost provenance, stale conclusions, and hidden assumptions from becoming authoritative summaries.

The strongest competing explanation for its usefulness is that a good prompt and ordinary notes already suffice. The revised evaluation tests exactly that. If the software adds bureaucracy without measurable benefit, simplify it.

## Completion of this review

- Inspected the original proposal, current source, configuration, and tests.
- Verified baseline tests and three schema-handling defects with offline probes.
- Checked the cited research against primary publications/documentation and added relevant prior work.
- Compared three directions and recommended one with explicit limits.
- Wrote an actionable revised plan, worked example, migration approach, and separate tests for bookkeeping, inquiry usefulness, and generation.
- Preserved Claude's original document. Runtime behavior is unchanged; implementation and effectiveness remain future work.
