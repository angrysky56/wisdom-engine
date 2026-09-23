# wisdom-engine: improvement plan

For: Astra (Codex). Written 2026-09-23 by Claude (Opus 5.5) in Cowork, with Ty.
Status: proposal. Nothing here is built yet.

## 1. Verdict

It isn't just a dream, but the useful version is smaller and more concrete than the current README suggests.

**What an LLM tool can do well here:**

- List many *different* candidate causes, not the same cause reworded.
- For each cause, say what else would have to be true if it were the real one.
- Keep a table of which observed facts fit which causes, across calls.
- Suggest the next check that best separates the remaining causes.

**What it can't do:** know which cause is true. Only observed evidence can eliminate a rival. Today the engine eliminates rivals using an LLM's opinion of them, not evidence. That is the main thing to fix.

**The honest bar:** Claude can already list rivals when asked directly. On one case it listed 5 by hand, and Jev rated 2 of them plausible rivals. How well other models do this is untested. wisdom-engine is worth keeping only if it beats a single plain prompt ("list 8 distinct possible causes") on real cases where the true cause is known. Phase 1 below tests exactly that. If it doesn't beat that prompt, stop, and keep the prompt instead of the server (see §7).

## 2. What happens today

All of this was observed in `src/wisdom_engine/engine.py` at commit `3cd42b9`, plus the uncommitted `llm.py` fix. Runs were live calls from Cowork on 2026-09-22/23.

**What works:**

- **It fails loudly.** When a check can't run, the engine raises an error instead of letting the hypothesis pass. Keep this.
- **The model backend chain works:** MCP sampling, then OpenRouter, then Ollama. Through OpenRouter (`deepseek/deepseek-v4.1-flash`), `generate_hypotheses` finished inside Cowork's 60 s tool limit in 2 of 2 calls.
- **The code is clean and small,** with 30 tests passing.

**What doesn't:**

| # | Problem | Where | Evidence |
|---|---|---|---|
| 1 | **The three perspectives converged.** Likely cause: each prompt independently asks for "the most likely" explanation. Rival explanation, not ruled out: this case has one dominant cause. Phase 0 will tell which. | `MECHANISM_PROMPT` / `NARRATIVE_PROMPT` / `CONSTRAINT_PROMPT` | 2 of 2 live runs on one case ("every Jev tool returned missing_key; the key is exported in ~/.bashrc"): all 3 hypotheses reused one cause, and only one extra rival (a mismatched key name) appeared at all. |
| 2 | **The narrative prompt answers a different question.** It asks why people *believe* something, not what else could *cause* the observation. That is a category error for debugging. | `NARRATIVE_PROMPT` | In the same runs, the narrative hypothesis was about the developer's mistaken belief, not a cause. |
| 3 | **`falsification_condition` is requested, then thrown away.** It is the most useful field and is never stored or returned. | `_build_hypothesis`; `Hypothesis` has no such field | Code reading. |
| 4 | **Invented evidence is mixed with observed facts.** The `evidence` field is written by the model: often predictions ("would show…"), sometimes invented facts ("likely does not…"). Nothing marks which facts were actually observed. | `evidence` | Live output contained "Inspecting … would show no TYPESAFE_API_KEY". |
| 5 | **The Stage B "Lakatosian cut" is a one-shot yes/no LLM call.** Lakatos judged research programmes by how they changed over time. A hypothesis generated a second ago has no history to judge. | `LAKATOS_PROMPT` | Code reading. |
| 6 | **Stage C "Bayesian collider" computes no probabilities.** `generate_hypotheses` output always contains exactly one mechanism, so on that input the "strongest mechanism" call chooses from a list of one. Only narratives can be eliminated, by design. | Stage C | Code reading. |
| 7 | **The confidence formula rewards learning nothing.** `confidence = survivors / total` rises as fewer rivals are eliminated, and reaches 1.0 when none are. | `synthesize_truth` | Code reading. |
| 8 | **No test checks output quality.** Every engine test uses a mocked LLM, so the tests prove the plumbing works, not that the hypotheses are any good. There is no evaluation set. | `tests/` | Code reading. |
| 9 | **`apply_via_negativa` timed out in Cowork.** It runs several LLM stages one after another. In 1 of 1 call it exceeded the 60 s tool limit. Likely every time, but untested. | `apply_via_negativa` | 1 of 1 call timed out. |
| 10 | **Nothing is saved between calls.** There are no cases, no evidence log, and no record of which cause turned out to be true, so it can't learn or be measured. | whole server | Code reading. |

Items 5–7 are the parts that make it feel fake: they use rigorous-sounding names for steps that don't do what the names say.

## 3. The ideal: a rival board

Think of a detective's board: candidate causes down the side, observed facts across the top, and marks where a fact rules a cause out. This is Heuer's Analysis of Competing Hypotheses (ACH), plus two things from recent research:

- **Concept-first generation for diversity.** Mixture of Concepts: first list K distinct concepts, then write one hypothesis per concept. On its inductive-reasoning benchmarks this cut redundant samples and reached baseline accuracy with half as many hypotheses.
- **Pick the next question by how much it would tell you.** BED-LLM, ICLR 2026: choose checks by expected information gain. We use a simple, code-computed version of that.

**Evidence caveat:** ACH's own track record is thin. Its value as a debiasing method "is widely believed … though there is a lack of strong empirical evidence" (Wikipedia summary of the literature). So we measure ours (§4, Phase 0) rather than assume it works.

### The loop

```
open_case(observation, context, facts[])        -> case_id                       [code]
propose_rivals(case_id, n=8)                     -> rivals with predictions       [LLM, parallel]
   host may add_rival(...) / merge_rivals(...)                                    [code]
add_evidence(case_id, text, source, observed)                                     [code]
score_matrix(case_id)                            -> fact × rival: fits / conflicts / neutral  [LLM, parallel, one call per cell]
board(case_id)                                   -> ranking, conflicts, what's unexplained  [code]
next_check(case_id)                              -> checks that best split live rivals  [code]
resolve_case(case_id, true_rival_id | "other: …")                                 [code]
```

**Design rules:**

1. **Only observed evidence eliminates.** A rival is marked `ruled_out` only when an *observed* fact conflicts with it, and the record names that fact. There is no elimination by "degenerating" or by explaining-away opinions.
2. **Every rival carries predictions:** 2–4 observable consequences that differ from the other rivals', plus the cheapest check for each. Store them. This replaces the lost `falsification_condition`.
3. **Two rivals are always present:**
   - the incumbent, meaning the claim as stated
   - "the observation itself is wrong", such as a stale log, the wrong machine, or a measurement artefact
4. **Generation is concept-first.** Step 1: one call lists 6–10 distinct *kinds* of cause (for software: config/env, code defect, data, dependency/version, resource/timeout, concurrency/state, human/process, measurement). Step 2: one hypothesis per kind, in parallel. Step 3: remove duplicates with a "same underlying cause?" check, and merge rather than delete.
5. **The model's likelihood guesses are labelled as guesses.** Verbalized sampling (asking for candidates *with* probabilities) improved diversity 1.6–2.1× on creative tasks in its paper. Use it only to widen the list, and store the numbers as `model_prior_guess`, never as confidence.
6. **Ranking and next-check are plain code.**
   - Rank by the number of observed conflicts (Heuer), then by how many observed facts the rival leaves unexplained.
   - `next_check` scores each candidate check by how evenly its predicted outcomes split the live rivals (the entropy of the partition). This is a crude but transparent stand-in for expected information gain.
7. **Remove the survival-rate confidence.** Report plain facts instead: how many rivals are live, how many are ruled out, and which observed facts no live rival explains. If a single number is wanted, use "live rivals left", which gets smaller as you learn.
8. **Every tool call must finish within 50 s over stdio.** Use parallel fan-out with a per-LLM-call timeout of 40 s. No tool chains LLM stages one after another, so the old pipeline becomes separate steps.
   - MCP Tasks (spec 2025-11-25) would allow long jobs, but it is marked *experimental* and needs client support. Treat it as optional.
9. **Save cases in SQLite** (`WISDOM_DATA_DIR`, default `./.wisdom/`). Cases, rivals, evidence, matrix cells and resolutions are append-only with timestamps.
10. **Self-contained.** No imports or paths into other projects. The output is plain JSON, so a host can pass rivals and facts to another judge if it wants to (for example Jev `evidence_stance`), but wisdom-engine does not depend on one.

### Two modes

The current "narrative" idea is real, but it belongs to a different job:

- **`mode: "cause"`** (default): what could produce this observation? This is the rival board above.
- **`mode: "belief"`**: why might people believe this claim whether or not it is true? It returns belief drivers (incentives, salience, a story that fits) as its own list. It never mixes them into causes, and never eliminates a cause.

### Old tools

- Keep `generate_hypotheses` for one release as a thin wrapper over `open_case` + `propose_rivals`, returning the old shape plus the new fields. Mark it deprecated in its description.
- Remove Stage B (Lakatos) and Stage C (collider) from `apply_via_negativa`. Replace it with `score_matrix` + `board`. If Ty wants the name kept, `apply_via_negativa` can become an alias of `board` that returns the conflicts, since elimination by observed evidence is the literal *via negativa*.
- `synthesize_truth`: rewrite it to summarise `board` output. It must not state a single "truth" while more than one rival is live. Its answer is "live rivals + next check".

## 4. Phases

Each phase ends with a demo Ty can run, and its tests passing. Don't start a phase until the previous one's gate is met.

### Phase 0: evaluation set and baseline (do this first)

1. **Create `evals/cases/*.json`.** Each file holds `{id, observation, context, facts_observed[], true_cause, equivalents[], source, author}`.
2. **Seed it with incidents from Ty's own stack where the cause is known.** Confirm each cause with Ty before using it.
   - GoT server crashed with `'NoneType' object has no attribute 'replace'`. Cause: the reasoning model spent its 1024-token output cap on thinking, so content came back empty.
   - GoT `generate_type: "list"` turned 6 rewrites into 10 fragments. Cause: the parser split on commas inside JSON strings.
   - GoT reported cost as always 0.0. Cause: `usage.cost` was not read.
   - wisdom-engine returned Ollama 404. Cause: `OLLAMA_MODEL=gemma4:12b` was not installed.
   - wisdom-engine got a ReadTimeout on `aura-ornith:35b`. Likely cause: 3 concurrent prompts were queued on one large local model past the 120 s HTTP timeout. **Ty to confirm.**
   - A Jev capability got `context` as a string, not an object. Cause: the Cowork device bridge serialises free-form JSON params.
   - `git` failed with an index.lock error. Cause: a stale `.git/index.lock` left by an interrupted `git status`.
   - Background jobs started from the device shell vanished. Cause: the shell's processes are killed when each tool call ends.
3. **Add at least 12 more cases not written by the prompt author** (Claude or Astra), so there are 20 or more in total. Sources:
   - Ty's own past bugs
   - [danluu/post-mortems](https://github.com/danluu/post-mortems), using a short observation-only summary written *before* reading the root cause
   - Warning: public postmortems may be in the model's training data. Tag them `public: true` and report results with and without them.
4. **Pre-register predictions** in `evals/PREDICTIONS.md` before the first scored run: expected recall for each arm, and what result would kill the project.
5. **Arms, all on the same model:**
   - **B0:** the current `generate_hypotheses`
   - **B1:** one plain prompt, "list 8 distinct possible causes, one line each"
   - **N1:** the new `propose_rivals`
6. **Metrics:**
   - **Recall@k:** is the true cause (or an equivalent) among the rivals? Labelled by a person, or by a blinded LLM judge with a person checking at least 25%.
   - **Distinct causes per case:** the count after merging duplicates, spot-checked by a person.
   - **Discriminating predictions:** the share of rivals whose predictions differ from every other rival's in at least one item.
   - **Time:** p95 seconds per tool call.
   - **Cost** per case.
7. **Script:** `uv run python -m evals.run --arm B0|B1|N1`, writing `evals/results/<date>-<arm>.json`.

### Phase 1: `propose_rivals` alone

- Build `open_case` and `propose_rivals` (concept-first, dedupe, the two fixed rivals, predictions and cheapest check stored), plus the SQLite store.
- **Gate:** N1 beats B1 on recall@8 *and* on distinct causes on the full case set, with the per-case results reported, not just averages. With about 20 cases a difference of 1–2 cases is noise, so say so. If N1 does not beat B1, go to §7.

### Phase 2: board, evidence, next check

- Build `add_rival`, `merge_rivals`, `add_evidence`, `score_matrix`, `board`, `next_check`, and `resolve_case`.
- `score_matrix` returns one cell per (fact, rival) pair: `fits | conflicts | neutral`, with a one-line reason.
- **Gate 1:** on the case set, replay the known observed facts one at a time in their original order. The true cause is never `ruled_out`: count false eliminations, and the target is 0.
- **Gate 2:** after all facts are in, the true cause is ranked 1st on at least 60% of cases where the facts are enough to decide. Mark the undecidable cases in advance.
- **Gate 3:** `next_check`'s top pick is a check a person judges useful on at least 70% of a 10-case sample.

### Phase 3: retire the fake parts

- Remove the Lakatos and collider stages and the survival-rate confidence.
- Add the deprecated wrappers and the `belief` mode.
- Update the README so every named method matches what the code actually does.

### Phase 4 (optional): learning from resolved cases

- Use resolved cases to report, per cause category, how often the true cause was proposed and at what rank.
- Only after 30 or more resolved real cases, consider feeding past resolutions back as examples.

## 5. Tests to add (beyond evaluation)

- **Unit, pure code:**
  - the ranking maths
  - the entropy calculation for `next_check`
  - dedupe merging keeps provenance
  - a rival can't be `ruled_out` by an unobserved (predicted) fact
  - the two fixed rivals are always present
- **Contract:** every tool's JSON output matches a schema, with a pydantic model for each.
- **Timeout:** with a mocked LLM that sleeps 45 s, each tool fails loudly within its time budget, never silently.
- **Keep all existing fail-loud tests.**

## 6. Constraints from Ty

- Python with `uv`. Run `uv run pytest` before every commit.
  - Pin dependencies after checking current versions. Don't assume them.
  - `pyproject.toml` currently has `mcp>=1.0.0`. The GoT server pins `mcp>=1.2,<2`. Check the current MCP Python SDK before choosing a pin.
- **Self-contained:** no code or paths from other repos.
- **Secrets:** never print or commit keys. `.env` stays git-ignored.
- **Honest reporting:** every result line gives n and conditions, and reports failures as plainly as successes.
- **Ask Ty before** installing anything large or needing sudo.

## 7. If Phase 1 fails

If concept-first `propose_rivals` doesn't beat the one-prompt baseline, the engine adds cost without adding rivals. The honest options:

1. Replace the server with a documented prompt (a skill) that does B1 plus the "predictions and cheapest check" fields, and archive the server.
2. Keep only the Phase 2 parts that don't depend on generation: the board, the evidence log, `next_check` and resolutions. A host (Claude) supplies the rivals, and the server keeps the record and does the arithmetic. My untested guess is that this part is useful whoever writes the rivals, because keeping many facts consistent against many rivals is harder for an LLM than listing them. Phase 2's gates would test it.

My guess, not tested: option 2 is the long-term shape either way.

## References

- Heuer, *Psychology of Intelligence Analysis*, ch. 8, ACH; summary and criticisms at https://en.wikipedia.org/wiki/Analysis_of_competing_hypotheses
- Mixture of Concepts: "Generating Diverse Hypotheses for Inductive Reasoning", arXiv 2412.13422 (IID sampling: 32 samples gave 7.89 unique programs on average)
- Verbalized Sampling: arXiv 2510.01171 (diversity 1.6–2.1× on creative writing)
- BED-LLM: arXiv 2508.21184, ICLR 2026 (choose questions by expected information gain)
- HypoBench: arXiv 2504.11524 (best methods recovered 38.8% of ground-truth hypotheses in its harder synthetic settings, so expect low recall and measure it)
- EvoDiverse: arXiv 2606.10587, ICML 2026 (diversity under a fixed verification budget; background only)
- MCP Tasks (experimental): https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks
