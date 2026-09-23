"""Tests for the Wisdom Engine MCP server tools.

Tests use MCP's in-memory transport with a sampling callback to simulate
the connected client's LLM. This exercises the full MCP protocol path:
client → server → tool → engine → sampling → client → response.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest

import mcp.types as types
from mcp.shared.context import RequestContext
from mcp.shared.memory import create_connected_server_and_client_session

from wisdom_engine.legacy.server import mcp as wisdom_mcp


# ---------------------------------------------------------------------------
# Mock LLM responses
# ---------------------------------------------------------------------------

def _mechanism_response() -> str:
    return json.dumps({
        "hypothesis": "The system fails because of a race condition in the database layer",
        "d2_mechanism": "Concurrent writes without proper locking cause data corruption",
        "d3_invariant": "CAP theorem: distributed systems cannot guarantee consistency, availability, and partition tolerance simultaneously",
        "evidence": ["Error logs show duplicate key violations", "Load test reproduces at >100 concurrent writes"],
        "falsification_condition": "If adding row-level locking eliminates the errors",
    })


def _narrative_response() -> str:
    return json.dumps({
        "hypothesis": "The team believes the issue is caused by the new caching layer because it was deployed recently",
        "d2_mechanism": "Recency bias and blame attribution to the most visible change",
        "d3_invariant": "Humans attribute causality to temporally proximate events (post hoc ergo propter hoc)",
        "evidence": ["The caching layer was deployed 2 days before the first error"],
        "falsification_condition": "If errors persist after caching layer rollback",
    })


def _constraint_response() -> str:
    return json.dumps({
        "hypothesis": "The system cannot handle more than 500 concurrent users due to connection pool exhaustion",
        "d2_mechanism": "Each request holds a database connection; the pool has a fixed maximum size",
        "d3_invariant": "Resource bounds are hard limits — you cannot allocate more connections than the pool maximum",
        "evidence": ["Connection pool metrics show 100% utilization at 480 users"],
        "falsification_condition": "If increasing pool size raises the throughput ceiling",
    })


# ---------------------------------------------------------------------------
# Sampling callback factory
# ---------------------------------------------------------------------------

def _make_sampling_callback(responses: list[str]):
    """Create a sampling callback that returns canned responses in order.

    The callback conforms to the ``SamplingFnT`` protocol: it receives the
    request context and ``CreateMessageRequestParams`` and returns a
    ``CreateMessageResult``.
    """
    call_count = 0

    async def _callback(
        context: RequestContext[Any, Any],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult:
        nonlocal call_count
        idx = min(call_count, len(responses) - 1)
        call_count += 1
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text=responses[idx]),
            model="mock-model",
            stopReason="endTurn",
        )

    return _callback


# ---------------------------------------------------------------------------
# Helper: call a tool via the client session and parse the JSON response
# ---------------------------------------------------------------------------

async def _call_tool(client, name: str, arguments: dict) -> dict:
    """Call a tool and parse the JSON text result."""
    result = await client.call_tool(name, arguments)
    assert not result.isError, f"Tool {name} returned error: {result.content}"
    # The tool returns a single TextContent block with JSON
    assert len(result.content) == 1
    text = result.content[0].text
    return json.loads(text)


# ---------------------------------------------------------------------------
# generate_hypotheses tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGenerateHypotheses:
    async def test_generates_three_hypotheses(self):
        """Tool should produce 3 hypotheses (mechanism, narrative, constraint)."""
        responses = [
            _mechanism_response(),
            _narrative_response(),
            _constraint_response(),
        ]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            result = await _call_tool(client, "generate_hypotheses", {
                "surface_symptom": "Database errors under high load",
                "context": "Errors started after the v2.0 deploy",
            })

        assert len(result["hypotheses"]) == 3
        assert result["surface_symptom"] == "Database errors under high load"

    async def test_hypothesis_types(self):
        """Each of the three perspective types should be present."""
        responses = [
            _mechanism_response(),
            _narrative_response(),
            _constraint_response(),
        ]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            result = await _call_tool(client, "generate_hypotheses", {
                "surface_symptom": "Database errors",
            })

        h_types = {h["type"] for h in result["hypotheses"]}
        assert h_types == {"mechanism", "narrative", "constraint"}

    async def test_hypothesis_depth_fields(self):
        """Each hypothesis should have d1/d2/d3 depth fields populated."""
        responses = [
            _mechanism_response(),
            _narrative_response(),
            _constraint_response(),
        ]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            result = await _call_tool(client, "generate_hypotheses", {
                "surface_symptom": "Database errors",
            })

        for h in result["hypotheses"]:
            assert h["d1_symptom"] == "Database errors"
            assert h["d2_mechanism"], f"Missing d2_mechanism for {h['id']}"
            assert h["d3_invariant"], f"Missing d3_invariant for {h['id']}"
            assert isinstance(h["evidence"], list)


# ---------------------------------------------------------------------------
# apply_via_negativa tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestApplyViaNegativa:
    async def _generate_hypotheses(self, client) -> list[dict]:
        """Helper: generate hypotheses and return the list."""
        result = await _call_tool(client, "generate_hypotheses", {
            "surface_symptom": "Database errors",
        })
        return result["hypotheses"]

    async def test_full_pipeline_with_explain_away(self):
        """Full pipeline: generate, then filter. Narrative should be explained away."""
        responses = [
            # generate_hypotheses: 3 perspective calls
            _mechanism_response(),
            _narrative_response(),
            _constraint_response(),
            # apply_via_negativa Stage A: 3 constraint checks (all pass)
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            # Stage B: 3 Lakatos checks (all pass)
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            # Stage C: strongest mechanism
            json.dumps({"strongest_id": "PLACEHOLDER", "reasoning": "Direct causal evidence"}),
            # Stage C: explain away
            json.dumps({"results": [{"narrative_id": "PLACEHOLDER", "explained_away": True, "reasoning": "Mechanism explains the timing"}]}),
        ]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            # Generate
            gen_result = await _call_tool(client, "generate_hypotheses", {
                "surface_symptom": "Database errors",
            })
            hypotheses = gen_result["hypotheses"]

            # Patch placeholder IDs in the sampling responses with real IDs
            mech_id = next(h["id"] for h in hypotheses if h["type"] == "mechanism")
            narr_id = next(h["id"] for h in hypotheses if h["type"] == "narrative")

            # Re-seed the sampling callback with corrected IDs for the filter step
            # We need to update responses 9 and 10 with real IDs
            responses[9] = json.dumps({"strongest_id": mech_id, "reasoning": "Direct causal evidence"})
            responses[10] = json.dumps({"results": [{"narrative_id": narr_id, "explained_away": True, "reasoning": "Mechanism explains the timing"}]})

        # Run filter with fresh session using corrected responses
        # Start at index 3 since generate used 0-2
        filter_responses = [
            # Stage A: 3 constraint checks
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            # Stage B: 3 Lakatos checks
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            # Stage C
            json.dumps({"strongest_id": mech_id, "reasoning": "Direct causal evidence"}),
            json.dumps({"results": [{"narrative_id": narr_id, "explained_away": True, "reasoning": "Mechanism explains the timing"}]}),
        ]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(filter_responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            filter_result = await _call_tool(client, "apply_via_negativa", {
                "surface_symptom": "Database errors",
                "hypotheses": hypotheses,
                "known_constraints": ["Resources are finite"],
            })

        surviving_types = {h["type"] for h in filter_result["surviving_hypotheses"]}
        assert "mechanism" in surviving_types
        assert "narrative" not in surviving_types  # explained away
        assert len(filter_result["elimination_log"]) >= 1

    async def test_constraint_violation_eliminates(self):
        """A hypothesis violating a constraint should be quarantined."""
        # First generate hypotheses
        gen_responses = [_mechanism_response(), _narrative_response(), _constraint_response()]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(gen_responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            gen_result = await _call_tool(client, "generate_hypotheses", {
                "surface_symptom": "Database errors",
            })
        hypotheses = gen_result["hypotheses"]
        constr_id = next(h["id"] for h in hypotheses if h["type"] == "constraint")
        mech_id = next(h["id"] for h in hypotheses if h["type"] == "mechanism")

        # Now filter — the constraint hypothesis violates
        filter_responses = [
            # Stage A: mech OK, narrative OK, constraint VIOLATES
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            json.dumps({"violates": True, "which_constraint": "energy conservation", "reasoning": "Exceeds physical limit"}),
            # Stage B: 2 remaining pass (constraint already eliminated)
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            # Stage C
            json.dumps({"strongest_id": mech_id, "reasoning": "Best evidence"}),
            json.dumps({"results": []}),
        ]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(filter_responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            result = await _call_tool(client, "apply_via_negativa", {
                "surface_symptom": "Database errors",
                "hypotheses": hypotheses,
                "known_constraints": ["Energy is conserved"],
            })

        surviving_ids = {h["id"] for h in result["surviving_hypotheses"]}
        assert constr_id not in surviving_ids
        quarantined = [e for e in result["elimination_log"] if e["reason"] == "quarantined"]
        assert len(quarantined) >= 1

    async def test_degenerating_hypothesis_cut(self):
        """A degenerating hypothesis should be Lakatos-cut in Stage B."""
        gen_responses = [_mechanism_response(), _narrative_response(), _constraint_response()]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(gen_responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            gen_result = await _call_tool(client, "generate_hypotheses", {
                "surface_symptom": "Database errors",
            })
        hypotheses = gen_result["hypotheses"]
        mech_id = next(h["id"] for h in hypotheses if h["type"] == "mechanism")

        filter_responses = [
            # Stage A: all pass
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            json.dumps({"violates": False, "which_constraint": "none", "reasoning": "OK"}),
            # Stage B: narrative is degenerating
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            json.dumps({"degenerating": True, "reasoning": "Non-falsifiable: confirms everything, predicts nothing"}),
            json.dumps({"degenerating": False, "reasoning": "Progressive"}),
            # Stage C
            json.dumps({"strongest_id": mech_id, "reasoning": "Best"}),
            json.dumps({"results": []}),
        ]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(filter_responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            result = await _call_tool(client, "apply_via_negativa", {
                "surface_symptom": "Database errors",
                "hypotheses": hypotheses,
                "known_constraints": ["Resources are finite"],
            })

        surviving_types = {h["type"] for h in result["surviving_hypotheses"]}
        assert "narrative" not in surviving_types
        cut = [e for e in result["elimination_log"] if e["reason"] == "degenerating"]
        assert len(cut) >= 1

    async def test_empty_hypotheses(self):
        """Filtering an empty hypothesis list should return empty results."""
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback([]),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            result = await _call_tool(client, "apply_via_negativa", {
                "surface_symptom": "Test",
                "hypotheses": [],
            })

        assert result["surviving_hypotheses"] == []
        assert result["elimination_log"] == []


# ---------------------------------------------------------------------------
# synthesize_truth tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSynthesizeTruth:
    async def test_synthesis_produces_actionable_truth(self):
        """Synthesis should return actionable_truth, confidence, and next_steps."""
        filter_result = {
            "surface_symptom": "Database errors under load",
            "all_hypotheses": [
                {"id": "mech_1", "text": "Race condition", "type": "mechanism",
                 "d1_symptom": "errors", "d2_mechanism": "concurrent writes",
                 "d3_invariant": "CAP", "evidence": [], "eliminated": False,
                 "elimination_reason": "", "elimination_detail": ""},
                {"id": "narr_1", "text": "Blame caching", "type": "narrative",
                 "d1_symptom": "errors", "d2_mechanism": "recency bias",
                 "d3_invariant": "post hoc", "evidence": [], "eliminated": True,
                 "elimination_reason": "explained_away",
                 "elimination_detail": "Mechanism explains it"},
            ],
            "surviving_hypotheses": [
                {"id": "mech_1", "text": "Race condition", "type": "mechanism",
                 "d1_symptom": "errors", "d2_mechanism": "concurrent writes",
                 "d3_invariant": "CAP"},
            ],
            "elimination_log": [
                {"hypothesis_id": "narr_1", "hypothesis_text": "Blame caching",
                 "reason": "explained_away", "detail": "Mechanism explains it"},
            ],
        }
        synth_responses = [
            json.dumps({
                "actionable_truth": "Add row-level locking to the database write path",
                "next_steps": ["Implement locking", "Add monitoring"],
                "remaining_uncertainties": ["Cache interaction"],
            }),
        ]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(synth_responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            result = await _call_tool(client, "synthesize_truth", {
                "filter_result": filter_result,
            })

        assert result["actionable_truth"] == "Add row-level locking to the database write path"
        # Confidence is survival-rate based: 1/2 = 0.5
        assert result["confidence"] == 0.5
        assert len(result["next_steps"]) == 2

    async def test_synthesis_no_survivors(self):
        """When all hypotheses are eliminated, confidence should be 0."""
        filter_result = {
            "surface_symptom": "Unknown issue",
            "all_hypotheses": [
                {"id": "mech_1", "text": "Guess", "type": "mechanism",
                 "d1_symptom": "", "d2_mechanism": "", "d3_invariant": "",
                 "evidence": [], "eliminated": True,
                 "elimination_reason": "quarantined",
                 "elimination_detail": "Violated constraints"},
            ],
            "surviving_hypotheses": [],
            "elimination_log": [
                {"hypothesis_id": "mech_1", "hypothesis_text": "Guess",
                 "reason": "quarantined", "detail": "Violated constraints"},
            ],
        }
        synth_responses = [
            json.dumps({
                "actionable_truth": "All hypotheses eliminated — need more data",
                "next_steps": ["Gather more evidence"],
                "remaining_uncertainties": ["Root cause unknown"],
            }),
        ]
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            sampling_callback=_make_sampling_callback(synth_responses),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            result = await _call_tool(client, "synthesize_truth", {
                "filter_result": filter_result,
            })

        assert result["confidence"] == 0.0
        assert "Gather more evidence" in result["next_steps"]


# ---------------------------------------------------------------------------
# Backend-unavailable test (fail loudly, no fabricated results)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestNoBackendAvailable:
    async def test_tool_errors_when_no_llm_backend(self, monkeypatch):
        """Client without sampling + no OpenRouter key + no Ollama → clear error."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        # Point Ollama probe at a dead port so a locally running Ollama
        # can't make this test pass by accident.
        monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")

        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:  # no sampling_callback → no sampling capability
            result = await client.call_tool("generate_hypotheses", {
                "surface_symptom": "Database errors",
            })

        assert result.isError
        text = result.content[0].text
        assert "No LLM backend available" in text


# ---------------------------------------------------------------------------
# Tool listing test (integration smoke test)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestToolListing:
    async def test_tools_are_registered(self):
        """All three tools should be listed with no raw_llm_response params."""
        async with create_connected_server_and_client_session(
            server=wisdom_mcp,
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            result = await client.list_tools()

        tool_names = {t.name for t in result.tools}
        assert "generate_hypotheses" in tool_names
        assert "apply_via_negativa" in tool_names
        assert "synthesize_truth" in tool_names

        # Verify no raw_llm_response params are exposed
        for tool in result.tools:
            param_names = set(tool.inputSchema.get("properties", {}).keys())
            assert "raw_llm_response" not in param_names
            assert "raw_llm_responses" not in param_names
