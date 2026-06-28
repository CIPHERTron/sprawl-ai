"""
Severity node — deterministic score + optional LLM explanation.

Reads:
    state["context"]  — environment, exposure_status, secret_type
    state["graph"]    — resource_count, high_priv_count

Writes:
    state["severity"] — SeverityResult (score, bucket, factors, explanation)
"""
from __future__ import annotations

import structlog

from worker.agents.guardrails import guardrail
from worker.agents.state import (
    BlastRadiusGraph,
    InvestigationState,
    SecretContext,
    SeverityResult,
)
from worker.llm.client import explain_severity
from worker.severity.engine import SeverityEngine

logger = structlog.get_logger(__name__)

_engine = SeverityEngine()


@guardrail(timeout_s=45, node_name="severity")
async def severity_node(state: InvestigationState) -> InvestigationState:
    """
    Computes the deterministic severity score, then optionally requests
    an LLM explanation.  LLM call never blocks completion.
    """
    context: SecretContext | None = state.get("context")
    graph: BlastRadiusGraph | None = state.get("graph")

    if context is None:
        result = SeverityResult(score=0, bucket="low")
        return {**state, "severity": result}  # type: ignore[return-value]

    resource_count   = graph.resource_count if graph else 0
    high_priv_count  = graph.high_priv_count if graph else 0

    det_result = _engine.score(
        resource_count=resource_count,
        high_privilege_resources=high_priv_count,
        environment=context.environment,
        exposure_status=context.exposure_status,
        secret_type=context.secret_type,
    )

    # ── Optional LLM explanation ───────────────────────────────────────────────
    explanation: str | None = None
    try:
        explanation = await explain_severity(
            score=det_result.score,
            bucket=det_result.bucket,
            factors=det_result.factors,
            context={
                "principal_arn": context.principal_arn,
                "store_present": context.store_present,
                "last_used_date": context.last_used_date,
            },
            trace_id=state.get("trace_id"),
        )
    except Exception as exc:
        logger.debug("severity.llm_skip", error=str(exc))

    result = SeverityResult(
        score=det_result.score,
        bucket=det_result.bucket,
        factors=det_result.factors,
        explanation=explanation,
    )

    logger.info(
        "severity.done",
        secret_id=str(context.secret_id),
        score=result.score,
        bucket=result.bucket,
        has_explanation=explanation is not None,
    )

    events = list(state.get("events") or [])
    events.append({
        "type": "node.complete",
        "node": "severity",
        "score": result.score,
        "bucket": result.bucket,
    })

    return {**state, "severity": result, "events": events}  # type: ignore[return-value]
