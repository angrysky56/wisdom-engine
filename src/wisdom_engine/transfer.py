"""Strict portable event archive, independent of local database paths."""
from typing import Literal
from pydantic import Field
from .contracts import CaseInput, Identifier, Record, StrictModel, Text


class Event(StrictModel):
    sequence: int = Field(ge=1)
    record: Record


class Bundle(StrictModel):
    schema_version: Literal[1]
    case_id: Identifier
    case: CaseInput
    created_at: Text
    events: list[Event] = Field(max_length=5000)
