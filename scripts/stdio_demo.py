"""Exercise the installed MCP server through a real stdio subprocess.

Run: uv run python scripts/stdio_demo.py [--live]
All case data is synthetic and stored in an automatically cleaned temporary directory.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def run(live: bool = False) -> dict:
    """Create, assess, correct, restart, and replay the case across the protocol."""
    with tempfile.TemporaryDirectory(prefix='wisdom-demo-') as data_dir:
        params = StdioServerParameters(command=sys.executable, args=['-m', 'wisdom_engine.server'],
                                       cwd=str(ROOT), env={**os.environ, 'WISDOM_DATA_DIR': data_dir})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(name: str, args: dict) -> dict:
                    result = await session.call_tool(name, args)
                    if result.isError:
                        raise RuntimeError(f'{name} failed: {result.content}')
                    return result.structuredContent or json.loads(result.content[0].text)

                names = {t.name for t in (await session.list_tools()).tools}
                assert {'open_case', 'assess_evidence', 'revise_record', 'inquiry_board'} <= names
                case = await call('open_case', {'case': {'question': 'Is the key absent in process P?',
                                                       'scope': 'P at T', 'author': 'synthetic demo'}, 'request_id': 'open'})
                cid = case['case_id']
                claim = {'kind': 'claim', 'text': 'The key is absent in process P at T',
                         'scope': 'P at T', 'author': 'demo host'}
                observed = {'kind': 'observation', 'text': 'Presence test in P found the key',
                            'scope': 'P at T', 'author': 'demo tool', 'origin': 'tool_result',
                            'observed_at': '2026-09-23T12:00:00+00:00',
                            'source': {'locator': 'fixture://presence', 'excerpt': 'Process P at T: key_present=true',
                                       'method': 'Synthetic presence-only result', 'group': 'presence'}}
                seeded = await call('record_batch', {'case_id': cid, 'records': [claim, observed],
                                                    'expected_sequence': 0, 'request_id': 'seed'})
                c, o = seeded['records']
                cref, oref = ({'record_id': r['id'], 'revision': 1} for r in (c, o))
                if live:
                    judged = await call('assess_evidence', {'case_id': cid, 'pairs': [{'claim': cref, 'observation': oref}],
                                                          'expected_sequence': 2, 'request_id': 'judge'})
                    payload = judged['records'][0]['payload']
                    model = payload['jev']['model_returned']
                    relation = payload['relation']
                    usage = judged.get('request_usage', {})
                else:
                    await call('record_assessment', {'case_id': cid, 'assessment': {
                        'claim': cref, 'observation': oref, 'relation': 'conflicts', 'rationale': 'Synthetic example',
                        'origin': 'host', 'author': 'demo host'}, 'expected_sequence': 2, 'request_id': 'judge'})
                    model, relation, usage = None, 'conflicts', {}
                before = await call('inquiry_board', {'case_id': cid})
                assert before['claims'][0]['status'] != 'refuted_in_scope'
                await call('revise_record', {'case_id': cid, 'record_id': o['id'], 'expected_revision': 1,
                                             'expected_sequence': 3, 'request_id': 'correct', 'reason': 'Wrong process',
                                             'replacement': {**observed, 'scope': 'Q at T', 'text': 'The result was from Q'}})
                after = await call('inquiry_board', {'case_id': cid})
                assert after['claims'][0]['status'] == 'untested'
                assert len(after['invalidated']) == 1
                bundle = await call('export_case', {'case_id': cid})
                old = await session.call_tool('synthesize_truth', {'filter_result': {}})
                assert old.isError
        # The server is genuinely restarted against the same store.
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool('export_case', {'case_id': cid})
                restored = response.structuredContent or json.loads(response.content[0].text)
                assert not response.isError and restored == bundle
        return {'transport': 'stdio', 'restart_parity': True, 'stale_assessments': 1,
                'model': model, 'relation': relation, 'request_usage': usage,
                'final_status': 'untested', 'live': live}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Call Jev once with synthetic data; uses provider credentials')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.live)), indent=2))
