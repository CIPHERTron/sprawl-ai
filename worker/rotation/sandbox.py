"""
In-process sandbox connectors for demo mode and testing.

Both implement the real connector protocols (shared/connectors/base.py) with
no external calls. A `fail_at` parameter lets tests / the simulate-failure
endpoint inject a controlled failure at a specific step kind.

Usage:
    store = SandboxStoreConnector()
    cloud = SandboxCloudConnector(fail_at="revoke")   # will raise on revoke step
"""
from __future__ import annotations

import structlog

from shared.connectors.base import (
    CapabilityReport,
    CredentialMaterial,
    SecretValue,
    VerifyResult,
    VersionId,
)
from shared.refs import ConsumerRef, CredentialRef, PrincipalRef, ResourceRef, StoreRef

logger = structlog.get_logger(__name__)

# Sentinel credential material returned by sandbox provision
_SANDBOX_KEY_ID     = "AKIA_SANDBOX_NEW_KEY_0001"
_SANDBOX_SECRET     = "SANDBOX/Secret+AccessKey/notReal/forDemoOnly"  # noqa: S105
_SANDBOX_VERSION    = "v-sandbox-2"


class SandboxConnectorError(Exception):
    """Raised by sandbox connectors when fail_at matches the current step kind."""


class SandboxStoreConnector:
    """
    Fake SecretStoreConnector — all operations are in-memory no-ops that
    return plausible-looking values.

    Args:
        fail_at: Step kind string ('provision'|'distribute'|'verify'|'revoke')
                 that should raise SandboxConnectorError when executed.
                 None = always succeed.
    """

    def __init__(self, fail_at: str | None = None) -> None:
        self._fail_at = fail_at
        self._store: dict[str, SecretValue] = {}

    def _maybe_fail(self, step_kind: str) -> None:
        if self._fail_at and self._fail_at == step_kind:
            raise SandboxConnectorError(
                f"Simulated failure at step kind '{step_kind}'"
            )

    def test_connection(self) -> CapabilityReport:
        return CapabilityReport(read=True, write=True, rotate=True, revoke=True)

    def read(self, ref: StoreRef) -> SecretValue:
        stored = self._store.get(ref.path)
        if stored:
            return stored
        return SecretValue(value="***SANDBOX_CURRENT_VALUE***", version="v-sandbox-1")

    def write_new_version(self, ref: StoreRef, value: SecretValue) -> VersionId:
        self._maybe_fail("distribute")
        self._store[ref.path] = value
        logger.debug("sandbox.store.write_new_version", path=ref.path)
        return VersionId(id=_SANDBOX_VERSION, store_ref=ref)

    def verify_store(self, ref: StoreRef) -> VerifyResult:
        self._maybe_fail("verify")
        return VerifyResult(
            success=True,
            message="sandbox_store_verified",
            metadata={"path": ref.path, "version": _SANDBOX_VERSION},
        )

    def revoke_old(self, ref: StoreRef, version: VersionId) -> None:
        self._maybe_fail("revoke")
        self._store.pop(ref.path, None)
        logger.debug("sandbox.store.revoke_old", path=ref.path, version=version.id)


class SandboxCloudConnector:
    """
    Fake CloudConnector — simulates AWS IAM operations in-memory.

    Args:
        fail_at: Step kind that should raise SandboxConnectorError.
    """

    def __init__(self, fail_at: str | None = None) -> None:
        self._fail_at = fail_at

    def _maybe_fail(self, step_kind: str) -> None:
        if self._fail_at and self._fail_at == step_kind:
            raise SandboxConnectorError(
                f"Simulated failure at step kind '{step_kind}'"
            )

    def test_connection(self) -> CapabilityReport:
        return CapabilityReport(read=True, write=True, rotate=True, revoke=True)

    def enumerate_scope(self, principal: PrincipalRef) -> list[ResourceRef]:
        return [
            ResourceRef(
                provider="aws",
                resource_type="s3",
                arn=f"arn:aws:s3:::sandbox-bucket-prod",
                label="S3 Bucket: sandbox-bucket-prod",
                environment="prod",
            ),
            ResourceRef(
                provider="aws",
                resource_type="ec2",
                arn=f"arn:aws:ec2:us-east-1:123456789012:instance/i-sandbox",
                label="EC2 Resource: i-sandbox",
                environment="prod",
            ),
        ]

    def create_credential(self, principal: PrincipalRef) -> CredentialMaterial:
        self._maybe_fail("provision")
        logger.debug("sandbox.cloud.create_credential", principal=principal.arn)
        return CredentialMaterial(
            credential_id=_SANDBOX_KEY_ID,
            access_key_id=_SANDBOX_KEY_ID,
            secret_access_key=_SANDBOX_SECRET,
        )

    def disable_credential(self, credential: CredentialRef) -> None:
        self._maybe_fail("revoke")
        logger.debug("sandbox.cloud.disable_credential", key_id=credential.credential_id)

    def delete_credential(self, credential: CredentialRef) -> None:
        self._maybe_fail("revoke")
        logger.debug("sandbox.cloud.delete_credential", key_id=credential.credential_id)


def build_sandbox_connectors(fail_at: str | None = None) -> dict:
    """
    Return a connectors dict used by the rotation engine in demo/sandbox mode.

    Keys:
        "store"  → SandboxStoreConnector
        "cloud"  → SandboxCloudConnector
    """
    return {
        "store": SandboxStoreConnector(fail_at=fail_at),
        "cloud": SandboxCloudConnector(fail_at=fail_at),
    }
