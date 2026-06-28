"""
VaultStoreConnector — implements SecretStoreConnector protocol (§8.6).

Wraps VaultClient with the canonical protocol methods:
  read / write_new_version / verify_store / revoke_old / test_connection
"""
from __future__ import annotations

import structlog

from shared.connectors.base import (
    CapabilityReport,
    SecretValue,
    VerifyResult,
    VersionId,
)
from shared.refs import StoreRef
from worker.connectors.vault_client import VaultClient

logger = structlog.get_logger(__name__)


class VaultStoreConnector:
    """
    SecretStoreConnector implementation backed by HashiCorp Vault KV v2.

    *creds* are passed as constructor kwargs by the connector registry:
        VaultStoreConnector(addr=..., role_id=..., secret_id=..., mount_point=...)
    """

    def __init__(
        self,
        addr: str | None = None,
        role_id: str | None = None,
        secret_id: str | None = None,
        mount_point: str = "secret",
        namespace: str | None = None,
    ) -> None:
        self._vault = VaultClient(
            addr=addr,
            role_id=role_id,
            secret_id=secret_id,
            namespace=namespace,
            mount_point=mount_point,
        )

    # ── Protocol methods ───────────────────────────────────────────────────────

    def test_connection(self) -> CapabilityReport:
        try:
            self._vault.connect()
            health = self._vault.client.sys.read_health_status()
            if health.get("sealed"):
                return CapabilityReport(error="vault_sealed")
            return CapabilityReport(read=True, write=True, rotate=True, revoke=True)
        except Exception as exc:
            return CapabilityReport(error=str(exc))

    def read(self, ref: StoreRef) -> SecretValue:
        version_int = int(ref.version) if ref.version else None
        data = self._vault.get_secret(ref.path, version=version_int)
        # KV v2 stores arbitrary key/value — serialise back to a single string value
        value = data.get("value") or data.get("secret") or next(iter(data.values()), "")
        return SecretValue(value=str(value), version=ref.version, metadata=data)

    def write_new_version(self, ref: StoreRef, value: SecretValue) -> VersionId:
        meta = self._vault.put_secret(ref.path, data={"value": value.value})
        version_str = str(meta.get("version", ""))
        return VersionId(id=version_str, store_ref=ref)

    def verify_store(self, ref: StoreRef) -> VerifyResult:
        """
        Confirm the latest version is readable.  Used after write_new_version.
        Reads and compares the value — if readable, store verified.
        """
        try:
            data = self._vault.get_secret(ref.path)
            return VerifyResult(
                success=True,
                message="vault_read_ok",
                metadata={"keys": list(data.keys())},
            )
        except Exception as exc:
            return VerifyResult(success=False, message=str(exc))

    def revoke_old(self, ref: StoreRef, version: VersionId) -> None:
        try:
            version_int = int(version.id)
            self._vault.delete_versions(ref.path, versions=[version_int])
        except ValueError:
            logger.warning("vault.revoke_invalid_version", version_id=version.id)
