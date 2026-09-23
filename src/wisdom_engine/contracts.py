"""Strict, versioned inquiry contracts. Model assessments never become observations."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16000)]
Identifier = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,80}$')]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Relation = Literal['supports', 'conflicts', 'neutral', 'unknown']


def timestamp_with_timezone(value: str) -> str:
    """Preserve the supplied ISO timestamp while rejecting ambiguous or invalid times."""
    if datetime.fromisoformat(value).tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return value


Timestamp = Annotated[Text, AfterValidator(timestamp_with_timezone)]


class StrictModel(BaseModel):
    """Reject extra keys and coercion, including string booleans and numeric IDs."""
    model_config = ConfigDict(extra='forbid', strict=True, validate_default=True)


class Ref(StrictModel):
    record_id: Identifier
    revision: Annotated[int, Field(ge=1)]


class CaseInput(StrictModel):
    question: Text
    scope: Text
    kind: Literal['cause', 'claim', 'belief', 'decision'] = 'cause'
    context: str = Field(default='', max_length=16000)
    author: Text
    decision_to_inform: str = Field(default='', max_length=4000)


class Payload(StrictModel):
    author: Text
    requires: list[Ref] = Field(default_factory=list, max_length=50)


class Source(StrictModel):
    locator: Text
    excerpt: Text
    method: Text
    # Unknown independence stays explicit instead of treating every link as a vote.
    group: Text = 'unknown'


class Observation(Payload):
    kind: Literal['observation'] = 'observation'
    text: Text
    scope: Text
    observed_at: Timestamp
    origin: Literal['human_report', 'tool_result', 'dataset']
    source: Source
    limitations: list[Text] = Field(default_factory=list, max_length=20)

class Claim(Payload):
    kind: Literal['claim'] = 'claim'
    text: Text
    scope: Text
    category: Literal['explanation', 'assumption', 'interpretation', 'belief_driver'] = 'explanation'
    origin: Literal['human', 'host', 'model'] = 'host'


class Prediction(Payload):
    kind: Literal['prediction'] = 'prediction'
    claim: Ref
    outcome: Text
    conditions: Text
    scope: Text
    necessary: bool = False
    retrospective: bool = False


class JevTrace(StrictModel):
    provider: Literal['openrouter', 'typesafe']
    model_requested: Text
    model_returned: Text
    rubric: Text
    request_sha256: Text
    probabilities: dict[Relation, Probability]
    confidence: Probability
    latency_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)]

    @model_validator(mode='after')
    def distribution(self) -> JevTrace:
        if set(self.probabilities) != {'supports', 'conflicts', 'neutral', 'unknown'}:
            raise ValueError('Jev trace must retain every relation probability')
        if abs(sum(self.probabilities.values()) - 1) > 0.001:
            raise ValueError('Invalid Jev trace probability distribution')
        return self


class RefutationReview(StrictModel):
    """A caller's attributed human review, never authenticated by model confidence."""
    reviewer: Text
    attestation: Literal['human_reviewed_necessary_prediction_and_applicable_conditions']
    rationale: Text


class Assessment(Payload):
    kind: Literal['assessment'] = 'assessment'
    claim: Ref
    observation: Ref
    relation: Relation
    rationale: Text
    origin: Literal['human', 'host', 'jev'] = 'host'
    prediction: Ref | None = None
    review: RefutationReview | None = None
    jev: JevTrace | None = None

    @model_validator(mode='after')
    def authority(self) -> Assessment:
        if (self.origin == 'jev') != (self.jev is not None):
            raise ValueError('Jev assessments require a trace; other origins cannot attach one')
        if self.review and (self.origin != 'human' or not self.prediction or self.relation != 'conflicts'):
            raise ValueError('Refutation requires human origin, prediction, and conflict')
        return self


class Check(Payload):
    kind: Literal['check'] = 'check'
    procedure: Text
    decision_relevance: Text
    outcomes: list[Text] = Field(min_length=2, max_length=20)
    # Keys are claim IDs; dependencies below capture their exact revisions.
    scenarios: list[Ref] = Field(min_length=2, max_length=20)
    predicted_outcomes: dict[str, list[Text]]
    mutually_exclusive: bool = False
    constraint_status: Literal['eligible', 'blocked', 'unknown'] = 'unknown'
    constraint_reason: Text
    cost: Text
    time: Text
    limitations: list[Text] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def candidates(self) -> Check:
        ids = [r.record_id for r in self.scenarios]
        if len(set(ids)) != len(ids) or len(set(self.outcomes)) != len(self.outcomes):
            raise ValueError('Duplicate scenario or outcome')
        if not set(self.predicted_outcomes) <= set(ids):
            raise ValueError('Unknown scenario')
        if any(not set(values) <= set(self.outcomes) for values in self.predicted_outcomes.values()):
            raise ValueError('Unknown predicted outcome')
        return self


class Decision(Payload):
    kind: Literal['decision'] = 'decision'
    options: list[Text] = Field(min_length=1, max_length=20)
    selected: Text | None = None
    affected_people: list[Text] = Field(min_length=1, max_length=20)
    hard_constraints: list[Text] = Field(min_length=1, max_length=20)
    constraint_status: Literal['eligible', 'blocked', 'unknown'] = 'unknown'
    rationale: Text
    revisit_when: Text

    @model_validator(mode='after')
    def selected_option(self) -> Decision:
        if self.selected is not None and (self.selected not in self.options or self.constraint_status != 'eligible'):
            raise ValueError('A selected option must be listed and declared eligible')
        return self


class Resolution(Payload):
    kind: Literal['resolution'] = 'resolution'
    outcome: Literal['supported', 'multiple_causes', 'unresolved', 'action_taken']
    summary: Text
    evidence: list[Ref] = Field(min_length=1, max_length=50)
    revisit_when: Text


RecordPayload = Annotated[Observation | Claim | Prediction | Assessment | Check | Decision | Resolution,
                          Field(discriminator='kind')]
PAYLOAD = TypeAdapter(RecordPayload)


class Record(StrictModel):
    id: Identifier
    revision: Annotated[int, Field(ge=1)]
    created_at: Timestamp
    lifecycle: Literal['active', 'withdrawn'] = 'active'
    change_reason: Text
    payload: RecordPayload

    def ref(self) -> Ref:
        """Return an immutable dependency reference."""
        return Ref(record_id=self.id, revision=self.revision)


class CaseSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    case_id: Identifier
    case: CaseInput
    sequence: int
    records: list[Record]


def dependencies(payload: RecordPayload) -> list[Ref]:
    """Collect semantic and explicit dependencies; never infer links from prose."""
    refs = list(payload.requires)
    if isinstance(payload, Prediction):
        refs.append(payload.claim)
    if isinstance(payload, Assessment):
        refs.extend([payload.claim, payload.observation])
        if payload.prediction:
            refs.append(payload.prediction)
    if isinstance(payload, Check):
        refs.extend(payload.scenarios)
    if isinstance(payload, Resolution):
        refs.extend(payload.evidence)
    return list({(r.record_id, r.revision): r for r in refs}.values())
