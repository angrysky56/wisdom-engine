"""Revision semantics, atomic writes, independent support, and portable replay."""
from concurrent.futures import ThreadPoolExecutor
import copy
import sqlite3

import pytest
from pydantic import ValidationError

from wisdom_engine.board import board, compare_checks
from wisdom_engine.contracts import (Assessment, Check, Claim, Decision, Observation, PAYLOAD, Prediction,
                                    Ref, RefutationReview, Resolution)
from wisdom_engine.store import InquiryError, Store


def assess(claim, obs, **kwargs):
    return Assessment(author='tester', claim=claim.ref(), observation=obs.ref(),
                      relation='conflicts', rationale='Fixture interpretation', **kwargs)


def status(store, case):
    return board(store.snapshot(case))['claims'][0]['status']


def test_correction_invalidates_and_reopens_after_restart(inquiry):
    store, case, claim, obs = inquiry
    a = assess(claim, obs)
    saved = store.append(case, [a], 2, 'assessment')
    a_ref = Ref(record_id=saved['records'][0]['id'], revision=1)
    store.append(case, [Resolution(author='tester', outcome='supported', summary='Scoped conclusion',
                                   evidence=[a_ref], revisit_when='New evidence')], 3, 'resolve')
    assert status(store, case) == 'contested'
    corrected = obs.payload.model_copy(update={'scope': 'Q at T', 'text': 'Actually inspected Q'})
    store.revise(case, obs.id, 1, 4, 'correct', 'Wrong process', corrected)
    reopened = Store(store.path)
    view = board(reopened.snapshot(case))
    assert view['claims'][0]['status'] == 'untested'
    assert view['resolution_state'] == 'open'
    assert len(view['invalidated']) == 2
    assert len(reopened.export_case(case)['events']) == 5


def test_human_refutation_and_retraction(inquiry):
    store, case, claim, obs = inquiry
    pred = Prediction(author='tester', claim=claim.ref(), scope='P at T', necessary=True,
                      retrospective=True, conditions='Presence test within process P', outcome='key_present=false')
    saved = store.append(case, [pred], 2, 'predict')
    prediction = Ref(record_id=saved['records'][0]['id'], revision=1)
    review = RefutationReview(reviewer='fixture reviewer',
                             attestation='human_reviewed_necessary_prediction_and_applicable_conditions',
                             rationale='Fixture reports a reviewed incompatible outcome')
    store.append(case, [assess(claim, obs, origin='human', prediction=prediction, review=review)], 3, 'review')
    assert status(store, case) == 'refuted_in_scope'
    assert board(store.snapshot(case))['reframe_needed']
    store.revise(case, obs.id, 1, 4, 'withdraw', 'Invalid measurement', withdraw=True)
    assert status(store, case) == 'untested'


def test_independent_assessment_survives_retraction(inquiry):
    store, case, claim, obs = inquiry
    other = obs.payload.model_copy(update={'text': 'Independent check', 'source': obs.payload.source.model_copy(update={'group': 'independent'})})
    saved = store.append(case, [other], 2, 'other')
    other_ref = Ref(record_id=saved['records'][0]['id'], revision=1)
    store.append(case, [assess(claim, obs), Assessment(author='host', claim=claim.ref(), observation=other_ref,
                                                     relation='supports', rationale='Independent report')], 3, 'assess')
    store.revise(case, obs.id, 1, 5, 'withdraw', 'Bad first source', withdraw=True)
    assert status(store, case) == 'open'
    sensitivity = board(store.snapshot(case), 'independent')
    assert sensitivity['claims'][0]['status'] == 'untested'
    assert status(store, case) == 'open'  # Counterfactual does not mutate.


def test_atomic_batch_and_stale_ref_rejection(inquiry):
    store, case, claim, obs = inquiry
    missing = Assessment(author='host', claim=claim.ref(), observation=Ref(record_id='other_case', revision=1),
                         relation='supports', rationale='Missing reference')
    with pytest.raises(InquiryError, match='Dependency'):
        store.append(case, [assess(claim, obs), missing], 2, 'bad')
    assert store.snapshot(case).sequence == 2
    store.revise(case, obs.id, 1, 2, 'revise', 'Correction', obs.payload)
    with pytest.raises(InquiryError, match='Dependency'):
        store.append(case, [assess(claim, obs)], 3, 'stale')
    assert store.snapshot(case).sequence == 3


def test_idempotency_and_concurrent_writers(inquiry):
    store, case, claim, obs = inquiry
    def write(request):
        try:
            return store.append(case, [assess(claim, obs)], 2, request)
        except InquiryError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ['one', 'two']))
    assert sum(r is not None for r in results) == 1
    winner = 'one' if results[0] else 'two'
    assert store.append(case, [assess(claim, obs)], 2, winner) == next(r for r in results if r)
    with pytest.raises(InquiryError, match='Idempotency'):
        store.append(case, [claim.payload], 2, winner)


def test_export_import_parity_and_tampering(inquiry, tmp_path):
    store, case, claim, obs = inquiry
    store.append(case, [assess(claim, obs)], 2, 'assess')
    store.revise(case, obs.id, 1, 3, 'correct', 'Wrong process', obs.payload.model_copy(update={'scope': 'Q'}))
    bundle = store.export_case(case)
    second = Store(tmp_path / 'import.sqlite3')
    second.import_case(bundle, 'import')
    assert second.export_case(case) == bundle
    assert board(second.snapshot(case)) == board(store.snapshot(case))
    assert second.import_case(bundle, 'import')['sequence'] == 4
    with pytest.raises(InquiryError, match='already exists'):
        second.import_case(bundle, 'another')
    bad = copy.deepcopy(bundle)
    bad['events'][1]['sequence'] = 99
    third = Store(tmp_path / 'bad.sqlite3')
    with pytest.raises(InquiryError, match='sequence'):
        third.import_case(bad, 'bad')
    with pytest.raises(InquiryError, match='not found'):
        third.snapshot(case)


@pytest.mark.parametrize('timestamp', ['not a date', '2026-09-23', '2026-09-23T00:00:00'])
@pytest.mark.parametrize('target', ['case', 'record'])
def test_invalid_import_timestamp_rejected_atomically(inquiry, tmp_path, timestamp, target):
    store, case, _, _ = inquiry
    bundle = store.export_case(case)
    if target == 'case':
        bundle['created_at'] = timestamp
    else:
        bundle['events'][0]['record']['created_at'] = timestamp
    destination = Store(tmp_path / 'timestamps.sqlite3')
    with pytest.raises(ValidationError):
        destination.import_case(bundle, 'invalid-time')
    assert destination.list_cases()['cases'] == []


@pytest.mark.parametrize('payload', [
    {}, {'kind': 'observation', 'origin': 'model'}, {'kind': 'claim', 'text': ''},
    {'kind': 'prediction', 'necessary': 'false'}, ['not an object'],
])
def test_malformed_records_rejected(payload):
    with pytest.raises(ValidationError):
        PAYLOAD.validate_python(payload)


def test_no_false_human_review(inquiry):
    _, _, claim, obs = inquiry
    with pytest.raises(ValidationError, match='Refutation requires'):
        assess(claim, obs, origin='host', review=RefutationReview(reviewer='host',
            attestation='human_reviewed_necessary_prediction_and_applicable_conditions', rationale='No review'))
    with pytest.raises(ValidationError):
        Prediction(author='host', claim=claim.ref(), outcome='x', conditions='x', scope='x', necessary='false')


def test_scope_and_non_necessary_prediction_block_refutation(inquiry):
    store, case, claim, obs = inquiry
    with pytest.raises(InquiryError, match='scope'):
        store.append(case, [Prediction(author='host', claim=claim.ref(), scope='Q', outcome='absent', conditions='same')], 2, 'bad')
    predicted = Prediction(author='host', claim=claim.ref(), scope='P at T', outcome='absent', conditions='same')
    saved = store.append(case, [predicted], 2, 'pred')
    reviewed = assess(claim, obs, origin='human', prediction=Ref(record_id=saved['records'][0]['id'], revision=1),
                      review=RefutationReview(reviewer='tester', rationale='test',
                      attestation='human_reviewed_necessary_prediction_and_applicable_conditions'))
    with pytest.raises(InquiryError, match='necessary'):
        store.append(case, [reviewed], 3, 'refute')


def test_check_coverage_and_decision_constraint(inquiry):
    store, case, claim, obs = inquiry
    second = store.append(case, [Claim(author='host', text='Different cause', scope='P at T')], 2, 'second')
    other_ref = Ref(record_id=second['records'][0]['id'], revision=1)
    check = Check(author='host', procedure='Read presence only', decision_relevance='Select next diagnostic',
                  outcomes=['present', 'absent', 'error'], scenarios=[claim.ref(), other_ref],
                  predicted_outcomes={claim.id: ['absent'], other_ref.record_id: ['present']},
                  mutually_exclusive=True, constraint_status='eligible', constraint_reason='Read only; no secrets',
                  cost='none', time='one minute')
    store.append(case, [check], 3, 'check')
    assert compare_checks(store.snapshot(case))['checks'][0]['separation_coverage'] == 1
    mixed = check.model_copy(update={'mutually_exclusive': False})
    store.append(case, [mixed], 4, 'mixed')
    assert compare_checks(store.snapshot(case))['checks'][1]['separation_coverage'] is None
    unknown = check.model_copy(update={'predicted_outcomes': {}})
    store.append(case, [unknown], 5, 'unknown')
    assert compare_checks(store.snapshot(case))['checks'][2]['separation_coverage'] == 0
    with pytest.raises(ValidationError):
        Decision(author='host', options=['Delete'], selected='Delete', affected_people=['owner'],
                 hard_constraints=['Preserve data'], constraint_status='blocked', rationale='No', revisit_when='Never')


def test_unknown_schema_rejected(tmp_path):
    path = tmp_path / 'future.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(InquiryError, match='schema 99'):
        Store(path)


def test_default_directory_ignores_working_directory(tmp_path, monkeypatch):
    monkeypatch.setenv('WISDOM_DATA_DIR', str(tmp_path / 'data'))
    first = Store().path
    (tmp_path / 'other').mkdir()
    monkeypatch.chdir(tmp_path / 'other')
    assert Store().path == first


def test_cycle_and_changed_claim_wording(inquiry):
    store, case, claim, obs = inquiry
    saved = store.append(case, [assess(claim, obs)], 2, 'assess')
    a_ref = Ref(record_id=saved['records'][0]['id'], revision=1)
    with pytest.raises(InquiryError, match='cycle'):
        store.revise(case, claim.id, 1, 3, 'cycle', 'Circular support',
                     claim.payload.model_copy(update={'requires': [a_ref]}))
    store.revise(case, claim.id, 1, 3, 'wording', 'Material correction',
                 claim.payload.model_copy(update={'text': 'The key has the wrong name'}))
    assert status(store, case) == 'untested'
    assert len(board(store.snapshot(case))['invalidated']) == 1


def test_duplicate_sources_not_counted_as_confidence(inquiry):
    store, case, claim, obs = inquiry
    store.append(case, [assess(claim, obs), assess(claim, obs)], 2, 'duplicates')
    view = board(store.snapshot(case))
    assert view['coverage']['assessed_pairs'] == 1
    assert 'confidence' not in view
    assert status(store, case) == 'contested'


def test_source_kind_and_retrospective_requirement(inquiry):
    store, case, claim, obs = inquiry
    wrong_source = Assessment(author='host', claim=claim.ref(), observation=claim.ref(),
                              relation='conflicts', rationale='Not an observation')
    with pytest.raises(InquiryError, match='observation must'):
        store.append(case, [wrong_source], 2, 'wrong')
    pred = Prediction(author='host', claim=claim.ref(), scope=claim.payload.scope, necessary=True,
                      conditions='Presence check', outcome='Absent')
    saved = store.append(case, [pred], 2, 'pred')
    reviewed = assess(claim, obs, origin='human', prediction=Ref(record_id=saved['records'][0]['id'], revision=1),
                      review=RefutationReview(reviewer='tester', rationale='Reviewed',
                      attestation='human_reviewed_necessary_prediction_and_applicable_conditions'))
    with pytest.raises(InquiryError, match='retrospective'):
        store.append(case, [reviewed], 3, 'review')


def test_listing_and_empty_case(inquiry):
    store, case, _, _ = inquiry
    assert store.list_cases()['cases'][0]['case_id'] == case
    assert store.list_cases(100)['cases'] == []
