"""Provider protocol validation and evidence-write atomicity, including cancellation."""
import asyncio
import json
import httpx
import pytest

from wisdom_engine.board import board
from wisdom_engine.jev import CRITERIA, JevClient, JevError, Pair, assess_evidence
from wisdom_engine.store import InquiryError


def reply(request, choice='conflicts'):
    questions = json.loads(request.content)['questions']
    return httpx.Response(200, json={'model': 'typesafe/fixture', 'answers': {
        key: {'type': 'choice', 'choice': choice, 'confidence': 0.99,
              'probabilities': {k: 1.0 if k == choice else 0.0 for k in CRITERIA}} for key in questions},
        'usage': {'cost': 0.001, 'input_tokens': 100}})


@pytest.mark.asyncio
async def test_confident_model_cannot_refute_and_retry_is_exact(inquiry, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-test-key')
    store, case, claim, obs = inquiry
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == '/api/alpha/decisions'
        assert 'synthetic-test-key' not in request.content.decode()
        return reply(request)
    client = JevClient(transport=httpx.MockTransport(handler))
    args = (store, client, case, [Pair(claim=claim.ref(), observation=obs.ref())], 2, 'judge')
    response = await assess_evidence(*args)
    assert response == await assess_evidence(*args)
    assert len(calls) == 1
    assert response['request_usage']['cost'] == 0.001
    assert board(store.snapshot(case))['claims'][0]['status'] == 'contested'
    assert 'synthetic-test-key' not in json.dumps(store.export_case(case))
    assert response['records'][0]['payload']['review'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [
    {}, {'answers': {}, 'model': 'test'},
    {'model': 'test', 'answers': {'pair_0': {'type': 'choice', 'choice': 'conflicts', 'confidence': '0.9', 'probabilities': {}}}},
    {'model': 'test', 'answers': {'pair_0': {'type': 'choice', 'choice': 'conflicts', 'confidence': 1.0, 'probabilities': {'conflicts': 1.0}}}},
])
async def test_invalid_response_never_writes(inquiry, monkeypatch, bad):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    store, case, claim, obs = inquiry
    client = JevClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=bad)))
    with pytest.raises(JevError, match='invalid typed'):
        await assess_evidence(store, client, case, [Pair(claim=claim.ref(), observation=obs.ref())], 2, 'bad')
    assert store.snapshot(case).sequence == 2


@pytest.mark.asyncio
async def test_stale_inflight_results_rejected(inquiry, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    store, case, claim, obs = inquiry
    def handler(request):
        store.revise(case, obs.id, 1, 2, 'change', 'Updated source', obs.payload)
        return reply(request)
    with pytest.raises(InquiryError, match='Stale case'):
        await assess_evidence(store, JevClient(transport=httpx.MockTransport(handler)), case,
                              [Pair(claim=claim.ref(), observation=obs.ref())], 2, 'judge')
    assert store.snapshot(case).sequence == 3
    assert board(store.snapshot(case))['assessments'] == []


@pytest.mark.asyncio
async def test_timeout_and_cancellation_leave_no_write(inquiry, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    store, case, claim, obs = inquiry
    entered = asyncio.Event()
    async def slow(request):
        entered.set()
        await asyncio.sleep(45)
        return reply(request)
    client = JevClient(timeout=0.02, transport=httpx.MockTransport(slow))
    args = (store, client, case, [Pair(claim=claim.ref(), observation=obs.ref())], 2, 'slow')
    with pytest.raises(JevError, match='deadline'):
        await assess_evidence(*args)
    client.timeout = 40
    entered.clear()
    task = asyncio.create_task(assess_evidence(*args))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.snapshot(case).sequence == 2


@pytest.mark.asyncio
async def test_missing_key_and_http_failure_redacted(inquiry, monkeypatch):
    store, case, claim, obs = inquiry
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    args = (store, JevClient(), case, [Pair(claim=claim.ref(), observation=obs.ref())], 2, 'missing')
    with pytest.raises(JevError, match='OPENROUTER_API_KEY is missing'):
        await assess_evidence(*args)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'secret-test')
    client = JevClient(transport=httpx.MockTransport(lambda _: httpx.Response(401, text='secret-test')))
    with pytest.raises(JevError) as error:
        await assess_evidence(store, client, case, args[3], 2, 'http')
    assert 'secret-test' not in str(error.value)
    assert store.snapshot(case).sequence == 2


@pytest.mark.asyncio
async def test_multiple_questions_are_one_request_and_typesafe_is_opt_in(inquiry, monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test')
    store, case, claim, obs = inquiry
    saved = store.append(case, [claim.payload.model_copy(update={'text': 'The variable name is different'})], 2, 'second')
    from wisdom_engine.contracts import Ref
    other = Ref(record_id=saved['records'][0]['id'], revision=1)
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host == 'api.typesafe.ai'
        assert request.url.path == '/v1/systemone'
        assert len(json.loads(request.content)['questions']) == 2
        return reply(request, 'unknown')
    client = JevClient(provider='typesafe', transport=httpx.MockTransport(handler))
    result = await assess_evidence(store, client, case,
        [Pair(claim=claim.ref(), observation=obs.ref()), Pair(claim=other, observation=obs.ref())], 3, 'batch')
    assert len(calls) == 1 and result['sequence'] == 5


@pytest.mark.asyncio
async def test_incomplete_batch_discards_valid_answers(inquiry, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    store, case, claim, obs = inquiry
    saved = store.append(case, [claim.payload], 2, 'second')
    from wisdom_engine.contracts import Ref
    other = Ref(record_id=saved['records'][0]['id'], revision=1)
    def handler(request):
        response = reply(request).json()
        del response['answers']['pair_1']
        return httpx.Response(200, json=response)
    with pytest.raises(JevError):
        await assess_evidence(store, JevClient(transport=httpx.MockTransport(handler)), case,
            [Pair(claim=claim.ref(), observation=obs.ref()), Pair(claim=other, observation=obs.ref())], 3, 'partial')
    assert store.snapshot(case).sequence == 3
