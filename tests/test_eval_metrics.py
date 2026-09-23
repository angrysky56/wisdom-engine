"""Evaluation reporting must expose class imbalance and mistakes, not just total accuracy."""
import pytest

from evals.run import summarize


def test_confusion_and_macro_accuracy_use_reference_class_denominators():
    cases = [{'id': name} for name in ('a', 'b', 'c', 'd')]
    gold = {'a': 'supports', 'b': 'supports', 'c': 'supports', 'd': 'unknown'}
    answers = {f'pair_{i}': {'choice': 'supports'} for i in range(4)}
    result = summarize(cases, gold, answers)
    assert result['accuracy'] == 0.75
    assert result['macro_accuracy'] == 0.5
    assert result['confusion_expected_by_predicted']['unknown']['supports'] == 1
    assert result['per_class_recall']['neutral'] is None
    assert result['mean_brier'] is None


def test_brier_includes_each_label_probability():
    result = summarize([{'id': 'a'}], {'a': 'supports'}, {'pair_0': {
        'choice': 'supports', 'probabilities': {'supports': 0.7, 'conflicts': 0.1, 'neutral': 0.1, 'unknown': 0.1}}})
    assert result['mean_brier'] == pytest.approx(0.12)
