---
name: wisdom-eval-failures
description: Diagnose Wisdom Engine live evaluation output failures and prepare reproducible, separately versioned repeats without changing reference labels or hiding failed runs.
---

Read the relevant protocol under `evals/` and the failed result before changing the harness. In the controlled revision pilot, valid JSON sometimes contained a corrupted `conclusion` key even after the prompt included its schema. JSON-object mode alone did not enforce the output contract.

Capture the raw synthetic reply, finish reason, actual model, input hash, and reported usage before Pydantic validation. Preserve validation errors. Do not salvage a scored label from the explanation, rename unexpected keys, silently retry, or discard failed turns. Count invalid output as failed completion and include its known cost. Calls with no usage have unknown cost, not zero cost.

Before changing provider output controls, check current endpoint support in the official OpenRouter structured-output documentation: https://openrouter.ai/docs/guides/features/structured-outputs . Schema enforcement and supported parameters vary by endpoint. Continue local strict validation even when native schema output is available.

A revised prompt or request configuration is a new experimental version. Record the amendment before running, keep reference labels and fixtures frozen, retain earlier artifacts, and compare all arms with the same new configuration. Do not pool different protocol versions or infer a reasoning advantage from unequal formatting failures. Stop the comparison as inconclusive if failures still obstruct it; a fresh full run requires a concrete new diagnostic hypothesis and the applicable cost authorization.

For private-data evaluations, replace raw-content logging with an explicitly approved local retention/redaction policy. The repository's existing fixtures and committed reports are synthetic.
