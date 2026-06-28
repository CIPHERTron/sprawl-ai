"""
Triage node — cheap severity heuristic from exposure status + secret type.

No connector calls.  Decides whether full investigation is worthwhile:
  - routing = "skip"        → low severity (< 20); graph ends here
  - routing = "investigate" → everything else

The triage_score is a rough pre-investigation estimate, not the final score.
"""
from __future__ import annotations

import structlog

from worker.agents.guardrails import guardrail
from worker.agents.state import InvestigationState

logger = structlog.get_logger(__name__)

# Quick lookup: exposure_status → pre-score contribution
# DB enum: unknown | live_inferred | public_leak | inactive
_EXPOSURE_SCORE: dict[str, int] = {
    "public_leak":   90,
    "live_inferred": 60,
    "inactive":      10,
    "unknown":       30,
    # Aliases
    "confirmed": 70,
    "suspected": 40,
}

# Secret types that always trigger full investigation regardless of score
_ALWAYS_INVESTIGATE = frozenset({
    "aws_access_key",
    "iam_access_key",
    "database_url",
    "database",
    "private_key",
    "github_token",
})

_SKIP_THRESHOLD = 20


@guardrail(timeout_s=10, node_name="triage")
async def triage_node(state: InvestigationState) -> InvestigationState:
    """
    Sets:
        state["triage_score"]  — quick integer score 0-100
        state["routing"]       — "investigate" | "skip"
    """
    context = state.get("context")
    if context is None:
        # Should not happen in production; ingest always runs first
        return {**state, "triage_score": 50, "routing": "investigate"}  # type: ignore[return-value]

    exposure = context.exposure_status.lower()
    secret_type = context.secret_type.lower()

    score = _EXPOSURE_SCORE.get(exposure, 30)

    # High-value secret types bump score
    if secret_type in _ALWAYS_INVESTIGATE:
        score = max(score, 55)

    # Prod environment bumps score (env enum values: prod | staging | dev | unknown)
    if context.environment.lower() in ("prod", "production"):
        score = min(100, score + 20)

    routing: str = "investigate" if (score >= _SKIP_THRESHOLD or secret_type in _ALWAYS_INVESTIGATE) else "skip"

    logger.info(
        "triage.done",
        secret_id=str(context.secret_id),
        triage_score=score,
        routing=routing,
        exposure=exposure,
        secret_type=secret_type,
    )

    events = list(state.get("events") or [])
    events.append({"type": "node.complete", "node": "triage", "routing": routing, "score": score})

    return {**state, "triage_score": score, "routing": routing, "events": events}  # type: ignore[return-value]
