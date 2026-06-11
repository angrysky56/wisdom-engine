"""Wisdom Engine — MCP server for epistemic filtering via Via Negativa.

Tools:
  generate_hypotheses   — Fan out to 3 perspectives, generate structured hypotheses
  apply_via_negativa    — Run the subtraction engine (constraint check + Bayesian collider)
  synthesize_truth      — Compress surviving hypotheses into actionable output

LLM calls are made via MCP sampling: the server borrows the connected client's
LLM through ctx.session.create_message(). No API keys, no external modules.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import SamplingMessage, TextContent

from .engine import (
    apply_via_negativa as _engine_apply_via_negativa,
    generate_hypotheses as _engine_generate_hypotheses,
    synthesize_truth as _engine_synthesize_truth,
)
from .models import (
    EliminationRecord,
    FilterResult,
    Hypothesis,
    HypothesisType,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wisdom_engine")


# ---------------------------------------------------------------------------
# MCP Sampling bridge
# ---------------------------------------------------------------------------

def _make_llm_call(ctx: Context) -> Any:
    """Create an async llm_call callable that uses MCP sampling.

    Returns an ``async def llm_call(prompt: str) -> str`` that sends
    the prompt to the connected MCP client via ``create_message`` and
    returns the text response.
    """

    async def llm_call(prompt: str) -> str:
        result = await ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=prompt),
                )
            ],
            max_tokens=4096,
        )
        # Extract text from response content
        if isinstance(result.content, TextContent):
            return result.content.text
        # Fallback: content might be ImageContent or AudioContent
        return str(result.content)

    return llm_call


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _hypothesis_to_dict(h: Hypothesis) -> dict:
    """Convert a Hypothesis dataclass to a JSON-serializable dict."""
    return {
        "id": h.id,
        "text": h.text,
        "type": h.h_type.value,
        "d1_symptom": h.d1_symptom,
        "d2_mechanism": h.d2_mechanism,
        "d3_invariant": h.d3_invariant,
        "evidence": h.evidence,
        "eliminated": h.eliminated,
        "elimination_reason": h.elimination_reason,
        "elimination_detail": h.elimination_detail,
    }


def _filter_result_to_dict(fr: FilterResult) -> dict:
    """Convert a FilterResult dataclass to a JSON-serializable dict."""
    return {
        "surface_symptom": fr.surface_symptom,
        "all_hypotheses": [_hypothesis_to_dict(h) for h in fr.all_hypotheses],
        "surviving_hypotheses": [
            _hypothesis_to_dict(h) for h in fr.surviving_hypotheses
        ],
        "elimination_log": [
            {
                "hypothesis_id": r.hypothesis_id,
                "hypothesis_text": r.hypothesis_text,
                "reason": r.reason,
                "detail": r.detail,
            }
            for r in fr.elimination_log
        ],
        "strongest_mechanism": (
            _hypothesis_to_dict(fr.strongest_mechanism)
            if fr.strongest_mechanism
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Server (FastMCP)
# ---------------------------------------------------------------------------
mcp = FastMCP("wisdom-engine")


@mcp.tool()
async def generate_hypotheses(
    surface_symptom: str,
    context: str = "",
    ctx: Context = None,
) -> str:
    """Generate competing hypotheses from three perspectives.

    Fans out to mechanism, narrative, and constraint perspectives to produce
    hypotheses with recursive depth mapping (d1 symptom → d2 mechanism →
    d3 invariant). Uses MCP sampling to call the connected client's LLM.

    Args:
        surface_symptom: The observation, problem, or claim to explain.
        context: Supporting context from research agents.

    Returns:
        JSON with hypotheses array, each containing id, text, type, d1/d2/d3.
    """
    llm_call = _make_llm_call(ctx)
    hypotheses = await _engine_generate_hypotheses(
        llm_call, surface_symptom, context
    )
    return json.dumps(
        {
            "surface_symptom": surface_symptom,
            "hypotheses": [_hypothesis_to_dict(h) for h in hypotheses],
        },
        indent=2,
    )


@mcp.tool()
async def apply_via_negativa(
    surface_symptom: str,
    hypotheses: list[dict],
    known_constraints: list[str] | None = None,
    ctx: Context = None,
) -> str:
    """Apply the Via Negativa subtraction engine to competing hypotheses.

    Three elimination stages:
    A. Constraint check — does the hypothesis violate known constraints?
    B. Lakatosian cut — does it require ad hoc defenses (degenerating program)?
    C. Bayesian collider — is there a stronger mechanism that explains away
       competing narratives sharing the same symptom?

    Uses MCP sampling to call the connected client's LLM for each stage.

    Args:
        surface_symptom: The original observation being explained.
        hypotheses: List of hypothesis dicts (as returned by generate_hypotheses).
        known_constraints: Optional list of known invariant constraints.

    Returns:
        FilterResult as JSON: surviving hypotheses, elimination log,
        strongest mechanism.
    """
    # Reconstruct Hypothesis objects from input dicts
    hypo_objects = [
        Hypothesis(
            id=h_dict.get("id", ""),
            text=h_dict.get("text", ""),
            h_type=HypothesisType(h_dict.get("type", "mechanism")),
            d1_symptom=h_dict.get("d1_symptom", surface_symptom),
            d2_mechanism=h_dict.get("d2_mechanism", ""),
            d3_invariant=h_dict.get("d3_invariant", ""),
            evidence=h_dict.get("evidence", []),
        )
        for h_dict in hypotheses
    ]

    llm_call = _make_llm_call(ctx)
    result = await _engine_apply_via_negativa(
        llm_call, surface_symptom, hypo_objects, known_constraints
    )
    return json.dumps(_filter_result_to_dict(result), indent=2)


@mcp.tool()
async def synthesize_truth(
    filter_result: dict,
    ctx: Context = None,
) -> str:
    """Compress surviving hypotheses into an actionable truth.

    Takes the output of apply_via_negativa and produces a compressed,
    actionable synthesis with confidence score and next steps.
    Uses MCP sampling to call the connected client's LLM.

    Args:
        filter_result: The dict output from apply_via_negativa.

    Returns:
        JSON with actionable_truth, confidence, next_steps,
        remaining_uncertainties.
    """
    llm_call = _make_llm_call(ctx)

    # Reconstruct FilterResult from dict
    all_h = [
        Hypothesis(
            id=h_dict.get("id", ""),
            text=h_dict.get("text", ""),
            h_type=HypothesisType(h_dict.get("type", "mechanism")),
            d1_symptom=h_dict.get("d1_symptom", ""),
            d2_mechanism=h_dict.get("d2_mechanism", ""),
            d3_invariant=h_dict.get("d3_invariant", ""),
            evidence=h_dict.get("evidence", []),
            eliminated=h_dict.get("eliminated", False),
            elimination_reason=h_dict.get("elimination_reason", ""),
            elimination_detail=h_dict.get("elimination_detail", ""),
        )
        for h_dict in filter_result.get("all_hypotheses", [])
    ]

    surviving_h = [
        Hypothesis(
            id=h_dict.get("id", ""),
            text=h_dict.get("text", ""),
            h_type=HypothesisType(h_dict.get("type", "mechanism")),
            d1_symptom=h_dict.get("d1_symptom", ""),
            d2_mechanism=h_dict.get("d2_mechanism", ""),
            d3_invariant=h_dict.get("d3_invariant", ""),
        )
        for h_dict in filter_result.get("surviving_hypotheses", [])
    ]

    elim_log = [
        EliminationRecord(
            hypothesis_id=r_dict.get("hypothesis_id", ""),
            hypothesis_text=r_dict.get("hypothesis_text", ""),
            reason=r_dict.get("reason", ""),
            detail=r_dict.get("detail", ""),
        )
        for r_dict in filter_result.get("elimination_log", [])
    ]

    fr = FilterResult(
        surface_symptom=filter_result.get("surface_symptom", ""),
        all_hypotheses=all_h,
        surviving_hypotheses=surviving_h,
        elimination_log=elim_log,
    )

    result = await _engine_synthesize_truth(llm_call, fr)
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """Start the wisdom-engine MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
