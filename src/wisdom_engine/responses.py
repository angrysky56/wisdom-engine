"""Explicit MCP output contracts, validated by FastMCP before returning results."""
from typing import Literal
from pydantic import Field

from .contracts import (CaseInput, Check, Identifier, Probability, Record, StrictModel, Text, Timestamp)


class CaseResult(StrictModel):
    schema_version: Literal[1] = 1
    case_id: Identifier
    sequence: int = Field(ge=0)


class MutationResult(CaseResult):
    records: list[Record]
    request_usage: dict[str, float | int] | None = None
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class CasePage(CaseResult):
    case: CaseInput
    records: list[Record]
    total_records: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)


class CaseHeader(StrictModel):
    case_id: Identifier
    question: Text
    created_at: Timestamp


class CaseList(StrictModel):
    schema_version: Literal[1] = 1
    cases: list[CaseHeader]
    next_offset: int | None = None


class ClaimView(StrictModel):
    id: Identifier
    revision: int = Field(ge=1)
    text: Text
    scope: Text
    status: Literal['untested', 'open', 'contested', 'refuted_in_scope', 'inactive']
    assessment_ids: list[Identifier]
    refutation_ids: list[Identifier]
    invalidation_reasons: list[Text]


class Coverage(StrictModel):
    assessed_pairs: int = Field(ge=0)
    possible_pairs: int = Field(ge=0)
    missing_pairs: int = Field(ge=0)


class Invalidated(StrictModel):
    id: Identifier
    reasons: list[Text]


class BoardResult(CaseResult):
    question: Text
    claims: list[ClaimView]
    observations: list[Record]
    assessments: list[Record]
    predictions: list[Record]
    coverage: Coverage
    invalidated: list[Invalidated]
    decisions: list[Record]
    resolutions: list[Record]
    resolution_state: Literal['recorded_outcome', 'open']
    coverage_questions: list[Text]
    reframe_needed: bool
    omitted_source_group: Text | None
    notice: Text


class CheckView(Check):
    id: Identifier
    separation_coverage: Probability | None
    prediction_coverage: Probability


class CheckComparison(CaseResult):
    checks: list[CheckView]
    notice: Text
