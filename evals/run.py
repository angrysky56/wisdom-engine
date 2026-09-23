"""Run a reproducible, bounded evidence-relation pilot on public synthetic fixtures."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import httpx

from wisdom_engine.jev import CRITERIA, INSTRUCTIONS, JevClient, RUBRIC_VERSION
from wisdom_engine.store import canonical, fingerprint

ROOT = Path(__file__).parent


def prepare(cases: list[dict]) -> tuple[dict, dict]:
    """Construct state without expected labels or judge-visible outcome hints."""
    pairs = [{'claim': {'text': c['claim'], 'scope': c['scope']},
              'observation': {'text': c['text'], 'scope': c['observation_scope'],
                              'source': {'excerpt': c['excerpt']}}} for c in cases]
    questions = {f'pair_{i}': {'type': 'choice', 'instructions': f'For `pairs[{i}]`: {INSTRUCTIONS}',
                              'criteria': CRITERIA} for i in range(len(pairs))}
    return {'pairs': pairs}, questions


def summarize(cases: list[dict], gold: dict, answers: dict) -> dict:
    rows = []
    for i, case in enumerate(cases):
        answer = answers[f'pair_{i}']
        expected = gold[case['id']]
        probabilities = answer.get('probabilities')
        brier = sum((probabilities[k] - (1 if k == expected else 0)) ** 2 for k in CRITERIA) if probabilities else None
        rows.append({'id': case['id'], 'expected': expected, **answer,
                     'correct': answer['choice'] == expected, 'brier': brier})
    confusion = {expected: {chosen: 0 for chosen in CRITERIA} for expected in CRITERIA}
    for row in rows:
        confusion[row['expected']][row['choice']] += 1
    recall = {label: counts[label] / sum(counts.values()) if sum(counts.values()) else None
              for label, counts in confusion.items()}
    represented = [value for value in recall.values() if value is not None]
    return {'n': len(rows), 'correct': sum(r['correct'] for r in rows),
            'accuracy': sum(r['correct'] for r in rows) / len(rows),
            'confusion_expected_by_predicted': confusion,
            'per_class_recall': recall,
            'macro_accuracy': sum(represented) / len(represented),
            'mean_brier': sum(r['brier'] for r in rows) / len(rows) if all(r['brier'] is not None for r in rows) else None,
            'per_case': rows}


async def baseline(model: str, state: dict, questions: dict) -> dict:
    """Optional single chat prompt with the same state/rubric and exact output labels."""
    key = os.environ.get('OPENROUTER_API_KEY')
    if not key:
        raise ValueError('OPENROUTER_API_KEY missing for baseline')
    start = time.monotonic()
    prompt = ('Evaluate each supplied question against the supplied state. Return only JSON mapping every question '
              'ID to {"choice": LABEL}, where LABEL is one of supports, conflicts, neutral, unknown. '
              'Do not generate explanations.\n' + canonical({'state': state, 'questions': questions}))
    async with asyncio.timeout(45):
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post('https://openrouter.ai/api/v1/chat/completions',
                headers={'Authorization': f'Bearer {key}'},
                json={'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                      'max_tokens': 3000, 'response_format': {'type': 'json_object'}})
            if response.status_code != 200:
                raise ValueError(f'Baseline HTTP {response.status_code}')
            data = response.json()
    answers = json.loads(data['choices'][0]['message']['content'])
    if set(answers) != set(questions) or any(a.get('choice') not in CRITERIA for a in answers.values()):
        raise ValueError('Baseline output violates answer contract')
    usage = {k: v for k, v in data.get('usage', {}).items()
             if k in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cost') and type(v) in (int, float)}
    return {'answers': answers, 'model': data['model'], 'usage': usage, 'latency_ms': (time.monotonic() - start) * 1000}


async def run(args: argparse.Namespace) -> dict:
    cases = json.loads((ROOT / 'cases.json').read_text())
    gold = json.loads((ROOT / 'gold.json').read_text())
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'n': len(cases),
              'dataset_sha256': fingerprint(cases), 'gold_sha256': fingerprint(gold),
              'rubric': RUBRIC_VERSION, 'conditions': 'synthetic same-author development pilot; one batch per arm',
              'live': args.live, 'arms': {}}
    if not args.live:
        return report
    state, questions = prepare(cases)
    client = JevClient()
    report['jev_requested'] = {'provider': client.provider, 'model': client.model}
    start = time.monotonic()
    try:
        result = await client.evaluate(state, questions)
        answers = {k: v.model_dump() for k, v in result.pop('answers').items()}
        report['arms']['jev'] = {'status': 'completed', **result, **summarize(cases, gold, answers)}
    except Exception as exc:
        report['arms']['jev'] = {'status': 'failed', 'error_type': type(exc).__name__,
                                 'elapsed_ms': (time.monotonic() - start) * 1000}
    if args.baseline_model:
        start = time.monotonic()
        try:
            result = await baseline(args.baseline_model, state, questions)
            report['arms']['host_baseline'] = {'status': 'completed', 'model_requested': args.baseline_model,
                                              **summarize(cases, gold, result.pop('answers')), **result}
        except Exception as exc:
            report['arms']['host_baseline'] = {'status': 'failed', 'model_requested': args.baseline_model,
                                              'error_type': type(exc).__name__, 'elapsed_ms': (time.monotonic() - start) * 1000}
    for arm in report['arms'].values():
        arm['missing_cost'] = 'cost' not in arm.get('usage', {})
    folder = ROOT / 'results'
    folder.mkdir(exist_ok=True)
    destination = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    destination.write_text(json.dumps(report, indent=2) + '\n')
    report['report_path'] = str(destination)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--baseline-model')
    result = asyncio.run(run(parser.parse_args()))
    print(json.dumps({**result, 'arms': {k: {a: b for a, b in v.items() if a != 'per_case'}
                                      for k, v in result['arms'].items()}}, indent=2))
    if any(a['status'] == 'failed' for a in result['arms'].values()):
        raise SystemExit(1)
