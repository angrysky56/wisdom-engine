"""MCP contract checks against the current server, independent of legacy fixtures."""
from datetime import timedelta
import copy
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from wisdom_engine.server import mcp


@pytest.mark.asyncio
async def test_tools_schema_guidance_and_deprecations(tmp_path, monkeypatch):
    monkeypatch.setenv('WISDOM_DATA_DIR', str(tmp_path))
    async with create_connected_server_and_client_session(server=mcp, read_timeout_seconds=timedelta(seconds=10)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert all(t.outputSchema is not None for t in tools.values())
        assert 'records' in tools['record_observation'].outputSchema['properties']
        assert 'claims' in tools['inquiry_board'].outputSchema['properties']
        assert tools['record_observation'].inputSchema['$defs']['Observation']['additionalProperties'] is False
        guide = await client.read_resource('wisdom://guide')
        assert 'Jev' in guide.contents[0].text
        opened = await client.call_tool('open_case', {'case': {'question': 'Q', 'scope': 'S', 'author': 'test'}, 'request_id': 'open'})
        assert not opened.isError
        cid = (opened.structuredContent or json.loads(opened.content[0].text))['case_id']
        bad = await client.call_tool('record_observation', {'case_id': cid, 'observation': {
            'text': 'Model invented a fact', 'origin': 'model'}, 'expected_sequence': 0, 'request_id': 'bad'})
        assert bad.isError
        current = await client.call_tool('get_case', {'case_id': cid})
        assert (current.structuredContent or json.loads(current.content[0].text))['sequence'] == 0
        for tool, args in [('generate_hypotheses', {'surface_symptom': 'x'}),
                           ('apply_via_negativa', {'surface_symptom': 'x', 'hypotheses': []}),
                           ('synthesize_truth', {'filter_result': {}})]:
            retired = await client.call_tool(tool, args)
            assert retired.isError and 'retired' in retired.content[0].text


@pytest.mark.asyncio
async def test_typed_end_to_end_inquiry_tools(tmp_path, monkeypatch):
    monkeypatch.setenv('WISDOM_DATA_DIR', str(tmp_path / 'first'))
    async with create_connected_server_and_client_session(server=mcp) as client:
        async def call(name, arguments):
            result = await client.call_tool(name, arguments)
            assert not result.isError, result.content
            assert result.structuredContent is not None
            return result.structuredContent

        opened = await call('open_case', {'case': {'question': 'Which explanation?', 'scope': 'S', 'author': 'test'}, 'request_id': 'open'})
        cid = opened['case_id']
        sequence = 0

        async def write(name, field, value):
            nonlocal sequence
            result = await call(name, {'case_id': cid, field: value, 'expected_sequence': sequence, 'request_id': f'write_{sequence}'})
            sequence = result['sequence']
            return {'record_id': result['records'][0]['id'], 'revision': 1}

        c1 = await write('add_claim', 'claim', {'text': 'A', 'scope': 'S', 'author': 'test'})
        c2 = await write('add_claim', 'claim', {'text': 'B', 'scope': 'S', 'author': 'test'})
        await write('add_prediction', 'prediction', {'claim': c1, 'scope': 'S', 'author': 'test',
            'outcome': 'x', 'conditions': 'Controlled conditions'})
        obs = await write('record_observation', 'observation', {'text': 'x was seen', 'scope': 'S',
            'author': 'test', 'origin': 'dataset', 'observed_at': '2000-01-01T00:00:00+00:00',
            'source': {'locator': 'fixture://test', 'excerpt': 'x', 'method': 'Synthetic', 'group': 'one'}})
        a = await write('record_assessment', 'assessment', {'claim': c1, 'observation': obs, 'relation': 'supports',
            'rationale': 'Fixture support', 'author': 'test'})
        await write('add_check', 'check', {'author': 'test', 'procedure': 'Inspect again',
            'decision_relevance': 'Choose next action', 'outcomes': ['x', 'y'], 'scenarios': [c1, c2],
            'predicted_outcomes': {c1['record_id']: ['x'], c2['record_id']: ['y']},
            'mutually_exclusive': True, 'constraint_status': 'eligible', 'constraint_reason': 'Synthetic read only',
            'cost': 'none', 'time': 'one minute'})
        checks = await call('compare_checks', {'case_id': cid})
        assert checks['checks'][0]['separation_coverage'] == 1.0
        await write('record_decision', 'decision', {'author': 'test', 'options': ['Inspect'], 'selected': 'Inspect',
            'affected_people': ['owner'], 'hard_constraints': ['Read only'], 'constraint_status': 'eligible',
            'rationale': 'Gather information', 'revisit_when': 'After inspection', 'requires': [a]})
        await write('resolve_case', 'resolution', {'author': 'test', 'outcome': 'action_taken',
            'summary': 'Inspection recorded', 'evidence': [obs], 'revisit_when': 'New evidence'})
        before = await call('inquiry_board', {'case_id': cid})
        assert len(before['decisions']) == 1
        saved = await call('export_case', {'case_id': cid})
        monkeypatch.setenv('WISDOM_DATA_DIR', str(tmp_path / 'second'))
        malformed = copy.deepcopy(saved)
        malformed['events'][0]['record']['created_at'] = 'invalid time'
        rejected = await client.call_tool('import_case', {'bundle': malformed, 'request_id': 'bad-import'})
        assert rejected.isError
        assert (await call('list_cases', {}))['cases'] == []
        await call('import_case', {'bundle': saved, 'request_id': 'import'})
        assert await call('export_case', {'case_id': cid}) == saved
        assert (await call('list_cases', {}))['cases'][0]['case_id'] == cid
        current = await call('get_case', {'case_id': cid, 'limit': 2})
        assert len(current['records']) == 2 and current['next_offset'] == 2
