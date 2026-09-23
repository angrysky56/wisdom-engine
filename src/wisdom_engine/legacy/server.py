"""Wisdom Engine — MCP server for epistemic filtering via Via Negativa.

Tools:
  generate_hypotheses   — Fan out to 3 perspectives, generate structured hypotheses
  apply_via_negativa    — Run the subtraction engine (constraint check + Bayesian collider)
  synthesize_truth      — Compress surviving hypotheses into actionable output

LLM backend chain (first available wins):
  1. MCP sampling — only if the client declared the sampling capability
  2. OpenRouter   — when OPENROUTER_API_KEY is set
  3. Ollama       — when a local Ollama server is reachable

If none is available, tools fail loudly with a clear error instead of
returning fabricated results.
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import Context, FastMCP

from .engine import (
    apply_via_negativa as _engine_apply_via_negativa,
    generate_hypotheses as _engine_generate_hypotheses,
    synthesize_truth as _engine_synthesize_truth,
)
from .llm import resolve_llm_call
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
    d3 invariant). Uses the first available LLM backend
    (MCP sampling → OpenRouter → Ollama).

    Args:
        surface_symptom: The observation, problem, or claim to explain.
        context: Supporting context from research agents.

    Returns:
        JSON with hypotheses array, each containing id, text, type, d1/d2/d3,
        and the llm_backend that produced them.
    """
    llm_call, backend = await resolve_llm_call(ctx)
    hypotheses = await _engine_generate_hypotheses(
        llm_call, surface_symptom, context
    )
    return json.dumps(
        {
            "surface_symptom": surface_symptom,
            "llm_backend": backend,
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
       (Skipped when no known_constraints are provided.)
    B. Lakatosian cut — does it require ad hoc defenses (degenerating program)?
    C. Bayesian collider — is there a stronger mechanism that explains away
       competing narratives sharing the same symptom?

    Uses the first available LLM backend (MCP sampling → OpenRouter → Ollama).
    Fails loudly if a stage's LLM call fails — a check that did not run
    never counts as a check that passed.

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

    llm_call, backend = await resolve_llm_call(ctx)
    result = await _engine_apply_via_negativa(
        llm_call, surface_symptom, hypo_objects, known_constraints
    )
    out = _filter_result_to_dict(result)
    out["llm_backend"] = backend
    return json.dumps(out, indent=2)


@mcp.tool()
async def synthesize_truth(
    filter_result: dict,
    ctx: Context = None,
) -> str:
    """Compress surviving hypotheses into an actionable truth.

    Takes the output of apply_via_negativa and produces a compressed,
    actionable synthesis with confidence score and next steps.
    Uses the first available LLM backend (MCP sampling → OpenRouter → Ollama).
    Confidence is structural (survival rate), never LLM self-report.

    Args:
        filter_result: The dict output from apply_via_negativa.

    Returns:
        JSON with actionable_truth, confidence, next_steps,
        remaining_uncertainties.
    """
    llm_call, backend = await resolve_llm_call(ctx)

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
    result["llm_backend"] = backend
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """Start the wisdom-engine MCP server.

    Configuration precedence: OS environment variables always win;
    a .env file (searched from the working directory upward, i.e. the
    project root when launched via ``uv --directory ... run``) fills in
    anything not already set. Keep secrets like OPENROUTER_API_KEY in
    the OS environment; .env is for non-secret settings (model, host).

    Transport (via WISDOM_TRANSPORT): "stdio" (default) — client spawns
    the process; or "streamable-http" — long-running shared server on
    WISDOM_HTTP_HOST:WISDOM_HTTP_PORT (default 127.0.0.1:8765, /mcp).
    """
    import os

    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True), override=False)

    transport = os.environ.get("WISDOM_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        mcp.run()
    elif transport == "streamable-http":
        mcp.settings.host = os.environ.get("WISDOM_HTTP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("WISDOM_HTTP_PORT", "8765"))
        logger.info(
            "Serving streamable HTTP at http://%s:%s/mcp",
            mcp.settings.host, mcp.settings.port,
        )
        mcp.run(transport="streamable-http")
    else:
        raise ValueError(
            f"Unknown WISDOM_TRANSPORT {transport!r}: "
            "use 'stdio' or 'streamable-http'"
        )


if __name__ == "__main__":
    main()
