"""The live experiment's fixtures must obey the same revision rules as the product."""
import pytest
from evals.revision import change, parse_reply, seed
from wisdom_engine.board import board
from wisdom_engine.store import Store


@pytest.mark.parametrize('number,expected', [(0, 'untested'), (1, 'open'), (2, 'untested'), (3, 'contested')])
def test_controlled_trajectories(tmp_path, number, expected):
    store = Store(tmp_path / 'trajectory.sqlite3')
    case = seed(store, number)
    assert board(store.snapshot(case))['claims'][0]['status'] == 'open'
    change(store, case, number)
    assert board(store.snapshot(case))['claims'][0]['status'] == expected


@pytest.mark.parametrize('content', [
    '{"conclusion":"supported","reason":"Evidence","notes":["wrong type"]}',
    '{"conclusion":"supported","reason":"Evidence","notes":"memo","extra":true}',
    'not JSON',
])
def test_invalid_reply_keeps_evidence_and_cost(content):
    result = parse_reply({'model': 'test', 'usage': {'cost': 0.01, 'prompt_tokens': 12},
                         'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}, [], 10)
    assert result['error_type'] == 'ValidationError'
    assert result['raw_content'] == content
    assert result['usage']['cost'] == 0.01
    assert result['validation_errors']
    assert 'answer' not in result


def test_valid_reply_is_scored_without_repair():
    content = '{"conclusion":"unknown","reason":"Wrong scope","notes":"Need applicable evidence"}'
    result = parse_reply({'model': 'test', 'choices': [{'message': {'content': content}}]}, [], 10)
    assert result['answer']['conclusion'] == 'unknown'
    assert result['raw_content'] == content
    assert result['usage'] == {}
