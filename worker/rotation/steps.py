"""
Rotation step executors — one function per StepKind.

`execute_step` dispatches to `_provision`, `_distribute`, `_verify`, `_revoke`
based on `step["kind"]`.  Each executor:
  - Calls the appropriate connector method (sandbox or real)
  - Returns a StepResult with the new step status
  - Never writes to the DB — the engine does all persistence
  - Does not raise on step failure — wraps errors into StepResult

Secret values (C1): `create_credential` returns material held only in-memory
here. The material is forwarded to the store connector and then discarded.
It is never returned to the caller, never logged, never persisted to Postgres.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from shared.refs import CredentialRef, PrincipalRef, StoreRef

logger = structlog.get_logger(__name__)


@dataclass
class StepResult:
    """Outcome of executing a single rotation step."""
    status: str               # 'done' | 'failed' | 'awaiting_confirmation'
    error: str | None = None
    # Metadata persisted to rotation.new_secret_ref after provision
    new_secret_ref: dict | None = None
    # Metadata to extend the rotation row's coverage
    extra: dict = field(default_factory=dict)


def execute_step(
    step: dict[str, Any],
    rotation: dict[str, Any],
    connectors: dict[str, Any],
) -> StepResult:
    """
    Execute a single rotation step synchronously.

    Args:
        step:       Raw dict from DB — keys: id, kind, target, compensation,
                    requires_confirmation, status, idx
        rotation:   Raw dict from DB — keys: id, secret_id, status, plan,
                    new_secret_ref, coverage, workspace_id
        connectors: {'store': StoreConnector, 'cloud': CloudConnector}

    Returns:
        StepResult — the engine writes this back to the DB.
    """
    kind = step["kind"]
    dispatch = {
        "provision":  _provision,
        "distribute": _distribute,
        "verify":     _verify,
        "revoke":     _revoke,
    }
    fn = dispatch.get(kind)
    if fn is None:
        return StepResult(status="failed", error=f"Unknown step kind: {kind!r}")

    try:
        return fn(step, rotation, connectors)
    except Exception as exc:
        logger.error(
            "rotation.step.error",
            step_idx=step.get("idx"),
            kind=kind,
            error=str(exc),
        )
        return StepResult(status="failed", error=str(exc))


# ── Step implementations ───────────────────────────────────────────────────────

def _provision(
    step: dict,
    rotation: dict,
    connectors: dict,
) -> StepResult:
    """
    Provision a new credential via CloudConnector.create_credential.

    Then immediately write the new value to the store (Vault) so it's available
    for distribute steps. The raw credential material is discarded after the
    store write (C1).

    Sets rotation.new_secret_ref to the store reference for the new version.
    """
    cloud = connectors.get("cloud")
    store = connectors.get("store")

    target = step.get("target") or {}
    principal = PrincipalRef(
        provider="aws",
        principal_type="iam_user",
        arn=f"arn:aws:iam::{target.get('account', '000000000000')}:user/{target.get('username', 'unknown')}",
        account_id=target.get("account", "000000000000"),
    )

    # Create the new credential (material is transient — never persisted)
    material = cloud.create_credential(principal)

    new_secret_ref = None
    if store and rotation.get("plan"):
        plan = rotation["plan"] or {}
        store_path = plan.get("store_path") or f"rotation/{rotation['id']}/new_credential"
        ref = StoreRef(
            connector_type="vault",
            connector_id="sandbox",
            path=store_path,
        )
        from shared.connectors.base import SecretValue
        value = SecretValue(
            value=material.secret_access_key or "",
            metadata={
                "access_key_id": material.access_key_id,
                "credential_id": material.credential_id,
            },
        )
        version = store.write_new_version(ref, value)
        new_secret_ref = {
            "connector_type": "vault",
            "path": store_path,
            "version": version.id,
            "credential_id": material.credential_id,
            "access_key_id": material.access_key_id,
        }

    logger.info(
        "rotation.step.provision.done",
        step_idx=step.get("idx"),
        credential_id=material.credential_id,
    )
    return StepResult(status="done", new_secret_ref=new_secret_ref)


def _distribute(
    step: dict,
    rotation: dict,
    connectors: dict,
) -> StepResult:
    """
    Distribute the new credential to a consumer.

    For sandbox/demo: always succeeds (the SandboxStoreConnector.write_new_version
    already recorded the value in-memory during provision). In real mode this
    would push to k8s/ECS/GitHub Actions/etc.
    """
    target = step.get("target") or {}
    consumer_type = target.get("type", "unknown")

    # For sandbox: no real push needed — connector call is a no-op
    store = connectors.get("store")
    if store and rotation.get("new_secret_ref"):
        ref = rotation["new_secret_ref"]
        store_ref = StoreRef(
            connector_type="vault",
            connector_id="sandbox",
            path=ref.get("path", "sandbox/path"),
        )
        from shared.connectors.base import SecretValue
        _ = store.write_new_version(
            store_ref,
            SecretValue(value="***distributed***"),
        )

    logger.info(
        "rotation.step.distribute.done",
        step_idx=step.get("idx"),
        consumer_type=consumer_type,
    )
    return StepResult(status="done")


def _verify(
    step: dict,
    rotation: dict,
    connectors: dict,
) -> StepResult:
    """
    Verify the new credential is readable/usable.

    Uses StoreConnector.verify_store. For sandbox this always returns success.
    """
    store = connectors.get("store")
    target = step.get("target") or {}

    if store and rotation.get("new_secret_ref"):
        ref_meta = rotation["new_secret_ref"]
        store_ref = StoreRef(
            connector_type="vault",
            connector_id="sandbox",
            path=ref_meta.get("path", "sandbox/path"),
        )
        result = store.verify_store(store_ref)
        if not result.success:
            return StepResult(status="failed", error=result.message)
    else:
        # No store configured — sandbox verify always passes
        logger.debug("rotation.step.verify.sandbox_no_store", step_idx=step.get("idx"))

    logger.info("rotation.step.verify.done", step_idx=step.get("idx"))
    return StepResult(status="done")


def _revoke(
    step: dict,
    rotation: dict,
    connectors: dict,
) -> StepResult:
    """
    Revoke the old credential via CloudConnector.disable_credential then delete.

    This is the final step — runs only after the verify gate has passed.
    Implements disable-then-delete (C5 / §5.3.4).
    """
    cloud = connectors.get("cloud")
    target = step.get("target") or {}

    old_key_id = target.get("key_id", "UNKNOWN_KEY")
    username   = target.get("username", "unknown")
    account    = target.get("account", "000000000000")

    cred_ref = CredentialRef(
        provider="aws",
        credential_type="access_key",
        credential_id=old_key_id,
        metadata={"username": username, "account": account},
    )

    if cloud:
        cloud.disable_credential(cred_ref)   # reversible
        cloud.delete_credential(cred_ref)    # irreversible

    logger.info(
        "rotation.step.revoke.done",
        step_idx=step.get("idx"),
        key_id=old_key_id,
    )
    return StepResult(status="done")


# ── Compensation (rollback) ────────────────────────────────────────────────────

def compensate_step(
    step: dict[str, Any],
    rotation: dict[str, Any],
    connectors: dict[str, Any],
) -> StepResult:
    """
    Run the compensation (undo) for a completed step.

    Called in reverse order on the steps that already ran when a later step fails.
    The compensation action is stored in `step["compensation"]`.
    """
    compensation = step.get("compensation") or {}
    action = compensation.get("action", "")
    kind = step.get("kind", "")

    try:
        if action == "delete_new_key" and kind == "provision":
            cloud = connectors.get("cloud")
            if cloud and rotation.get("new_secret_ref"):
                ref = rotation["new_secret_ref"]
                cred_ref = CredentialRef(
                    provider="aws",
                    credential_type="access_key",
                    credential_id=ref.get("credential_id", ""),
                    metadata={"username": "unknown"},
                )
                cloud.delete_credential(cred_ref)

        elif action == "restore_old_secret_value" and kind == "distribute":
            # For sandbox: no real restore needed
            logger.debug("rotation.compensation.restore_value.sandbox", step_idx=step.get("idx"))

        elif action == "reactivate_old_key" and kind == "revoke":
            # Revoke shouldn't need compensation (it's the last step) but handle gracefully
            logger.debug("rotation.compensation.reactivate.sandbox", step_idx=step.get("idx"))

        else:
            logger.debug(
                "rotation.compensation.noop",
                action=action,
                kind=kind,
                step_idx=step.get("idx"),
            )

        logger.info("rotation.step.compensated", step_idx=step.get("idx"), action=action)
        return StepResult(status="compensated")

    except Exception as exc:
        logger.error(
            "rotation.step.compensation_failed",
            step_idx=step.get("idx"),
            action=action,
            error=str(exc),
        )
        return StepResult(status="failed", error=f"compensation_failed: {exc}")
