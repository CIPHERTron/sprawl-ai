"""
Guardrails decorator for LangGraph agent nodes.

Wraps a node function with:
  - Asyncio timeout enforcement
  - Tenacity retry on transient errors (ConnectionError, TimeoutError, OSError)
  - Structured error capture into state["errors"] instead of raising
  - Langfuse span (best-effort — skipped if Langfuse not configured)

Usage:
    @guardrail(timeout_s=30, node_name="investigator")
    async def investigator_node(state: InvestigationState) -> InvestigationState:
        ...
"""
from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, Coroutine

import structlog
import tenacity

from worker.agents.state import AgentError, InvestigationState

logger = structlog.get_logger(__name__)

# Transient errors that warrant a retry
_TRANSIENT = (ConnectionError, TimeoutError, OSError)


def guardrail(
    timeout_s: float = 60.0,
    node_name: str = "",
    max_attempts: int = 2,
) -> Callable:
    """
    Decorator factory for LangGraph node functions.

    Args:
        timeout_s: Seconds before the node is aborted (state is returned with error).
        node_name: Human-readable name for logging / Langfuse span.
        max_attempts: Number of retry attempts on transient errors.
    """
    def decorator(fn: Callable[..., Coroutine]) -> Callable:
        name = node_name or fn.__name__

        @functools.wraps(fn)
        async def wrapper(state: InvestigationState, *args: Any, **kwargs: Any) -> InvestigationState:
            span = _start_span(state, name)
            try:
                result = await asyncio.wait_for(
                    _with_retry(fn, state, *args, **kwargs, max_attempts=max_attempts),
                    timeout=timeout_s,
                )
                _end_span(span, success=True)
                return result

            except asyncio.TimeoutError:
                logger.warning("guardrail.timeout", node=name, timeout_s=timeout_s)
                _end_span(span, success=False, error=f"timeout after {timeout_s}s")
                return _append_error(state, name, f"node timed out after {timeout_s}s", recoverable=True)

            except Exception as exc:
                logger.error("guardrail.unhandled_error", node=name, error=str(exc))
                _end_span(span, success=False, error=str(exc))
                return _append_error(state, name, str(exc), recoverable=False)

        return wrapper
    return decorator


async def _with_retry(fn, state, *args, max_attempts: int, **kwargs):
    """Run *fn* with exponential-backoff retry on transient errors."""
    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(_TRANSIENT),
        stop=tenacity.stop_after_attempt(max_attempts),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _inner():
        return await fn(state, *args, **kwargs)

    return await _inner()


def _append_error(
    state: InvestigationState,
    node: str,
    message: str,
    recoverable: bool,
) -> InvestigationState:
    errors = list(state.get("errors") or [])
    errors.append(AgentError(node=node, message=message, recoverable=recoverable))
    return {**state, "errors": errors}  # type: ignore[return-value]


def _start_span(state: InvestigationState, name: str):
    """Create a Langfuse span; return it or None if Langfuse unavailable."""
    trace_id = state.get("trace_id")
    if not trace_id:
        return None
    try:
        from worker.config import worker_settings
        if not worker_settings.langfuse_public_key:
            return None
        from langfuse import Langfuse
        lf = Langfuse(
            public_key=worker_settings.langfuse_public_key,
            secret_key=worker_settings.langfuse_secret_key,
            host=worker_settings.langfuse_host,
        )
        trace = lf.trace(id=trace_id)
        return trace.span(
            name=name,
            input={
                "secret_id": state.get("secret_id"),
                "investigation_id": state.get("investigation_id"),
            },
        )
    except Exception:
        return None


def _end_span(span, success: bool, error: str | None = None) -> None:
    if span is None:
        return
    try:
        output = {"success": success}
        if error:
            output["error"] = error
        span.end(output=output)
    except Exception:
        pass
