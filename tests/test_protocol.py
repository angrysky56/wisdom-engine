"""MCP contract checks against the current server, independent of legacy fixtures."""
from datetime import timedelta
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
