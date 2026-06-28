"""
Rotation safety gates (§5.3.2).

Two gates enforce the verify-before-revoke invariant and coverage requirements:

  verify_gate     — raises GateBlockedError if any 'verify' step is not 'done'.
                    Called immediately before executing a 'revoke' step.

  coverage_gate   — raises GateBlockedError if unknown_consumers > 0 and the
                    revoke has not been explicitly confirmed by the user.
                    Called as part of the pre-revoke check sequence.

Both raise GateBlockedError with a machine-readable `reason` so the engine
can set `awaiting_confirmation` status and surface the right message to the UI.
"""
from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


@dataclass
class GateBlockedError(Exception):
    """
    Raised by a gate function when the engine must stop and wait.

    Attributes:
        reason: machine-readable reason code (e.g. 'verify_incomplete')
        message: human-readable description
        rotation_status: what status the engine should set on the Rotation row
    """
    reason: str
    message: str
    rotation_status: str = "awaiting_confirmation"

    def __str__(self) -> str:
        return f"GateBlockedError({self.reason}): {self.message}"


async def verify_gate(rotation_id: str, db: AsyncSession) -> None:
    """
    Invariant: every 'verify' step must be 'done' before any 'revoke' step runs.

    Queries rotation_steps for this rotation and raises GateBlockedError if any
    verify step is not in a terminal-success state.

    Args:
        rotation_id: UUID string of the rotation row.
        db: Active SQLAlchemy async session.

    Raises:
        GateBlockedError: if the gate is not satisfied.
    """
    result = await db.execute(
        text("""
            SELECT COUNT(*) FROM rotation_steps
            WHERE rotation_id = :rid
              AND kind = 'verify'
              AND status != 'done'
        """),
        {"rid": rotation_id},
    )
    incomplete_count = result.scalar_one()

    if incomplete_count > 0:
        logger.warning(
            "gate.verify_gate.blocked",
            rotation_id=rotation_id,
            incomplete_verify_steps=incomplete_count,
        )
        raise GateBlockedError(
            reason="verify_incomplete",
            message=(
                f"{incomplete_count} verify step(s) have not completed. "
                "All verification must pass before revocation."
            ),
            rotation_status="awaiting_confirmation",
        )

    logger.debug("gate.verify_gate.passed", rotation_id=rotation_id)


def coverage_gate(coverage: dict, revoke_confirmed: bool) -> None:
    """
    D12 invariant: if there are unknown consumers, block the revoke gate until
    the user explicitly acknowledges the incomplete coverage.

    This is a synchronous check (no DB needed — coverage is already on the
    Rotation row or passed in from the step context).

    Args:
        coverage: dict with 'unknown_consumers' key (int).
        revoke_confirmed: True if the user has explicitly confirmed the revoke
                          step despite incomplete coverage.

    Raises:
        GateBlockedError: if coverage is incomplete and not confirmed.
    """
    unknown = coverage.get("unknown_consumers", 0)
    if unknown > 0 and not revoke_confirmed:
        logger.warning(
            "gate.coverage_gate.blocked",
            unknown_consumers=unknown,
            revoke_confirmed=revoke_confirmed,
        )
        raise GateBlockedError(
            reason="coverage_incomplete",
            message=(
                f"{unknown} consumer(s) could not be verified. "
                "Explicit confirmation is required before revoking the old credential."
            ),
            rotation_status="awaiting_confirmation",
        )

    logger.debug("gate.coverage_gate.passed", unknown_consumers=unknown, confirmed=revoke_confirmed)
