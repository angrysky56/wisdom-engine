# Wisdom Engine

An Model Context Protocol (MCP) server for epistemic filtering via **Via Negativa** — hypothesis generation, subtraction, and truth synthesis.

The Wisdom Engine implements an advanced, agent-centric pipeline that filters out false narratives and ad-hoc assumptions to discover structural mechanisms, logical limits, and actionable truths.

---

## Architecture Overview

```mermaid
graph TD
    A[Surface Observation / Claim] --> B[generate_hypotheses]
    B --> B1[Mechanism Hypothesis]
    B --> B2[Narrative Hypothesis]
    B --> B3[Constraint Hypothesis]
    
    B1 & B2 & B3 --> C[apply_via_negativa]
    
    subgraph apply_via_negativa [Via Negativa Filter]
        C --> D[Stage A: Constraint Checks]
        D -->|Formal Prove / LLM| E[Stage B: Lakatosian Cuts]
        E -->|Falsifiability Check| F[Stage C: Bayesian Collider]
        F -->|Explain-Away Narratives| G[Surviving Hypotheses]
    end
    
    G --> H[synthesize_truth]
    H --> I[Actionable Truth + Next Steps]
```

### How LLM Calls Work

The engine uses **MCP sampling** — it borrows the connected client's LLM through the MCP protocol. When a tool needs to reason (e.g., check if a hypothesis violates a constraint), the server sends a `sampling/createMessage` request back to the client, which completes it using its own LLM. No API keys or external modules are needed.

> **Requirement:** The MCP client must support the `sampling` capability.

### 1. Hypothesis Generation (`generate_hypotheses`)
Given a surface symptom, the engine fans out to three distinct perspectives:
- **Mechanism (How does it work?):** Physical, technical, or systemic causes.
- **Narrative (Why do we think it works?):** Social, cognitive, or psychological stories that make it seem true.
- **Constraint (What are the hard limits?):** Boundary conditions, resource bounds, or logical limits.

Each hypothesis is automatically mapped at three recursion depths:
- **d1 (Symptom):** The surface-level observation.
- **d2 (Mechanism):** The underlying causal explanation.
- **d3 (Invariant):** The fundamental law or boundary condition supporting it.

### 2. Subtraction Engine (`apply_via_negativa`)
The core Via Negativa filter eliminates weak hypotheses through three stages:
- **Stage A (Constraint checks):** Checks if the hypothesis violates known invariants.
  - *Dual Path:* Formalizable invariants (math/logic) are verified using a formal solver via `mcp-logic`, while non-formalizable invariants fallback to LLM judgment.
- **Stage B (Lakatosian cuts):** Cuts degenerating research programs that require ad-hoc defensive assertions to survive or are non-falsifiable.
- **Stage C (Bayesian collider):** Stronger mechanistic explanations explain away competing narratives that share the same symptom.

### 3. Truth Synthesis (`synthesize_truth`)
Compresses surviving hypotheses into an actionable path forward.
- **Structural Confidence:** Confidence is mathematically derived from the hypothesis survival rate ($\text{survivors} / \text{total}$), rather than the LLM's self-assessment.

---

## MCP Tools Exposed

### 1. `generate_hypotheses`
Proposes three competing hypotheses from mechanism, narrative, and constraint perspectives.
- **Arguments:**
  - `surface_symptom` (string, required): The observation or problem.
  - `context` (string, optional): Supporting context from research.

### 2. `apply_via_negativa`
Filters hypotheses through constraint checking, Lakatosian cuts, and Bayesian collider checks.
- **Arguments:**
  - `surface_symptom` (string, required): The original observation.
  - `hypotheses` (array, required): List of hypothesis dicts (output from `generate_hypotheses`).
  - `known_constraints` (array, optional): Physical or domain constraints.

### 3. `synthesize_truth`
Synthesizes the surviving hypotheses into a clear, actionable sentence.
- **Arguments:**
  - `filter_result` (dict, required): Output from `apply_via_negativa`.

---

## Installation & Setup

Ensure you have [uv](https://github.com/astral-sh/uv) installed.

### Run Locally
To run the server in development mode, start it via `stdio` transport:
```bash
uv run wisdom-engine
```

### Run Tests
The codebase includes a fully-featured async test suite.
```bash
uv run pytest
```

---

## MCP Integration Configuration

To use the Wisdom Engine with an MCP-compatible client, add the server configuration to your client's config file.

### Example Configuration
See `mcp_config_example.json` in the root of this project:
```json
{
  "mcpServers": {
    "wisdom-engine": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/wisdom-engine",
        "run",
        "wisdom-engine"
      ]
    }
  }
}
```

Replace `/path/to/wisdom-engine` with the absolute path to your local project directory.
