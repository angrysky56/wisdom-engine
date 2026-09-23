# Controlled multi-turn revision pilot

Preregistered 2026-09-23 before this pilot's first live run. Four same-author synthetic trajectories, two turns each, three arms using the same generative model:

- `notes`: raw event history plus the model's prior reply/notes.
- `ledger`: identical events/reply history plus a deterministic current inquiry board.
- `ledger_jev`: identical ledger workflow plus Jev's advisory relation assessments of current evidence.

Scenarios: (1) evidence corrected to another process; (2) one source withdrawn while independent support remains; (3) claim changes from key presence to validity; (4) an equally credible conflicting measurement arrives. The initial claim is supported in all four. Final reference labels are respectively `unknown`, `supported`, `unknown`, `contested`. Source/provenance and revisions are available to every arm; the board is the treatment. Fixture host assessments are provided to all arms rather than generated separately. Jev adds judgments, not observations. No reference label or scenario name is sent to either model.

Prediction: ledger arms should preserve the intended revision behavior in 4/4 final decisions. Notes may also succeed; a tie is not a demonstrated advantage. No prediction that adding Jev improves accuracy. All model assessments remain advisory. Do not change prompts, labels, or acceptance criteria after seeing the run.

Output contract: `conclusion` (`supported`, `contested`, `unknown`), `reason`, `notes`. No confidence threshold. Record every turn, input hash, full small synthetic messages, model ID, time, cost, and failures. Report initial and final accuracy separately and all denominators. Failure counts against completion; do not silently rerun failed trajectories. Results are developmental, not independently labelled, randomized, or powered. This is a controlled updating task, not a full autonomous investigation or human review-burden study.

Run with `uv run python -m evals.revision --live --model deepseek/deepseek-v4.1-flash`. This makes up to 24 chat requests and 8 Jev batches, bounded to two concurrent chat calls and per-request deadlines. All stores are temporary and all data synthetic. Without `--live`, no provider calls are made.

## Version 2 amendment, recorded before the repeat

Version 1 is retained at `results/20260923T182019550973Z-revision.json`. Four of twelve trajectories failed strict response validation, making that comparison inconclusive. Its harness did not retain the invalid replies or their usage, so the exact causes are unavailable and its reported costs are incomplete. Completed trajectories had correct initial and final labels.

Version 2 explicitly supplies the existing output JSON Schema and states that `reason` and `notes` must be nonempty strings. This clarifies the existing contract; it does not relax validation or reinterpret answers. The source cases, labels, semantic rubric, model, JSON-object response format, concurrency, and request budget stay the same. Invalid replies now retain raw synthetic content, finish reason, validation details, and provider usage before scoring. Failures remain failures; no repairs or automatic retries occur. Network/HTTP failures without a captured reply have unknown cost.

Run all twelve trajectories again and report this as a separate experiment, including the first run's failures. Do not pool the two versions into a single accuracy estimate. JSON Schema routing was considered using the [current OpenRouter documentation](https://openrouter.ai/docs/guides/features/structured-outputs), but the repeat keeps the same routing and adds the schema to the prompt, with local strict validation still authoritative.
