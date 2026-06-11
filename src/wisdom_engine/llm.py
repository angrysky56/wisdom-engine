"""LLM backend chain for the Wisdom Engine.

Resolution order (first available wins):
  1. MCP sampling — borrow the connected client's LLM, but ONLY if the
     client declared the ``sampling`` capability during initialization.
  2. OpenRouter — direct API call, enabled when OPENROUTER_API_KEY is set.
  3. Ollama — local model, enabled when the Ollama server is reachable.

If no backend is available, ``resolve_llm_call`` raises
``LLMUnavailableError`` with an actionable message. The engine never
silently proceeds without an LLM.

Environment variables:
  OPENROUTER_API_KEY    — enables the OpenRouter backend
  OPENROUTER_MODEL      — model slug (default: "openrouter/auto")
  OPENROUTER_BASE_URL   — API base (default: "https://openrouter.ai/api/v1")
  OLLAMA_HOST           — Ollama server (default: "http://localhost:11434")
  OLLAMA_MODEL          — model name (default: first locally installed model)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable

import httpx
from mcp import types
from mcp.server.fastmcp import Context
from mcp.types import SamplingMessage, TextContent

logger = logging.getLogger("wisdom_engine.llm")

# Async callable: prompt in, completion text out.
LLMCall = Callable[[str], Awaitable[str]]

DEFAULT_MAX_TOKENS = 4096
HTTP_TIMEOUT_S = 120.0
PROBE_TIMEOUT_S = 2.0


class LLMUnavailableError(RuntimeError):
    """No LLM backend is available — the pipeline cannot run."""


class LLMCallError(RuntimeError):
    """A backend was selected but an individual call failed."""


# ---------------------------------------------------------------------------
# Backend 1: MCP sampling
# ---------------------------------------------------------------------------

def sampling_supported(ctx: Context | None) -> bool:
    """True if a client is connected AND declared the sampling capability."""
    if ctx is None:
        return False
    try:
        return ctx.session.check_client_capability(
            types.ClientCapabilities(sampling=types.SamplingCapability())
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Capability check failed: %s", e)
        return False


def make_sampling_call(ctx: Context) -> LLMCall:
    """LLM call via MCP sampling (client's own model)."""

    async def llm_call(prompt: str) -> str:
        try:
            result = await ctx.session.create_message(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=TextContent(type="text", text=prompt),
                    )
                ],
                max_tokens=DEFAULT_MAX_TOKENS,
            )
        except Exception as e:
            raise LLMCallError(f"MCP sampling request failed: {e}") from e
        if isinstance(result.content, TextContent):
            return result.content.text
        raise LLMCallError(
            f"MCP sampling returned non-text content: {type(result.content).__name__}"
        )

    return llm_call


# ---------------------------------------------------------------------------
# Backend 2: OpenRouter
# ---------------------------------------------------------------------------

def openrouter_configured() -> bool:
    """True if an OpenRouter API key is present in the environment."""
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def make_openrouter_call() -> LLMCall:
    """LLM call via the OpenRouter chat completions API."""
    api_key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("OPENROUTER_MODEL", "openrouter/auto")
    base_url = os.environ.get(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )

    async def llm_call(prompt: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": DEFAULT_MAX_TOKENS,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise LLMCallError(
                f"OpenRouter HTTP {e.response.status_code}: {e.response.text[:300]}"
            ) from e
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise LLMCallError(f"OpenRouter call failed: {e}") from e

    return llm_call


# ---------------------------------------------------------------------------
# Backend 3: Ollama (local)
# ---------------------------------------------------------------------------

def _ollama_host() -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host.rstrip("/")


async def ollama_available() -> str | None:
    """Probe the Ollama server. Returns the model name to use, or None.

    Uses OLLAMA_MODEL if set; otherwise the first locally installed model.
    """
    host = _ollama_host()
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            resp = await client.get(f"{host}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return None

    preferred = os.environ.get("OLLAMA_MODEL")
    if preferred:
        return preferred
    if models:
        return models[0]["name"]
    return None


def make_ollama_call(model: str) -> LLMCall:
    """LLM call via a local Ollama server."""
    host = _ollama_host()

    async def llm_call(prompt: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{host}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            return data["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise LLMCallError(f"Ollama call failed ({model}): {e}") from e

    return llm_call


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

async def resolve_llm_call(ctx: Context | None) -> tuple[LLMCall, str]:
    """Pick the first available LLM backend.

    Returns:
        (llm_call, backend_name) where backend_name is one of
        "mcp-sampling", "openrouter", or "ollama/<model>".

    Raises:
        LLMUnavailableError: when no backend is available.
    """
    if sampling_supported(ctx):
        logger.info("LLM backend: MCP sampling (client capability declared)")
        return make_sampling_call(ctx), "mcp-sampling"

    if openrouter_configured():
        model = os.environ.get("OPENROUTER_MODEL", "openrouter/auto")
        logger.info("LLM backend: OpenRouter (%s)", model)
        return make_openrouter_call(), f"openrouter/{model}"

    ollama_model = await ollama_available()
    if ollama_model:
        logger.info("LLM backend: Ollama (%s)", ollama_model)
        return make_ollama_call(ollama_model), f"ollama/{ollama_model}"

    raise LLMUnavailableError(
        "No LLM backend available. The connected MCP client did not declare "
        "the 'sampling' capability, OPENROUTER_API_KEY is not set, and no "
        "Ollama server was reachable at "
        f"{_ollama_host()}. Set OPENROUTER_API_KEY or start Ollama "
        "(and optionally set OLLAMA_MODEL) in the server's environment."
    )
