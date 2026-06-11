"""Wisdom Engine — Via Negativa subtraction engine.

Implements the epistemic filtering pipeline:
  1. Hypothesis generation (fan out to N perspectives)
  2. Recursive depth mapping (d1 symptom → d2 mechanism → d3 invariant)
  3. Subtraction via constraint checks + Bayesian explaining-away
  4. Synthesis of surviving hypotheses

Stage A (constraint check) uses a dual path:
  - Formalizable constraints (logical consistency, quantitative bounds) are verified
    via mcp-logic's prove/find_counterexample — this is the "emergency brake"
    that cannot be sweet-talked.
  - Non-formalizable constraints (domain knowledge, heuristic bounds) fall back
    to LLM judgment.

Stage C (Bayesian collider) is intentionally asymmetric: mechanisms can explain
away narratives, but not the reverse. This is a design opinion: the filter is
mechanistic-explanation-first. When the social dynamic IS the mechanism (markets,
panics, norms), the mechanism hypothesis should encode that directly rather than
relying on a narrative hypothesis to survive. Documented, not hidden.
"""

from __future__ import annotations

import json
import asyncio
import logging
import uuid
from typing import Any

from .models import (
    EliminationRecord,
    FilterResult,
    Hypothesis,
    HypothesisType,
)

logger = logging.getLogger("wisdom_engine")

# ---------------------------------------------------------------------------
# Perspective prompts for hypothesis generation
# ---------------------------------------------------------------------------

MECHANISM_PROMPT = """You are analyzing the following observation/symptom:

{symptom}

Context:
{context}

Your task: Propose the most likely STRUCTURAL/MECHANISTIC explanation.
Focus on: How does this actually work? What are the physical, technical, or
systemic causes? What would you measure to verify this?

Respond in JSON:
{{
  "hypothesis": "one concise sentence",
  "d2_mechanism": "the generative mechanism (2-3 sentences)",
  "d3_invariant": "the root law or invariant this depends on",
  "evidence": ["piece of evidence 1", "piece of evidence 2"],
  "falsification_condition": "what observation would disprove this"
}}"""

NARRATIVE_PROMPT = """You are analyzing the following observation/symptom:

{symptom}

Context:
{context}

Your task: Propose the most likely NARRATIVE/PSYCHOLOGICAL explanation.
Focus on: Why do people believe this? What social, cognitive, or political
dynamics are at play? What story makes this seem true even if it isn't?

Respond in JSON:
{{
  "hypothesis": "one concise sentence",
  "d2_mechanism": "the social/psychological mechanism (2-3 sentences)",
  "d3_invariant": "the root law or invariant this depends on",
  "evidence": ["piece of evidence 1", "piece of evidence 2"],
  "falsification_condition": "what observation would disprove this"
}}"""

CONSTRAINT_PROMPT = """You are analyzing the following observation/symptom:

{symptom}

Context:
{context}

Your task: Propose the most likely CONSTRAINT/BOUNDARY explanation.
Focus on: What are the hard limits here? What physical, economic, or logical
constraints make some solutions impossible? What is being overlooked?

Respond in JSON:
{{
  "hypothesis": "one concise sentence",
  "d2_mechanism": "the constraint mechanism (2-3 sentences)",
  "d3_invariant": "the root law or invariant this depends on",
  "evidence": ["piece of evidence 1", "piece of evidence 2"],
  "falsification_condition": "what observation would disprove this"
}}"""


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Parse JSON from an LLM response, handling markdown code fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # Remove opening ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # Remove closing ```
        text = "\n".join(lines)
    return json.loads(text)


def _build_hypothesis(
    h_id: str,
    h_type: HypothesisType,
    parsed: dict[str, Any],
    symptom: str,
) -> Hypothesis:
    """Build a Hypothesis from a parsed LLM response."""
    return Hypothesis(
        id=h_id,
        text=parsed.get("hypothesis", ""),
        h_type=h_type,
        d1_symptom=symptom,
        d2_mechanism=parsed.get("d2_mechanism", ""),
        d3_invariant=parsed.get("d3_invariant", ""),
        evidence=parsed.get("evidence", []),
    )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

async def generate_hypotheses(
    llm_call: Any,
    surface_symptom: str,
    context: str = "",
) -> list[Hypothesis]:
    """Fan out to three perspectives and generate structured hypotheses.

    Args:
        llm_call: Async callable(prompt: str) -> str — the LLM interface.
        surface_symptom: The observation or problem to explain.
        context: Supporting context from research agents.

    Returns:
        List of 3 Hypothesis objects (mechanism, narrative, constraint).
    """
    prompts = [
        (MECHANISM_PROMPT, HypothesisType.MECHANISM, "mech"),
        (NARRATIVE_PROMPT, HypothesisType.NARRATIVE, "narr"),
        (CONSTRAINT_PROMPT, HypothesisType.CONSTRAINT, "constr"),
    ]

    async def _generate_one(template: str, h_type: HypothesisType, short_id: str) -> Hypothesis:
        prompt = template.format(symptom=surface_symptom, context=context)
        try:
            raw = await llm_call(prompt)
            parsed = _parse_json_response(raw)
            return _build_hypothesis(
                h_id=f"{short_id}_{uuid.uuid4().hex[:6]}",
                h_type=h_type,
                parsed=parsed,
                symptom=surface_symptom,
            )
        except Exception as e:
            logger.error("Hypothesis generation failed for %s: %s", h_type.value, e)
            return Hypothesis(
                id=f"{short_id}_{uuid.uuid4().hex[:6]}",
                text=f"[Generation failed: {e}]",
                h_type=h_type,
                d1_symptom=surface_symptom,
            )

    tasks = [_generate_one(template, h_type, short_id) for template, h_type, short_id in prompts]
    results = await asyncio.gather(*tasks)
    return list(results)


# ---------------------------------------------------------------------------
# Recursive unrolling (depth mapping)
# ---------------------------------------------------------------------------

async def unroll_depths(
    llm_call: Any,
    hypotheses: list[Hypothesis],
) -> list[Hypothesis]:
    """Ensure every hypothesis has d2 (mechanism) and d3 (invariant) populated.

    For hypotheses that were provided as plain strings without structured depth,
    run an LLM call to extract the deeper layers.

    Args:
        llm_call: Async callable(prompt: str) -> str.
        hypotheses: Hypotheses to unroll.

    Returns:
        The same hypotheses with d2/d3 populated.
    """
    UNROLL_PROMPT = """Given this hypothesis about the symptom "{symptom}":

Hypothesis: {hypothesis}

Extract the deeper layers. Respond in JSON:
{{
  "d2_mechanism": "the generative mechanism — how does this actually work?",
  "d3_invariant": "the root law or invariant — what fundamental principle does this depend on?",
  "evidence": ["evidence 1", "evidence 2"],
  "falsification_condition": "what would disprove this"
}}"""

    async def _unroll_one(h: Hypothesis) -> None:
        if h.d2_mechanism and h.d3_invariant:
            return
        try:
            prompt = UNROLL_PROMPT.format(
                symptom=h.d1_symptom,
                hypothesis=h.text,
            )
            raw = await llm_call(prompt)
            parsed = _parse_json_response(raw)
            h.d2_mechanism = parsed.get("d2_mechanism", "")
            h.d3_invariant = parsed.get("d3_invariant", "")
            if parsed.get("evidence"):
                h.evidence = parsed["evidence"]
        except Exception as e:
            logger.error("Depth unroll failed for %s: %s", h.id, e)
            h.d2_mechanism = h.d2_mechanism or "[unroll failed]"
            h.d3_invariant = h.d3_invariant or "[unroll failed]"

    tasks = [_unroll_one(h) for h in hypotheses]
    await asyncio.gather(*tasks)
    return hypotheses


# ---------------------------------------------------------------------------
# Stage A: Constraint check with formal verification
# ---------------------------------------------------------------------------

def _is_formalizable(constraint: str, invariant: str) -> bool:
    """Heuristic: can this constraint+invariant pair be expressed as FOL?

    Returns True if the constraint and invariant contain formalizable
    language (quantifiers, logical operators, mathematical relations).
    """
    formal_keywords = [
        "all ", "every ", "any ", "no ", "exists ", "at least", "at most",
        "greater than", "less than", "equal to", "not ", "and ", "or ",
        "if ", "then ", "implies ", "iff ", "only if",
        "<", ">", "<=", ">=", "=", "!=", "≠", "≤", "≥",
        "sum", "total", "maximum", "minimum", "bound", "limit",
        "cannot", "impossible", "must", "required", "necessary",
    ]
    combined = (constraint + " " + invariant).lower()
    return any(kw in combined for kw in formal_keywords)


async def _check_constraint_formal(
    prover_call: Any,
    hypothesis: Hypothesis,
    known_constraints: list[str],
) -> tuple[bool, str]:
    """Use formal prover to check if hypothesis violates known constraints.

    Returns (violates: bool, detail: str).
    """
    # Build premises from known constraints
    premises = known_constraints + [hypothesis.d3_invariant]
    conclusion = f"not ({hypothesis.d3_invariant})"

    try:
        # Try to prove that the constraints entail a contradiction with the invariant
        result = await prover_call(
            premises=premises,
            conclusion=conclusion,
        )
        if result.get("proved", False):
            return True, f"Formal proof: constraints contradict the invariant. {result.get('reasoning', '')}"
    except Exception as e:
        logger.warning("Formal prover failed, falling back to LLM: %s", e)

    # Fallback: try to find a counterexample
    try:
        result = await prover_call(
            premises=premises,
            conclusion=hypothesis.d3_invariant,
        )
        if result.get("result") == "unprovable":
            # The invariant doesn't follow from constraints — not necessarily a violation
            # but worth flagging
            pass
    except Exception:
        pass

    return False, ""


async def _check_constraint_llm(
    llm_call: Any,
    hypothesis: Hypothesis,
    known_constraints: list[str],
) -> tuple[bool, str]:
    """Use LLM to check if hypothesis violates known constraints."""
    CONSTRAINT_CHECK_PROMPT = """Known constraints (physical, economic, logical, or domain-specific):
{constraints}

Hypothesis: {hypothesis}
Proposed invariant: {invariant}

Does this hypothesis VIOLATE any of the known constraints? Respond in JSON:
{{
  "violates": true_or_false,
  "which_constraint": "the specific constraint violated, or 'none'",
  "reasoning": "brief explanation"
}}"""

    constraints_text = "\n".join(f"- {c}" for c in (known_constraints or []))
    if not constraints_text:
        constraints_text = "- No specific constraints provided"

    prompt = CONSTRAINT_CHECK_PROMPT.format(
        constraints=constraints_text,
        hypothesis=hypothesis.text,
        invariant=hypothesis.d3_invariant,
    )
    raw = await llm_call(prompt)
    parsed = _parse_json_response(raw)

    if parsed.get("violates", False):
        detail = (
            f"Violates constraint: {parsed.get('which_constraint', 'unknown')}. "
            f"{parsed.get('reasoning', '')}"
        )
        return True, detail
    return False, ""


# ---------------------------------------------------------------------------
# Subtraction engine (Via Negativa)
# ---------------------------------------------------------------------------

async def apply_via_negativa(
    llm_call: Any,
    surface_symptom: str,
    hypotheses: list[Hypothesis],
    known_constraints: list[str] | None = None,
    prover_call: Any | None = None,
) -> FilterResult:
    """Apply the Via Negativa subtraction engine.

    Three elimination stages:
    A. Constraint check — does the hypothesis violate known constraints?
       Uses formal prover (mcp-logic) for formalizable constraints, LLM fallback.
    B. Lakatosian cut — does the hypothesis require ad hoc defenses?
    C. Bayesian collider — is there a stronger mechanism that explains away
       competing narratives sharing the same symptom?

    Stage C is intentionally asymmetric: mechanisms explain away narratives,
    not the reverse. When social dynamics are the mechanism, encode them
    in the mechanism hypothesis directly.

    Args:
        llm_call: Async callable(prompt: str) -> str.
        surface_symptom: The original observation.
        hypotheses: Competing hypotheses to filter.
        known_constraints: Optional list of known invariant constraints.
        prover_call: Optional async callable for formal verification.
            Should accept (premises: list[str], conclusion: str) and return
            a dict with at least {"proved": bool}. When provided and a
            constraint pair is formalizable, this is used instead of LLM.

    Returns:
        FilterResult with survivors and elimination log.
    """
    elimination_log: list[EliminationRecord] = []

    # --- Stage A: Constraint Check ---
    # --- Stage A: Constraint Check ---
    async def _check_constraint(h: Hypothesis) -> None:
        if h.eliminated:
            return
        try:
            violated = False
            detail = ""

            # Try formal prover first if available and constraint looks formalizable
            if prover_call and known_constraints:
                for constraint in known_constraints:
                    if _is_formalizable(constraint, h.d3_invariant):
                        violated, detail = await _check_constraint_formal(
                            prover_call, h, known_constraints
                        )
                        if violated:
                            break

            # Fallback to LLM for non-formalizable or if prover unavailable
            if not violated:
                violated, detail = await _check_constraint_llm(
                    llm_call, h, known_constraints or []
                )

            if violated:
                h.eliminated = True
                h.elimination_reason = "quarantined"
                h.elimination_detail = detail
                elimination_log.append(EliminationRecord(
                    hypothesis_id=h.id,
                    hypothesis_text=h.text,
                    reason="quarantined",
                    detail=detail,
                ))
                logger.info("Quarantined %s: %s", h.id, detail)
        except Exception as e:
            logger.error("Constraint check failed for %s: %s", h.id, e)

    await asyncio.gather(*[_check_constraint(h) for h in hypotheses])

    # --- Stage B: Lakatosian Cut ---
    LAKATOS_PROMPT = """Hypothesis: {hypothesis}
Mechanism: {mechanism}
Invariant: {invariant}

Is this hypothesis a DEGENERATING research program? Signs:
- It requires ad hoc defensive assumptions to survive counter-evidence
- It is non-falsifiable (no observation could disprove it)
- It explains everything but predicts nothing new

Respond in JSON:
{{
  "degenerating": true_or_false,
  "reasoning": "brief explanation"
}}"""

    async def _check_lakatos(h: Hypothesis) -> None:
        if h.eliminated:
            return
        try:
            prompt = LAKATOS_PROMPT.format(
                hypothesis=h.text,
                mechanism=h.d2_mechanism,
                invariant=h.d3_invariant,
            )
            raw = await llm_call(prompt)
            parsed = _parse_json_response(raw)

            if parsed.get("degenerating", False):
                h.eliminated = True
                h.elimination_reason = "degenerating"
                h.elimination_detail = parsed.get("reasoning", "Non-falsifiable or ad hoc")
                elimination_log.append(EliminationRecord(
                    hypothesis_id=h.id,
                    hypothesis_text=h.text,
                    reason="degenerating",
                    detail=h.elimination_detail,
                ))
                logger.info("Lakatos cut %s: %s", h.id, h.elimination_detail)
        except Exception as e:
            logger.error("Lakatos check failed for %s: %s", h.id, e)

    await asyncio.gather(*[_check_lakatos(h) for h in hypotheses])

    # --- Stage C: Bayesian Collider Test ---
    # Design note: asymmetric — mechanisms explain away narratives, not reverse.
    # When social dynamics ARE the mechanism, the mechanism hypothesis should
    # encode that directly. This is a deliberate epistemic stance: the filter
    # is mechanistic-explanation-first.
    surviving = [h for h in hypotheses if not h.eliminated]
    mechanisms = [h for h in surviving if h.h_type == HypothesisType.MECHANISM]
    narratives = [h for h in surviving if h.h_type == HypothesisType.NARRATIVE]

    if mechanisms and narratives:
        STRONGEST_MECH_PROMPT = """Surface symptom: {symptom}

Candidate mechanisms:
{mechanisms}

Which mechanism has the strongest explanatory power? Consider:
- Does it directly explain the symptom?
- Is it falsifiable?
- Does it have the most evidence?

Respond in JSON:
{{
  "strongest_id": "the id of the strongest mechanism",
  "reasoning": "why this mechanism is strongest"
}}"""

        try:
            mech_list = "\n".join(
                f"[{m.id}] {m.text}\n  Mechanism: {m.d2_mechanism}"
                for m in mechanisms
            )
            prompt = STRONGEST_MECH_PROMPT.format(
                symptom=surface_symptom,
                mechanisms=mech_list,
            )
            raw = await llm_call(prompt)
            parsed = _parse_json_response(raw)
            strongest_id = parsed.get("strongest_id", "")

            if strongest_id:
                EXPLAIN_AWAY_PROMPT = """Surface symptom: {symptom}

Strongest mechanism: {strong_mechanism}

Competing narratives:
{narratives}

For each narrative: does the strongest mechanism EXPLAIN AWAY this narrative?
That is, if the mechanism is true, does the narrative become unnecessary or
much less likely? Respond in JSON:
{{
  "results": [
    {{
      "narrative_id": "id",
      "explained_away": true_or_false,
      "reasoning": "how the mechanism explains away this narrative, or why it doesn't"
    }}
  ]
}}"""

                strongest_mech = next(
                    (m for m in mechanisms if m.id == strongest_id), None
                )
                if strongest_mech:
                    narr_list = "\n".join(
                        f"[{n.id}] {n.text}" for n in narratives
                    )
                    prompt = EXPLAIN_AWAY_PROMPT.format(
                        symptom=surface_symptom,
                        strong_mechanism=strongest_mech.text,
                        narratives=narr_list,
                    )
                    raw = await llm_call(prompt)
                    ea_result = _parse_json_response(raw)

                    for item in ea_result.get("results", []):
                        if item.get("explained_away", False):
                            narr_id = item["narrative_id"]
                            for h in narratives:
                                if h.id == narr_id and not h.eliminated:
                                    h.eliminated = True
                                    h.elimination_reason = "explained_away"
                                    h.elimination_detail = (
                                        f"Explained away by mechanism [{strongest_id}]: "
                                        f"{item.get('reasoning', '')}"
                                    )
                                    elimination_log.append(EliminationRecord(
                                        hypothesis_id=h.id,
                                        hypothesis_text=h.text,
                                        reason="explained_away",
                                        detail=h.elimination_detail,
                                    ))
                                    logger.info(
                                        "Explained away %s by %s",
                                        h.id, strongest_id,
                                    )
        except Exception as e:
            logger.error("Bayesian collider test failed: %s", e)

    surviving = [h for h in hypotheses if not h.eliminated]
    strongest = next(
        (h for h in surviving if h.h_type == HypothesisType.MECHANISM),
        None,
    )

    return FilterResult(
        surface_symptom=surface_symptom,
        all_hypotheses=hypotheses,
        surviving_hypotheses=surviving,
        elimination_log=elimination_log,
        strongest_mechanism=strongest,
    )


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

async def synthesize_truth(
    llm_call: Any,
    filter_result: FilterResult,
) -> dict[str, Any]:
    """Compress surviving hypotheses into an actionable truth.

    Confidence is derived from the survival rate (survivors / total), not
    from the synthesis model's self-report. This is a structural signal:
    the more hypotheses survived the filter, the more robust the conclusion.

    Args:
        llm_call: Async callable(prompt: str) -> str.
        filter_result: Output from apply_via_negativa.

    Returns:
        Dict with actionable_truth, confidence (survival-rate based), and next_steps.
    """
    total = len(filter_result.all_hypotheses)
    survived = len(filter_result.surviving_hypotheses)
    survival_rate = survived / total if total > 0 else 0.0

    SYNTHESIS_PROMPT = """Surface symptom: {symptom}

Surviving hypotheses after Via Negativa filtering ({survived}/{total} survived):
{survivors}

Elimination log:
{elimination_log}

Synthesize the actionable truth. What should actually be done? What is the
most robust course of action given what survived the filter?

Respond in JSON:
{{
  "actionable_truth": "one clear sentence — what is actually true and actionable",
  "next_steps": ["step 1", "step 2", "step 3"],
  "remaining_uncertainties": ["uncertainty 1", "uncertainty 2"]
}}"""

    survivors_text = "\n".join(
        f"[{h.id}] ({h.h_type.value}) {h.text}\n  Mechanism: {h.d2_mechanism}"
        for h in filter_result.surviving_hypotheses
    ) or "No hypotheses survived the filter."

    log_text = "\n".join(
        f"- [{r.reason}] {r.hypothesis_text}: {r.detail}"
        for r in filter_result.elimination_log
    ) or "No eliminations."

    try:
        prompt = SYNTHESIS_PROMPT.format(
            symptom=filter_result.surface_symptom,
            survived=survived,
            total=total,
            survivors=survivors_text,
            elimination_log=log_text,
        )
        raw = await llm_call(prompt)
        parsed = _parse_json_response(raw)
        return {
            "actionable_truth": parsed.get("actionable_truth", ""),
            "confidence": round(survival_rate, 2),
            "next_steps": parsed.get("next_steps", []),
            "remaining_uncertainties": parsed.get("remaining_uncertainties", []),
        }
    except Exception as e:
        logger.error("Synthesis failed: %s", e)
        return {
            "actionable_truth": f"[Synthesis failed: {e}]",
            "confidence": round(survival_rate, 2),
            "next_steps": [],
            "remaining_uncertainties": ["synthesis failed"],
        }
