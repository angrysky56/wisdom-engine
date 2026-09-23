"""Wisdom Engine MCP interface. Local records work without model credentials."""
from __future__ import annotations

from functools import lru_cache
import logging
import os
from typing import Annotated, Any

from dotenv import find_dotenv, load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .board import board, compare_checks as _compare_checks
from .contracts import (Assessment, CaseInput, Check, Claim, Decision, Identifier, Observation,
                        Prediction, RecordPayload, Resolution, Text)
from .jev import JevClient, Pair, assess_evidence as _assess_evidence
from .store import InquiryError, Store
from .transfer import Bundle

Sequence = Annotated[int, Field(strict=True, ge=0)]
Revision = Annotated[int, Field(strict=True, ge=1)]

mcp = FastMCP('wisdom-engine', log_level='WARNING', instructions=(
    'Keep generation and explanations in the host agent. Record actual observations with sources, '
    'then claims and predictions, then assessments. Use returned IDs and exact revisions. '
    'Every write needs a unique request_id and the last case sequence; repeat the same request_id '
    'only for an identical retry. Refresh after a stale-sequence error. '
    'Jev is optional: assess_evidence sends selected evidence to the configured provider. '
    'Jev judgments never hard-refute a claim. Human review fields are attributed reports, '
    'not authenticated identities; do not claim a human review that did not happen. '
    'Read wisdom://guide for the inquiry workflow.'
))


def store() -> Store:
    """Resolve storage at call time, avoiding cwd- or import-time database selection."""
    return Store()


@lru_cache(maxsize=4)
def jev_client(provider: str, model: str) -> JevClient:
    """Reuse the bounded provider client across calls without caching credentials."""
    return JevClient(provider=provider, model=model or None)


def _manual(payload: RecordPayload) -> None:
    if isinstance(payload, Assessment) and payload.origin == 'jev':
        raise InquiryError('Jev provenance is reserved for assess_evidence; submit host judgments with origin=host')


@mcp.tool()
def list_cases(offset: Annotated[int, Field(ge=0)] = 0,
               limit: Annotated[int, Field(ge=1, le=100)] = 50) -> dict[str, Any]:
    """Discover saved inquiries in stable creation order."""
    return store().list_cases(offset, limit)


@mcp.tool()
def open_case(case: CaseInput, request_id: Identifier) -> dict[str, Any]:
    """Open an inquiry. Scope names the subject, setting, and relevant time."""
    return store().open_case(case, request_id)


@mcp.tool()
def record_observation(case_id: Identifier, observation: Observation,
                       expected_sequence: Sequence, request_id: Identifier) -> dict[str, Any]:
    """Record a sourced report/result, never a model prediction or invented measurement."""
    return store().append(case_id, [observation], expected_sequence, request_id)


@mcp.tool()
def add_claim(case_id: Identifier, claim: Claim, expected_sequence: Sequence, request_id: Identifier) -> dict[str, Any]:
    """Add an explanation, assumption, interpretation, or belief driver. Multiple causes may coexist."""
    return store().append(case_id, [claim], expected_sequence, request_id)


@mcp.tool()
def add_prediction(case_id: Identifier, prediction: Prediction,
                   expected_sequence: Sequence, request_id: Identifier) -> dict[str, Any]:
    """Store a testable prediction and its exact claim revision before checking the outcome."""
    return store().append(case_id, [prediction], expected_sequence, request_id)


@mcp.tool()
def record_assessment(case_id: Identifier, assessment: Assessment,
                      expected_sequence: Sequence, request_id: Identifier) -> dict[str, Any]:
    """Attribute an evidence interpretation. Only explicit reported human review can refute in scope."""
    _manual(assessment)
    return store().append(case_id, [assessment], expected_sequence, request_id)


@mcp.tool()
def record_batch(case_id: Identifier, records: Annotated[list[RecordPayload], Field(min_length=1, max_length=20)],
                 expected_sequence: Sequence, request_id: Identifier) -> dict[str, Any]:
    """Atomically append independent records referring to already-existing revisions."""
    for record in records:
        _manual(record)
    return store().append(case_id, records, expected_sequence, request_id)


@mcp.tool()
def revise_record(case_id: Identifier, record_id: Identifier, expected_revision: Revision,
                  expected_sequence: Sequence, request_id: Identifier, reason: Text,
                  replacement: RecordPayload | None = None, withdraw: bool = False) -> dict[str, Any]:
    """Replace content or withdraw it. Dependent assessments become stale, never silently reused."""
    if replacement:
        _manual(replacement)
    return store().revise(case_id, record_id, expected_revision, expected_sequence, request_id,
                          reason, replacement, withdraw)


@mcp.tool()
def get_case(case_id: Identifier, offset: Annotated[int, Field(ge=0)] = 0,
             limit: Annotated[int, Field(ge=1, le=100)] = 50) -> dict[str, Any]:
    """Read current records with revision IDs. Paginated; a changing sequence means refresh the pages."""
    snapshot = store().snapshot(case_id)
    return {**snapshot.model_dump(exclude={'records'}),
            'records': [r.model_dump() for r in snapshot.records[offset:offset + limit]],
            'total_records': len(snapshot.records),
            'next_offset': offset + limit if offset + limit < len(snapshot.records) else None}


@mcp.tool()
def inquiry_board(case_id: Identifier, omitted_source_group: Text | None = None) -> dict[str, Any]:
    """Show evidence statuses, unknown coverage, and invalidations; optionally test source sensitivity."""
    return board(store().snapshot(case_id), omitted_source_group)


@mcp.tool()
def add_check(case_id: Identifier, check: Check, expected_sequence: Sequence, request_id: Identifier) -> dict[str, Any]:
    """Record a proposed procedure and scenario outcomes. This tool does not execute the check."""
    return store().append(case_id, [check], expected_sequence, request_id)


@mcp.tool()
def compare_checks(case_id: Identifier) -> dict[str, Any]:
    """Compare declared check tradeoffs; no probability or automatic execution is implied."""
    return _compare_checks(store().snapshot(case_id))


@mcp.tool()
def record_decision(case_id: Identifier, decision: Decision,
                    expected_sequence: Sequence, request_id: Identifier) -> dict[str, Any]:
    """Record affected people, constraints, a decision, and its revisit trigger. Executes nothing."""
    return store().append(case_id, [decision], expected_sequence, request_id)


@mcp.tool()
def resolve_case(case_id: Identifier, resolution: Resolution,
                 expected_sequence: Sequence, request_id: Identifier) -> dict[str, Any]:
    """Record an attributed outcome with evidence. Revising its dependencies reopens the inquiry."""
    return store().append(case_id, [resolution], expected_sequence, request_id)


@mcp.tool()
def export_case(case_id: Identifier) -> dict[str, Any]:
    """Export the complete revision history as portable JSON; no provider credentials are included."""
    return store().export_case(case_id)


@mcp.tool()
def import_case(bundle: Bundle, request_id: Identifier) -> dict[str, Any]:
    """Replay/validate an archive into an absent case ID. Attribution is preserved, not authenticated."""
    return store().import_case(bundle.model_dump(), request_id)


@mcp.tool()
async def assess_evidence(case_id: Identifier, pairs: Annotated[list[Pair], Field(min_length=1, max_length=16)],
                          expected_sequence: Sequence, request_id: Identifier) -> dict[str, Any]:
    """Send selected source/claim pairs to Jev and save revisable typed assessments atomically.

    Defaults to OpenRouter. No model judgment grants a hard refutation or human review.
    Service failure/cancellation writes nothing. Refresh if evidence changed during the call.
    """
    client = jev_client(os.environ.get('WISDOM_JEV_PROVIDER', 'openrouter'), os.environ.get('WISDOM_JEV_MODEL', ''))
    return await _assess_evidence(store(), client, case_id, pairs, expected_sequence, request_id)


@mcp.resource('wisdom://guide')
def inquiry_guide() -> str:
    """Host workflow usable without a second model."""
    return (
        'Frame the question and its scope. Separate collected observations from interpretations. '
        'Generate distinct explanations, including possible measurement errors when relevant. '
        'Do not assume causes are exclusive. For each claim, record assumptions and observable '
        'predictions with conditions. Attach source excerpts, timestamps, and source groups to observations. '
        'Assess only relevant pairs, with unknown for missing context. Use Jev optionally as another '
        'attributed assessor. Do not fabricate a rationale for Jev: it returns labels and probabilities. '
        'A conflict is not a refutation. Never claim human review without an actual review. '
        'On new evidence, revise records and examine invalidations on inquiry_board. '
        'Prioritize checks that could change the decision; record costs, constraints, and inconclusive outcomes. '
        'Record actions separately from established causes. Always state what remains unknown and when to revisit.'
    )


@mcp.tool()
def generate_hypotheses(surface_symptom: str, context: str = '') -> dict[str, Any]:
    """DEPRECATED in v0.2. Host generates claims; open_case and add_claim persist them."""
    raise InquiryError('generate_hypotheses retired: use host generation, open_case, and add_claim; read wisdom://guide')


@mcp.tool()
def apply_via_negativa(surface_symptom: str, hypotheses: list[dict], known_constraints: list[str] | None = None) -> dict[str, Any]:
    """DEPRECATED: model-only elimination removed. Use record_assessment and inquiry_board."""
    raise InquiryError('apply_via_negativa retired: record sourced observations and assessments, then inquiry_board')


@mcp.tool()
def synthesize_truth(filter_result: dict) -> dict[str, Any]:
    """DEPRECATED: unsupported survival confidence removed. Read inquiry_board and summarize in the host."""
    raise InquiryError('synthesize_truth retired: use inquiry_board; no survival-rate confidence is provided')


def main() -> None:
    """Launch local stdio or explicitly configured HTTP transport."""
    logging.basicConfig(level=logging.WARNING)
    load_dotenv(find_dotenv(usecwd=True), override=False)
    transport = os.environ.get('WISDOM_TRANSPORT', 'stdio').strip().lower()
    if transport not in ('stdio', 'streamable-http'):
        raise ValueError('WISDOM_TRANSPORT must be stdio or streamable-http')
    if transport == 'streamable-http':
        mcp.settings.host = os.environ.get('WISDOM_HTTP_HOST', '127.0.0.1')
        mcp.settings.port = int(os.environ.get('WISDOM_HTTP_PORT', '8765'))
    mcp.run(transport=transport)


if __name__ == '__main__':
    main()
