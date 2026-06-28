"""
LLM client — async severity explanation via LiteLLM + Langfuse tracing.

Design:
  - Calls Ollama (or any OpenAI-compatible endpoint) through `litellm.acompletion`.
  - All errors, timeouts, and "Ollama not running" cases return `None` — the
    caller treats None as "no explanation available" and proceeds normally.
  - Langfuse tracing is initialised once at module level; spans are created per call.
    If Langfuse keys are missing, the Langfuse client is a no-op.

Public API:
    from worker.llm.client import explain_severity

    explanation = await explain_severity(score=78, factors=factors, context={...})
    # explanation is str | None
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from worker.config import worker_settings

if TYPE_CHECKING:
    from worker.severity.engine import SeverityFactors

logger = structlog.get_logger(__name__)

_EXPLAIN_TIMEOUT_S = 30  # graceful skip if Ollama takes longer than this

_SYSTEM_PROMPT = """You are a cloud security analyst. Given a severity score and the
contributing factors for an exposed cloud secret, write a concise (2–3 sentence)
explanation of why the score is what it is and what the primary risk driver is.
Be specific, avoid jargon where possible, and focus on actionable context."""

_USER_TEMPLATE = """
Severity score: {score}/100  (bucket: {bucket})

Factors:
- Scope: {resource_count} reachable AWS resources; high-privilege resources: {has_high_priv}
- Environment: {environment} (factor={env_factor:.2f})
- Exposure status: {exposure_status} (factor={exposure_factor:.2f})
- Secret type: {secret_type}

Additional context: {context}

Explain the severity in 2–3 sentences.
""".strip()


def _make_langfuse_client():
    """Return a Langfuse client or a no-op stub if keys are absent."""
    if not worker_settings.langfuse_public_key or not worker_settings.langfuse_secret_key:
        return None
    try:
        from langfuse import Langfuse
        return Langfuse(
            public_key=worker_settings.langfuse_public_key,
            secret_key=worker_settings.langfuse_secret_key,
            host=worker_settings.langfuse_host,
        )
    except Exception as exc:
        logger.warning("langfuse.init_failed", error=str(exc))
        return None


_langfuse = _make_langfuse_client()


async def explain_severity(
    score: int,
    bucket: str,
    factors: "SeverityFactors",
    context: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> str | None:
    """
    Generate an LLM explanation for a severity result.

    Returns a plain-text explanation string, or None if the LLM is unavailable,
    times out, or returns an error.  Always safe to ignore.
    """
    try:
        return await asyncio.wait_for(
            _call_llm(score=score, bucket=bucket, factors=factors, context=context, trace_id=trace_id),
            timeout=_EXPLAIN_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning("llm.explain_severity.timeout", score=score)
        return None
    except Exception as exc:
        logger.warning("llm.explain_severity.error", score=score, error=str(exc))
        return None


async def _call_llm(
    *,
    score: int,
    bucket: str,
    factors: "SeverityFactors",
    context: dict[str, Any] | None,
    trace_id: str | None,
) -> str | None:
    import litellm

    model = worker_settings.litellm_model
    api_base = worker_settings.ollama_base_url if "ollama/" in model else None

    user_msg = _USER_TEMPLATE.format(
        score=score,
        bucket=bucket,
        resource_count=factors.resource_count,
        has_high_priv=factors.has_high_priv,
        environment=factors.environment,
        env_factor=factors.env_factor,
        exposure_status=factors.exposure_status,
        exposure_factor=factors.exposure_factor,
        secret_type=factors.secret_type,
        context=str(context or {}),
    )

    span = None
    if _langfuse and trace_id:
        try:
            trace = _langfuse.trace(id=trace_id)
            span = trace.span(name="explain_severity", input={"score": score, "bucket": bucket})
        except Exception:
            pass

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 200,
        "temperature": 0.3,
    }
    if api_base:
        kwargs["api_base"] = api_base
    if worker_settings.litellm_api_key:
        kwargs["api_key"] = worker_settings.litellm_api_key

    resp = await litellm.acompletion(**kwargs)
    text = resp.choices[0].message.content or ""

    if span:
        try:
            span.end(output={"text": text})
        except Exception:
            pass

    logger.info("llm.explain_severity.ok", model=model, score=score, length=len(text))
    return text.strip() or None
