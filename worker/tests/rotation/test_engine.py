"""
Safety-invariant tests for the rotation engine (M5 — §5.3).

These tests exercise the pure logic of the rotation system without a
real database or Redis. They use:
  - SandboxStoreConnector / SandboxCloudConnector  (from worker/rotation/sandbox.py)
  - execute_step / compensate_step                 (from worker/rotation/steps.py)
  - verify_gate / coverage_gate                    (from worker/rotation/gate.py)
  - GateBlockedError, LockNotAcquiredError         (state / exception types)

Tests are grouped by invariant:
  T1  verify_gate blocks revoke when verify steps are incomplete
  T2  coverage_gate blocks revoke when unknown_consumers > 0 and not confirmed
  T3  coverage_gate passes when unknown_consumers == 0
  T4  sandbox provision succeeds and returns a new_secret_ref
  T5  sandbox provision failure → StepResult.status == 'failed'
  T6  sandbox revoke failure → StepResult.status == 'failed'
  T7  compensate_step reverses provision (delete_new_key action)
  T8  idempotency — executing a 'done' step returns the same done result
      (tests the engine's _find_next_step skips terminal steps)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.rotation.gate import GateBlockedError, coverage_gate, verify_gate
from worker.rotation.sandbox import (
    SandboxCloudConnector,
    SandboxConnectorError,
    SandboxStoreConnector,
    build_sandbox_connectors,
)
from worker.rotation.steps import StepResult, compensate_step, execute_step
from worker.rotation.engine import _find_next_step


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def connectors():
    return build_sandbox_connectors()


@pytest.fixture()
def base_rotation():
    return {
        "id": "rot-0001",
        "workspace_id": "ws-0001",
        "secret_id": "sec-0001",
        "status": "provisioning",
        "plan": {"store_path": "rotation/rot-0001/new_credential"},
        "coverage": {"known_consumers": 2, "unknown_consumers": 0},
        "new_secret_ref": None,
    }


def _make_step(idx: int, kind: str, status: str = "pending", req_confirm: bool = False) -> dict:
    compensations = {
        "provision":  {"action": "delete_new_key"},
        "distribute": {"action": "restore_old_secret_value"},
        "revoke":     {"action": "reactivate_old_key"},
    }
    targets = {
        "provision":  {"type": "aws_iam", "account": "123", "username": "ci-deploy"},
        "distribute": {"type": "sandbox", "consumer": "acme/frontend"},
        "verify":     {"type": "sandbox", "check": "readability"},
        "revoke":     {"type": "aws_iam", "account": "123", "key_id": "AKIAOLD"},
    }
    return {
        "id": f"step-{idx:03d}",
        "idx": idx,
        "kind": kind,
        "target": targets.get(kind, {}),
        "compensation": compensations.get(kind),
        "requires_confirmation": req_confirm,
        "status": status,
        "error": None,
    }


# ── T1: verify_gate blocks revoke when any verify step is not done ─────────────

@pytest.mark.asyncio
async def test_verify_gate_blocks_when_verify_incomplete():
    """T1 — verify_gate raises GateBlockedError if a verify step is not done."""
    mock_db = AsyncMock()
    # Simulate DB returning 1 incomplete verify step
    count_row = MagicMock()
    count_row.scalar_one.return_value = 1
    mock_db.execute.return_value = count_row

    with pytest.raises(GateBlockedError) as exc_info:
        await verify_gate("rot-0001", mock_db)

    assert exc_info.value.reason == "verify_incomplete"
    assert "1 verify step" in exc_info.value.message


@pytest.mark.asyncio
async def test_verify_gate_passes_when_all_verify_done():
    """T1b — verify_gate succeeds when all verify steps are done."""
    mock_db = AsyncMock()
    count_row = MagicMock()
    count_row.scalar_one.return_value = 0  # no incomplete verify steps
    mock_db.execute.return_value = count_row

    # Should not raise
    await verify_gate("rot-0001", mock_db)


# ── T2: coverage_gate blocks when unknown_consumers > 0 and not confirmed ──────

def test_coverage_gate_blocks_unknown_consumers_not_confirmed():
    """T2 — coverage_gate raises if unknown_consumers > 0 and not confirmed."""
    with pytest.raises(GateBlockedError) as exc_info:
        coverage_gate({"unknown_consumers": 1}, revoke_confirmed=False)

    assert exc_info.value.reason == "coverage_incomplete"
    assert "1 consumer" in exc_info.value.message


# ── T3: coverage_gate passes when unknown_consumers == 0 ──────────────────────

def test_coverage_gate_passes_when_all_consumers_known():
    """T3 — coverage_gate passes when all consumers are known."""
    # Should not raise
    coverage_gate({"unknown_consumers": 0}, revoke_confirmed=False)


def test_coverage_gate_passes_when_confirmed_despite_unknowns():
    """T3b — coverage_gate passes even with unknowns if user confirmed."""
    coverage_gate({"unknown_consumers": 3}, revoke_confirmed=True)


# ── T4: sandbox provision succeeds and returns new_secret_ref ─────────────────

def test_sandbox_provision_returns_new_secret_ref(connectors, base_rotation):
    """T4 — provision step creates a credential and returns new_secret_ref."""
    step = _make_step(0, "provision")
    result = execute_step(step, base_rotation, connectors)

    assert result.status == "done"
    assert result.new_secret_ref is not None
    assert "credential_id" in result.new_secret_ref
    assert "access_key_id" in result.new_secret_ref
    assert result.error is None


# ── T5: sandbox provision failure → step failed ───────────────────────────────

def test_sandbox_provision_failure_produces_failed_result(base_rotation):
    """T5 — fail_at='provision' causes execute_step to return failed status."""
    failing_connectors = build_sandbox_connectors(fail_at="provision")
    step = _make_step(0, "provision")

    result = execute_step(step, base_rotation, failing_connectors)

    assert result.status == "failed"
    assert result.error is not None
    assert "Simulated failure" in result.error


# ── T6: sandbox revoke failure → step failed ──────────────────────────────────

def test_sandbox_revoke_failure_produces_failed_result(base_rotation):
    """T6 — fail_at='revoke' causes revoke step to fail."""
    failing_connectors = build_sandbox_connectors(fail_at="revoke")
    step = _make_step(3, "revoke")

    # Add new_secret_ref so revoke has a key to delete
    rotation = {**base_rotation, "new_secret_ref": {"credential_id": "AKIA_NEW"}}

    result = execute_step(step, rotation, failing_connectors)

    assert result.status == "failed"
    assert result.error is not None


# ── T7: compensate_step reverses provision ────────────────────────────────────

def test_compensate_step_provision_succeeds(connectors, base_rotation):
    """T7 — compensate_step with delete_new_key succeeds and returns 'compensated'."""
    step = _make_step(0, "provision", status="done")
    rotation = {
        **base_rotation,
        "new_secret_ref": {"credential_id": "AKIA_SANDBOX_NEW_KEY_0001"},
    }

    result = compensate_step(step, rotation, connectors)

    assert result.status == "compensated"
    assert result.error is None


def test_compensate_step_distribute_succeeds(connectors, base_rotation):
    """T7b — compensate_step with restore_old_secret_value is a no-op in sandbox."""
    step = _make_step(1, "distribute", status="done")

    result = compensate_step(step, base_rotation, connectors)

    assert result.status == "compensated"


# ── T8: _find_next_step skips terminal steps ──────────────────────────────────

def test_find_next_step_skips_done_steps():
    """T8 — idempotency: _find_next_step returns only the first 'pending' step."""
    steps = [
        _make_step(0, "provision", status="done"),
        _make_step(1, "distribute", status="pending"),
        _make_step(2, "verify", status="pending"),
    ]
    next_step = _find_next_step(steps)
    assert next_step is not None
    assert next_step["idx"] == 1
    assert next_step["kind"] == "distribute"


def test_find_next_step_returns_none_when_all_done():
    """T8b — _find_next_step returns None when all steps are terminal."""
    steps = [
        _make_step(0, "provision", status="done"),
        _make_step(1, "distribute", status="done"),
        _make_step(2, "verify", status="done"),
        _make_step(3, "revoke", status="done"),
    ]
    assert _find_next_step(steps) is None


def test_find_next_step_skips_compensated():
    """T8c — compensated steps are not re-run."""
    steps = [
        _make_step(0, "provision", status="compensated"),
        _make_step(1, "distribute", status="failed"),
    ]
    assert _find_next_step(steps) is None  # no 'pending' steps left


# ── Sandbox connector unit tests ───────────────────────────────────────────────

def test_sandbox_store_connector_read_write_cycle():
    """Sandbox store: write then read returns the stored value."""
    from shared.connectors.base import SecretValue
    from shared.refs import StoreRef

    store = SandboxStoreConnector()
    ref = StoreRef(connector_type="vault", connector_id="s1", path="kv/myapp/api-key")
    value = SecretValue(value="my-secret-value")

    version = store.write_new_version(ref, value)
    assert version.id is not None

    read_back = store.read(ref)
    assert read_back.value == "my-secret-value"


def test_sandbox_cloud_connector_enumerate_scope():
    """Sandbox cloud: enumerate_scope returns two fake resources."""
    from shared.refs import PrincipalRef

    cloud = SandboxCloudConnector()
    principal = PrincipalRef(
        provider="aws",
        principal_type="iam_user",
        arn="arn:aws:iam::123456789012:user/ci-deploy",
        account_id="123456789012",
    )
    resources = cloud.enumerate_scope(principal)

    assert len(resources) == 2
    assert all(r.provider == "aws" for r in resources)


def test_sandbox_fail_at_distribute_blocks_distribute():
    """fail_at='distribute' raises SandboxConnectorError on write_new_version."""
    from shared.connectors.base import SecretValue
    from shared.refs import StoreRef

    store = SandboxStoreConnector(fail_at="distribute")
    ref = StoreRef(connector_type="vault", connector_id="s1", path="kv/test")

    with pytest.raises(SandboxConnectorError):
        store.write_new_version(ref, SecretValue(value="new"))


def test_lock_not_acquired_error_is_exception():
    """LockNotAcquiredError is a proper exception subclass."""
    from worker.rotation.lock import LockNotAcquiredError
    with pytest.raises(LockNotAcquiredError):
        raise LockNotAcquiredError("test")
