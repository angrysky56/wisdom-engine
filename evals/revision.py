"""Controlled two-turn revision comparison: notes, ledger, and ledger plus Jev."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Literal

import httpx
from pydantic import ValidationError

from wisdom_engine.board import board
from wisdom_engine.contracts import Assessment, CaseInput, Claim, Observation, Ref, Source, StrictModel, Text
from wisdom_engine.jev import JevClient, Pair, assess_evidence
from wisdom_engine.store import Store, canonical, fingerprint, invalid_reasons

ROOT = Path(__file__).parent
FINAL_LABELS = ['unknown', 'supported', 'unknown', 'contested']
SYSTEM = (
    'You maintain a short inquiry notebook across turns. Using only active applicable evidence, '
    'assess the CURRENT claim. A corrected record replaces its old revision; judgments depending '
    'on the old revision are stale. Independent unaffected evidence remains usable. A materially '
    'changed claim needs evidence for its new wording. Model assessments are fallible and do not '
    'override source scope or content. Return only JSON with conclusion, reason, notes. '
    'conclusion must be supported (applicable affirmative evidence with no active contrary evidence), '
    'contested (applicable evidence both for and against), or unknown (no sufficient applicable evidence). '
    'Do not infer credential validity from presence. Preserve source limitations and uncertainty.'
)


class Conclusion(StrictModel):
    conclusion: Literal['supported', 'contested', 'unknown']
    reason: Text
    notes: Text


SYSTEM += (' All three fields are required. reason and notes must each be a nonempty JSON string, '
           'not an array or object. No additional fields. Reply schema: '
           + canonical(Conclusion.model_json_schema()))


def parse_reply(data: dict, messages: list[dict], elapsed_ms: float) -> dict:
    """Keep synthetic reply and usage even when the strict answer contract fails."""
    usage = {k: v for k, v in data.get('usage', {}).items()
             if k in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cost') and type(v) in (int, float)}
    result = {'usage': usage, 'model': data.get('model'),
              'elapsed_ms_including_queue': elapsed_ms, 'input_sha256': fingerprint(messages)}
    try:
        choice = data['choices'][0]
        result['finish_reason'] = choice.get('finish_reason')
        result['raw_content'] = choice['message']['content']
        result['answer'] = Conclusion.model_validate_json(result['raw_content']).model_dump()
    except ValidationError as exc:
        result['error_type'] = type(exc).__name__
        result['validation_errors'] = exc.errors(include_url=False, include_input=False)
    except (KeyError, IndexError, TypeError) as exc:
        result['error_type'] = type(exc).__name__
    return result


def seed(store: Store, number: int) -> str:
    """Shared controlled initial records, identical before treatment in each arm."""
    case = store.open_case(CaseInput(question='Assess the current claim about P', scope='P at T', author='fixture'), 'open')['case_id']
    claim = Claim(author='fixture host', text='The key is present in process P at T', scope='P at T')
    obs = Observation(author='fixture', text='Key presence observed', scope='P at T', origin='dataset',
                      observed_at='2026-09-23T00:00:00+00:00', source=Source(locator='fixture://first',
                      excerpt='Direct presence inspection: process=P, time=T, key_present=true', method='Synthetic check', group='first'))
    records = [claim, obs]
    if number == 1:
        records.append(obs.model_copy(update={'source': Source(locator='fixture://independent',
            excerpt='Independent inspection: process=P, time=T, key_present=true', method='Independent synthetic check', group='second')}))
    store.append(case, records, 0, 'seed')
    snapshot = store.snapshot(case)
    c = snapshot.records[0]
    assessments = [Assessment(author='fixture host', claim=c.ref(), observation=o.ref(), relation='supports',
                              rationale='Initial fixture interpretation from direct same-scope evidence') for o in snapshot.records[1:]]
    store.append(case, assessments, snapshot.sequence, 'initial_assessments')
    return case


def change(store: Store, case: str, number: int) -> None:
    """Apply the predefined second-turn event; no dependence on model answers."""
    snapshot = store.snapshot(case)
    claim, observation = snapshot.records[:2]
    if number == 0:
        source = observation.payload.source.model_copy(update={'excerpt': 'Correction: the inspection was of process Q, not P. P was not inspected.'})
        corrected = observation.payload.model_copy(update={'scope': 'Q at T', 'text': 'Wrong process was inspected', 'source': source})
        store.revise(case, observation.id, 1, snapshot.sequence, 'correct', 'Inspection was of Q', corrected)
    elif number == 1:
        store.revise(case, observation.id, 1, snapshot.sequence, 'withdraw', 'First instrument was invalid; second independent check remains valid', withdraw=True)
    elif number == 2:
        revised = claim.payload.model_copy(update={'text': 'The credential in process P is valid and accepted by the service at T'})
        store.revise(case, claim.id, 1, snapshot.sequence, 'change_claim', 'Now asking validity, not presence', revised)
    else:
        new = observation.payload.model_copy(update={'text': 'Equally credible check found absence', 'source': Source(
            locator='fixture://contrary', excerpt='Equally credible independent inspection at exactly T: process=P, key_present=false. Neither instrument is known more reliable.',
            method='Synthetic simultaneous independent check', group='contrary')})
        saved = store.append(case, [new], snapshot.sequence, 'contrary')
        store.append(case, [Assessment(author='fixture host', claim=claim.ref(),
            observation=Ref(record_id=saved['records'][0]['id'], revision=1), relation='conflicts',
            rationale='Opposing same-time observation; neither source is more reliable')], saved['sequence'], 'conflict')


async def ask(model: str, messages: list[dict], semaphore: asyncio.Semaphore) -> dict:
    """One bounded host-model request; no silent repair/retry of failed output."""
    key = os.environ.get('OPENROUTER_API_KEY')
    if not key:
        raise ValueError('OPENROUTER_API_KEY is missing')
    start = time.monotonic()
    async with semaphore:
        async with asyncio.timeout(45):
            async with httpx.AsyncClient(timeout=40) as client:
                response = await client.post('https://openrouter.ai/api/v1/chat/completions',
                    headers={'Authorization': f'Bearer {key}'}, json={'model': model, 'messages': messages,
                    'max_tokens': 3000, 'temperature': 0, 'response_format': {'type': 'json_object'}})
                if response.status_code != 200:
                    raise ValueError(f'Host HTTP {response.status_code}')
                data = response.json()
    return parse_reply(data, messages, (time.monotonic() - start) * 1000)


async def trajectory(number: int, arm: str, model: str, semaphore: asyncio.Semaphore, jev: JevClient) -> dict:
    report = {'case': number + 1, 'arm': arm, 'turns': [], 'jev_runs': [], 'status': 'running'}
    with tempfile.TemporaryDirectory(prefix='wisdom-revision-') as directory:
        store = Store(Path(directory) / 'data.sqlite3')
        case = seed(store, number)
        messages = [{'role': 'system', 'content': SYSTEM}]
        last_sequence = 0
        for turn in range(2):
            try:
                if turn:
                    change(store, case, number)
                # Capture shared source events before the optional Jev intervention.
                events = [e for e in store.export_case(case)['events'] if e['sequence'] > last_sequence]
                if arm == 'ledger_jev':
                    snap = store.snapshot(case)
                    invalid = invalid_reasons({r.id: r for r in snap.records})
                    claim = snap.records[0]
                    observations = [r for r in snap.records if isinstance(r.payload, Observation) and not invalid[r.id]]
                    judged = await assess_evidence(store, jev, case,
                        [Pair(claim=claim.ref(), observation=o.ref()) for o in observations], snap.sequence, f'jev_{turn}')
                    report['jev_runs'].append({'usage': judged['request_usage'], 'latency_ms': judged['latency_ms'],
                                              'records': judged['records']})
                snap = store.snapshot(case)
                packet = {'case': snap.case.model_dump(), 'new_events': events,
                          'task': 'Update your notes and assess the current claim.'}
                if arm != 'notes':
                    packet['current_board'] = board(snap)
                messages.append({'role': 'user', 'content': canonical(packet)})
                reply = await ask(model, messages, semaphore)
                expected = 'supported' if turn == 0 else FINAL_LABELS[number]
                report['turns'].append({'turn': turn, 'expected': expected,
                                       'correct': reply.get('answer', {}).get('conclusion') == expected, **reply})
                if 'error_type' in reply:
                    report.update(status='failed', failure_turn=turn, error_type=reply['error_type'])
                    break
                messages.append({'role': 'assistant', 'content': canonical(reply['answer'])})
                last_sequence = snap.sequence
            except Exception as exc:
                report['status'] = 'failed'
                report['failure_turn'] = turn
                report['error_type'] = type(exc).__name__
                break
        else:
            report['status'] = 'completed'
        report['messages'] = messages  # Synthetic only; includes exact treatment packets.
    return report


async def run(model: str, live: bool) -> dict:
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'protocol': 'controlled-revision-v2',
              'model_requested': model, 'cases': 4, 'turns_per_case': 2, 'live': live,
              'conditions': 'Same-author synthetic controlled updating; not a full autonomous investigation',
              'source_sha256': fingerprint(Path(__file__).read_text()), 'system_sha256': fingerprint(SYSTEM)}
    if not live:
        return report
    semaphore = asyncio.Semaphore(2)
    jev = JevClient()
    # Independent trajectories run concurrently; turns within each remain sequential.
    results = await asyncio.gather(*(trajectory(i, arm, model, semaphore, jev)
                                    for i in range(4) for arm in ('notes', 'ledger', 'ledger_jev')))
    report['trajectories'] = results
    report['summary'] = {}
    for arm in ('notes', 'ledger', 'ledger_jev'):
        subset = [r for r in results if r['arm'] == arm]
        turns = [t for r in subset for t in r['turns']]
        report['summary'][arm] = {
            'completed': sum(r['status'] == 'completed' for r in subset), 'total_cases': 4,
            'initial_correct': sum(t['correct'] for t in turns if t['turn'] == 0),
            'final_correct': sum(t['correct'] for t in turns if t['turn'] == 1),
            'host_responses_captured': len(turns),
            'invalid_host_responses': sum('error_type' in t for t in turns),
            'host_reported_cost': sum(t['usage'].get('cost', 0) for t in turns),
            'host_missing_cost_count': sum('cost' not in t['usage'] for t in turns),
            'jev_reported_cost': sum(j['usage'].get('cost', 0) for r in subset for j in r['jev_runs']),
        }
    folder = ROOT / 'results'
    folder.mkdir(exist_ok=True)
    path = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-revision.json')
    path.write_text(json.dumps(report, indent=2) + '\n')
    return {**report, 'report_path': str(path)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', default='deepseek/deepseek-v4.1-flash')
    args = parser.parse_args()
    result = asyncio.run(run(args.model, args.live))
    print(json.dumps({k: v for k, v in result.items() if k != 'trajectories'}, indent=2))
    if any(r['status'] != 'completed' for r in result.get('trajectories', [])):
        raise SystemExit(1)
