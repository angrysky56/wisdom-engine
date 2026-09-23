"""Deterministic views of an inquiry. No likelihoods inferred from vote counts."""
from itertools import combinations

from .contracts import Assessment, CaseSnapshot, Check, Claim, Decision, Observation, Prediction, Resolution
from .store import invalid_reasons


def board(snapshot: CaseSnapshot, omitted_source_group: str | None = None) -> dict:
    """Project current records; a counterfactual omission does not mutate history."""
    records = {r.id: r for r in snapshot.records}
    if omitted_source_group is not None:
        records = {key: r.model_copy(update={'lifecycle': 'withdrawn'})
                   if isinstance(r.payload, Observation) and r.payload.source.group == omitted_source_group else r
                   for key, r in records.items()}
    invalid = invalid_reasons(records)
    live = {key: r for key, r in records.items() if not invalid[key]}
    assessments = [r for r in live.values() if isinstance(r.payload, Assessment)]
    claims = []
    for record in records.values():
        if not isinstance(record.payload, Claim):
            continue
        relevant = [a for a in assessments if a.payload.claim == record.ref()]
        conflicts = [a for a in relevant if a.payload.relation == 'conflicts']
        refutations = [a for a in conflicts if a.payload.review is not None]
        status = 'refuted_in_scope' if refutations else 'contested' if conflicts else (
            'open' if any(a.payload.relation in ('supports', 'neutral') for a in relevant) else 'untested')
        if invalid[record.id]:
            status = 'inactive'
        claims.append({'id': record.id, 'revision': record.revision, 'text': record.payload.text,
                       'scope': record.payload.scope, 'status': status,
                       'assessment_ids': [a.id for a in relevant],
                       'refutation_ids': [a.id for a in refutations],
                       'invalidation_reasons': invalid[record.id]})
    observation_ids = [r.id for r in live.values() if isinstance(r.payload, Observation)]
    assessed = {(a.payload.claim.record_id, a.payload.observation.record_id) for a in assessments}
    active_claims = [c for c in claims if c['status'] != 'inactive']
    possible = len(active_claims) * len(observation_ids)
    resolutions = [r.model_dump() for r in live.values() if isinstance(r.payload, Resolution)]
    return {
        'schema_version': 1, 'case_id': snapshot.case_id, 'sequence': snapshot.sequence,
        'question': snapshot.case.question, 'claims': claims,
        'observations': [r.model_dump() for r in live.values() if isinstance(r.payload, Observation)],
        'assessments': [r.model_dump() for r in assessments],
        'predictions': [r.model_dump() for r in live.values() if isinstance(r.payload, Prediction)],
        'coverage': {'assessed_pairs': len(assessed), 'possible_pairs': possible,
                     'missing_pairs': possible - len(assessed)},
        'invalidated': [{'id': k, 'reasons': reasons} for k, reasons in invalid.items() if reasons],
        'decisions': [r.model_dump() for r in live.values() if isinstance(r.payload, Decision)],
        'resolutions': resolutions,
        'resolution_state': 'recorded_outcome' if resolutions else 'open',
        'coverage_questions': ['Could the observation be misleading?', 'What explanations have we missed?'],
        'reframe_needed': bool(active_claims) and all(c['status'] == 'refuted_in_scope' for c in active_claims),
        'omitted_source_group': omitted_source_group,
        'notice': 'Assessments are attributed judgments. No status or count is a probability of truth.',
    }


def compare_checks(snapshot: CaseSnapshot) -> dict:
    """Show tradeoffs; never infer eligibility or execute a suggested procedure."""
    invalid = invalid_reasons({r.id: r for r in snapshot.records})
    checks = []
    for record in snapshot.records:
        check = record.payload
        if not isinstance(check, Check) or invalid[record.id]:
            continue
        pairs = list(combinations([r.record_id for r in check.scenarios], 2))
        separating = sum(bool(check.predicted_outcomes.get(a)) and bool(check.predicted_outcomes.get(b))
                         and set(check.predicted_outcomes[a]).isdisjoint(check.predicted_outcomes[b])
                         for a, b in pairs)
        checks.append({'id': record.id, **check.model_dump(),
                       'separation_coverage': separating / len(pairs) if check.mutually_exclusive else None,
                       'prediction_coverage': sum(bool(check.predicted_outcomes.get(r.record_id)) for r in check.scenarios)
                                              / len(check.scenarios)})
    return {'case_id': snapshot.case_id, 'sequence': snapshot.sequence, 'checks': checks,
            'notice': 'Separation is a heuristic over declared exclusive scenarios, not information gain. '
                      'Only eligible checks are candidates for action; no automatic best check is asserted.'}
