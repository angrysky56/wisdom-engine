"""Small independent fixtures for current inquiry behavior."""
import pytest
from wisdom_engine.contracts import CaseInput, Claim, Observation, Source
from wisdom_engine.store import Store


@pytest.fixture
def inquiry(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    case_id = store.open_case(CaseInput(question='Does P receive the key?', scope='P at T', author='test'), 'open')['case_id']
    claim = Claim(author='host', text='The key is absent in P at T', scope='P at T')
    obs = Observation(author='test', text='Presence check in P found the key', scope='P at T',
                      observed_at='2026-09-23T12:00:00+00:00', origin='tool_result',
                      source=Source(locator='fixture://presence', excerpt='process=P; key_present=true',
                                    method='presence-only check', group='presence'))
    store.append(case_id, [claim, obs], 0, 'seed')
    snap = store.snapshot(case_id)
    return store, case_id, snap.records[0], snap.records[1]
