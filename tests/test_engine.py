"""Tests for the Wisdom Engine core engine logic."""

from __future__ import annotations

import json

import pytest

from wisdom_engine.engine import (
    _parse_json_response,
    _build_hypothesis,
    apply_via_negativa,
    unroll_depths,
)
from wisdom_engine.models import Hypothesis, HypothesisType


# ---------------------------------------------------------------------------
# _parse_json_response tests
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_plain_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_fences(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_markdown_fences_no_lang(self):
        raw = '```\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# _build_hypothesis tests
# ---------------------------------------------------------------------------

class TestBuildHypothesis:
    def test_builds_from_parsed(self):
        parsed = {
            "hypothesis": "Test hypothesis",
            "d2_mechanism": "How it works",
            "d3_invariant": "Root law",
            "evidence": ["ev1", "ev2"],
        }
        h = _build_hypothesis("test_1", HypothesisType.MECHANISM, parsed, "symptom text")
        assert h.id == "test_1"
        assert h.text == "Test hypothesis"
        assert h.h_type == HypothesisType.MECHANISM
        assert h.d1_symptom == "symptom text"
        assert h.d2_mechanism == "How it works"
        assert h.d3_invariant == "Root law"
        assert h.evidence == ["ev1", "ev2"]
        assert not h.eliminated


# ---------------------------------------------------------------------------
# unroll_depths tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestUnrollDepths:
    async def test_skips_already_populated(self):
        h = Hypothesis(
            id="test_1",
            text="Already has depth",
            h_type=HypothesisType.MECHANISM,
            d1_symptom="symptom",
            d2_mechanism="mechanism",
            d3_invariant="invariant",
        )

        async def mock_llm(prompt: str) -> str:
            raise RuntimeError("Should not be called")

        result = await unroll_depths(mock_llm, [h])
        assert result[0].d2_mechanism == "mechanism"
        assert result[0].d3_invariant == "invariant"

    async def test_unrolls_missing_depth(self):
        h = Hypothesis(
            id="test_1",
            text="Missing depth",
            h_type=HypothesisType.MECHANISM,
            d1_symptom="symptom",
        )

        async def mock_llm(prompt: str) -> str:
            return json.dumps({
                "d2_mechanism": "extracted mechanism",
                "d3_invariant": "extracted invariant",
                "evidence": ["ev1"],
                "falsification_condition": "condition",
            })

        result = await unroll_depths(mock_llm, [h])
        assert result[0].d2_mechanism == "extracted mechanism"
        assert result[0].d3_invariant == "extracted invariant"
        assert result[0].evidence == ["ev1"]

    async def test_handles_llm_failure(self):
        h = Hypothesis(
            id="test_1",
            text="Will fail",
            h_type=HypothesisType.MECHANISM,
            d1_symptom="symptom",
        )

        async def mock_llm(prompt: str) -> str:
            raise RuntimeError("LLM down")

        result = await unroll_depths(mock_llm, [h])
        assert result[0].d2_mechanism == "[unroll failed]"
        assert result[0].d3_invariant == "[unroll failed]"


# ---------------------------------------------------------------------------
# apply_via_negativa integration-style tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestApplyViaNegativa:
    async def test_full_pipeline_all_survive(self):
        hypotheses = [
            Hypothesis(
                id="mech_1", text="Mechanism A", h_type=HypothesisType.MECHANISM,
                d1_symptom="symptom", d2_mechanism="mech A", d3_invariant="law A",
            ),
            Hypothesis(
                id="narr_1", text="Narrative B", h_type=HypothesisType.NARRATIVE,
                d1_symptom="symptom", d2_mechanism="narr B", d3_invariant="law B",
            ),
            Hypothesis(
                id="constr_1", text="Constraint C", h_type=HypothesisType.CONSTRAINT,
                d1_symptom="symptom", d2_mechanism="constr C", d3_invariant="law C",
            ),
        ]

        call_count = 0
        responses = [
            # Constraint checks (3)
            {"violates": False, "which_constraint": "none", "reasoning": "OK"},
            {"violates": False, "which_constraint": "none", "reasoning": "OK"},
            {"violates": False, "which_constraint": "none", "reasoning": "OK"},
            # Lakatos checks (3)
            {"degenerating": False, "reasoning": "OK"},
            {"degenerating": False, "reasoning": "OK"},
            {"degenerating": False, "reasoning": "OK"},
            # Strongest mechanism
            {"strongest_id": "mech_1", "reasoning": "Strongest"},
            # Explain away
            {"results": [{"narrative_id": "narr_1", "explained_away": True, "reasoning": "Explained"}]},
        ]

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return json.dumps(responses[idx])

        result = await apply_via_negativa(mock_llm, "symptom", hypotheses)

        surviving_ids = [h.id for h in result.surviving_hypotheses]
        assert "mech_1" in surviving_ids
        assert "constr_1" in surviving_ids
        assert "narr_1" not in surviving_ids  # explained away

        assert len(result.elimination_log) == 1
        assert result.elimination_log[0].reason == "explained_away"
        assert result.strongest_mechanism is not None
        assert result.strongest_mechanism.id == "mech_1"

    async def test_constraint_violation(self):
        hypotheses = [
            Hypothesis(
                id="mech_1", text="Mechanism A", h_type=HypothesisType.MECHANISM,
                d1_symptom="symptom", d2_mechanism="mech A", d3_invariant="law A",
            ),
            Hypothesis(
                id="bad_1", text="Bad hypothesis", h_type=HypothesisType.CONSTRAINT,
                d1_symptom="symptom", d2_mechanism="bad", d3_invariant="violates physics",
            ),
        ]

        call_count = 0
        responses = [
            {"violates": False, "which_constraint": "none", "reasoning": "OK"},
            {"violates": True, "which_constraint": "thermodynamics", "reasoning": "Violates energy conservation"},
            {"degenerating": False, "reasoning": "OK"},
            {"strongest_id": "mech_1", "reasoning": "Only one left"},
            {"results": []},
        ]

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return json.dumps(responses[idx])

        result = await apply_via_negativa(mock_llm, "symptom", hypotheses)

        surviving_ids = [h.id for h in result.surviving_hypotheses]
        assert "mech_1" in surviving_ids
        assert "bad_1" not in surviving_ids

        quarantined = [e for e in result.elimination_log if e.reason == "quarantined"]
        assert len(quarantined) == 1
        assert "thermodynamics" in quarantined[0].detail

    async def test_degenerating_cut(self):
        hypotheses = [
            Hypothesis(
                id="mech_1", text="Mechanism A", h_type=HypothesisType.MECHANISM,
                d1_symptom="symptom", d2_mechanism="mech A", d3_invariant="law A",
            ),
            Hypothesis(
                id="narr_1", text="Unfalsifiable narrative", h_type=HypothesisType.NARRATIVE,
                d1_symptom="symptom", d2_mechanism="narr B", d3_invariant="law B",
            ),
        ]

        call_count = 0
        responses = [
            {"violates": False, "which_constraint": "none", "reasoning": "OK"},
            {"violates": False, "which_constraint": "none", "reasoning": "OK"},
            {"degenerating": False, "reasoning": "OK"},
            {"degenerating": True, "reasoning": "Non-falsifiable — explains everything, predicts nothing"},
            {"strongest_id": "mech_1", "reasoning": "Strongest"},
            {"results": []},
        ]

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return json.dumps(responses[idx])

        result = await apply_via_negativa(mock_llm, "symptom", hypotheses)

        surviving_ids = [h.id for h in result.surviving_hypotheses]
        assert "mech_1" in surviving_ids
        assert "narr_1" not in surviving_ids

        cut = [e for e in result.elimination_log if e.reason == "degenerating"]
        assert len(cut) == 1
        assert "Non-falsifiable" in cut[0].detail

    async def test_empty_hypotheses(self):
        async def mock_llm(prompt: str) -> str:
            return "{}"

        result = await apply_via_negativa(mock_llm, "symptom", [])
        assert result.surviving_hypotheses == []
        assert result.elimination_log == []
        assert result.strongest_mechanism is None

    async def test_no_mechanisms_means_no_collider(self):
        """If no mechanism hypotheses exist, skip the Bayesian collider test."""
        hypotheses = [
            Hypothesis(
                id="narr_1", text="Narrative A", h_type=HypothesisType.NARRATIVE,
                d1_symptom="symptom", d2_mechanism="narr A", d3_invariant="law A",
            ),
            Hypothesis(
                id="narr_2", text="Narrative B", h_type=HypothesisType.NARRATIVE,
                d1_symptom="symptom", d2_mechanism="narr B", d3_invariant="law B",
            ),
        ]

        call_count = 0
        responses = [
            {"violates": False, "which_constraint": "none", "reasoning": "OK"},
            {"violates": False, "which_constraint": "none", "reasoning": "OK"},
            {"degenerating": False, "reasoning": "OK"},
            {"degenerating": False, "reasoning": "OK"},
        ]

        async def mock_llm(prompt: str) -> str:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return json.dumps(responses[idx])

        result = await apply_via_negativa(mock_llm, "symptom", hypotheses)
        # Both survive — no mechanism to trigger collider
        assert len(result.surviving_hypotheses) == 2

    async def test_prover_eliminates_formalizable_hypothesis(self):
        """When a prover_call is provided and the constraint is formalizable,
        Stage A should use it instead of the LLM."""
        hypotheses = [
            Hypothesis(
                id="mech_1", text="Valid mechanism", h_type=HypothesisType.MECHANISM,
                d1_symptom="symptom", d2_mechanism="mech A", d3_invariant="all x (P(x) -> Q(x))",
            ),
            Hypothesis(
                id="bad_1", text="Violates constraint", h_type=HypothesisType.CONSTRAINT,
                d1_symptom="symptom", d2_mechanism="bad", d3_invariant="exists x (P(x) and not Q(x))",
            ),
        ]

        async def mock_llm(prompt: str) -> str:
            # LLM should NOT be called for constraint checks when prover is available
            raise RuntimeError("LLM should not be called for formalizable constraints")

        async def mock_prover(premises: list[str], conclusion: str) -> dict:
            # The bad hypothesis's invariant contradicts the constraint
            if "not Q" in conclusion or "not Q" in str(premises):
                return {"proved": True, "reasoning": "Contradiction found"}
            return {"proved": False}

        result = await apply_via_negativa(
            mock_llm, "symptom", hypotheses,
            known_constraints=["all x (P(x) -> Q(x))"],
            prover_call=mock_prover,
        )

        surviving_ids = [h.id for h in result.surviving_hypotheses]
        assert "mech_1" in surviving_ids
        assert "bad_1" not in surviving_ids

        quarantined = [e for e in result.elimination_log if e.reason == "quarantined"]
        assert len(quarantined) == 1
        assert "Formal proof" in quarantined[0].detail

    async def test_prover_fallback_to_llm(self):
        """When prover fails or constraint is not formalizable, fall back to LLM."""
        hypotheses = [
            Hypothesis(
                id="h_1", text="Vague hypothesis", h_type=HypothesisType.MECHANISM,
                d1_symptom="symptom", d2_mechanism="mech", d3_invariant="things generally work this way",
            ),
        ]

        async def mock_llm(prompt: str) -> str:
            return json.dumps({
                "violates": False,
                "which_constraint": "none",
                "reasoning": "Cannot formalize — LLM judgment",
            })

        async def mock_prover(premises: list[str], conclusion: str) -> dict:
            # Prover can't handle vague statements
            raise RuntimeError("Cannot parse vague invariant")

        result = await apply_via_negativa(
            mock_llm, "symptom", hypotheses,
            known_constraints=["some domain knowledge"],
            prover_call=mock_prover,
        )

        assert len(result.surviving_hypotheses) == 1
        assert result.surviving_hypotheses[0].id == "h_1"
