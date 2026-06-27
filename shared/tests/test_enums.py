"""Smoke tests — enum values match the Postgres CREATE TYPE strings in Phase 8."""
from shared.models.enums import (
    RotationStatus,
    ROTATION_TERMINAL_STATUSES,
    StepKind,
    StepStatus,
    InvestigationStatus,
)


def test_plan_failed_is_terminal():
    assert RotationStatus.PLAN_FAILED in ROTATION_TERMINAL_STATUSES


def test_abandoned_is_terminal():
    assert RotationStatus.ABANDONED in ROTATION_TERMINAL_STATUSES


def test_needs_replan_is_not_terminal():
    """needs_replan keeps the rotation lock active until re-planned or reaped."""
    assert RotationStatus.NEEDS_REPLAN not in ROTATION_TERMINAL_STATUSES


def test_all_step_kinds_defined():
    kinds = {s.value for s in StepKind}
    assert kinds == {"provision", "distribute", "verify", "revoke"}


def test_investigation_status_values():
    values = {s.value for s in InvestigationStatus}
    assert values == {"running", "complete", "error"}
