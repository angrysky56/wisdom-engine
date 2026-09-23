# Wisdom Engine

A local MCP server for inquiries that can be corrected: sourced observations, claims, predictions, assessments, decisions, and their revision history. An optional direct Jev integration assesses evidence without turning model opinions into observed facts.

**Version 0.2 is a working development release.** Its record-keeping and protocol are tested. Whether it improves real investigations over a good prompt and editable notes remains an evaluation question. See [the plan](PLAN.md), [design review](docs/DESIGN_REVIEW.md), and [evaluation protocol](evals/PROTOCOL.md).

## How it works

The connected agent generates explanations and proposes checks. Wisdom Engine stores exact dependencies between revisions. If an observation is corrected or withdrawn, assessments and resolutions depending on that version become inactive. Independent grounds remain available.

Jev can label selected evidence–claim pairs `supports`, `conflicts`, `neutral`, or `unknown`. Results include the actual model version, rubric, probabilities, timing, and request fingerprint. **A Jev conflict makes a claim contested, never refuted.** Its confidence describes a model answer, not the probability an explanation is true. Jev provides no written reasoning; the system does not fabricate one.

Strict refutation is available only as an attributed report of human review of a necessary prediction, applicable conditions, and incompatible evidence. The caller must explicitly attest that review happened. This local tool does not authenticate human identity or independently verify an external source.

The board reports uncertainty and missing coverage without a global confidence score. Explanations may overlap. Proposed checks display tradeoffs; only explicitly exclusive scenarios receive a separation heuristic. Decisions record constraints and review triggers. No tool executes proposed checks or actions.

## Run

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
uv run wisdom-engine
```

Stdio is the default. Connect an MCP client using:

```json
{
  "mcpServers": {
    "wisdom-engine": {
      "command": "uv",
      "args": ["--directory", "/path/to/wisdom-engine", "run", "wisdom-engine"]
    }
  }
}
```

Replace `/path/to/wisdom-engine` with this checkout. Restart the client's MCP connection after upgrading from 0.1. No model key is needed for the record tools.

## Jev setup

The default route is **OpenRouter**, model `~typesafe/jev-latest`, using the Decisions API. Make `OPENROUTER_API_KEY` available to the server process. This is a hosted model call; selected excerpts and case context are sent to the configured provider. Do not include credentials or private material you do not want sent.

For native TypeSafe access, set `WISDOM_JEV_PROVIDER=typesafe` and supply `TYPESAFE_API_KEY`. The native default is `jev-latest`. There is no automatic provider fallback. Use a provider-supported fixed model ID with `WISDOM_JEV_MODEL` when comparing repeatable evaluations. Returned model IDs are always recorded.

Environment variables take precedence over `.env`. Copy `.env.example` if useful. GUI clients may not inherit shell variables: configure the launching environment or use the ignored `.env` file. Never put secret values in committed MCP configuration.

| Setting | Default / purpose |
|---|---|
| `WISDOM_DATA_DIR` | `~/.local/share/wisdom-engine`; contains `inquiry.sqlite3` |
| `WISDOM_JEV_PROVIDER` | `openrouter` or explicit `typesafe` |
| `WISDOM_JEV_MODEL` | Provider's Jev latest alias; independent of old `OPENROUTER_MODEL` |
| `OPENROUTER_API_KEY` | Credential for the default Jev route |
| `TYPESAFE_API_KEY` | Credential for the optional native route |
| `WISDOM_TRANSPORT` | `stdio`; optional `streamable-http` |
| `WISDOM_HTTP_HOST` / `WISDOM_HTTP_PORT` | `127.0.0.1` / `8765` |

The default store is stable across working directories. Use an **absolute** `WISDOM_DATA_DIR` for client-specific stores. SQLite transactions, request IDs, and sequence checks protect concurrent clients. Keep HTTP local; this release has no remote authentication layer.

## Inquiry tools

| Task | Tools |
|---|---|
| Start or resume | `open_case`, `list_cases`, `get_case` |
| Record inquiry material | `record_observation`, `add_claim`, `add_prediction`, `record_assessment`, `record_batch` |
| Ask Jev | `assess_evidence` (1–16 independent pairs per call) |
| Correct and inspect | `revise_record`, `inquiry_board` (optional source-group sensitivity) |
| Compare proposed checks | `add_check`, `compare_checks` |
| Record actions/outcomes | `record_decision`, `resolve_case` |
| Preserve or transfer | `export_case`, `import_case` |

Every write needs a unique `request_id`. After a successful write, use its returned `sequence` for the next write. An identical retry with the same request ID returns the original result; reuse with different inputs is an error. After a stale-sequence error, refresh and reconsider the change before submitting a new request ID.

Dependencies use `{ "record_id": "…", "revision": 1 }`. Batch records may refer to existing records, not to IDs that have yet to be allocated. Corrected claims and evidence require fresh assessments. Supplying a model-generated string as an observation's origin is rejected. Source fields are attributed reports, not proof of authenticity.

`get_case` and `list_cases` are paginated. Cases are bounded to 500 records and 5,000 events. Export includes the full event history and validates on import; existing cases are never overwritten. Treat imported human/provider attribution as the archive author's assertion. Import does not verify digital signatures. Failed provider calls, malformed answers, cancellations before commit, and results from changed case snapshots leave the record unchanged.

For the host's reasoning instructions, read MCP resource `wisdom://guide` or [the standalone inquiry prompt](docs/INQUIRY_PROMPT.md).

## Demonstrate and verify

These demos use synthetic data in a temporary store and do not change your saved inquiries:

```bash
uv run pytest
uv run python scripts/stdio_demo.py
uv run python scripts/stdio_demo.py --live
```

The first demo exercises an actual stdio subprocess, evidence correction, and restart parity. `--live` adds one paid Jev call using synthetic source text. Ordinary tests use controlled responses and never call a live model.

The opt-in evaluation commands and limitations are in [evals/PROTOCOL.md](evals/PROTOCOL.md) and the [controlled revision protocol](evals/REVISION_PROTOCOL.md). Results are saved with input hashes, per-case labels, actual model IDs, timing, and known costs. The [development report](docs/DEVELOPMENT_RESULTS.md) retains both successes and output-validation failures. These small same-author synthetic pilots are not substitutes for independently reviewed real cases.

## Migration from 0.1

`generate_hypotheses`, `apply_via_negativa`, and `synthesize_truth` now return actionable deprecation errors. They do not silently reinterpret the old inputs. The host supplies claims; the new board summarizes evidence. Unsupported Lakatos/collider eliminations and survival-rate confidence are absent from the active server.

The original implementation and its 30 regression tests are preserved in `src/wisdom_engine/legacy/` and `tests/legacy/` solely as a historical baseline. They are not the active server or evidence of the new system's reasoning quality. Old Python imports from `wisdom_engine.engine`, `.models`, or `.llm` must be migrated.

Still experimental/deferred: automatic claim merging, specialized generation, formal deterministic refutation adapters, calibrated action thresholds, and learning from resolved cases. The agent remains responsible for generating alternatives, gathering observations, explaining assessments, and respecting declared constraints.
