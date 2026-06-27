"""
Connector protocols — the fixed contract all connector implementations must satisfy.

Three protocols (§8.6):
- SecretStoreConnector  : Vault, SSM, Secrets Manager
- CloudConnector        : AWS IAM (credential authority)
- ConsumerConnector     : k8s, ECS, Lambda, CI (consumer-side verify/distribute)

Rules:
- `verify` is split into `verify_store` (store-level) and `verify_consumer`
  (consumer-level, C4) to disambiguate the two distinct checks.
- `CloudConnector` has both `disable_credential` (reversible) and
  `delete_credential` (the 'delete' in disable-then-delete, M1).
- Secret *values* from `read`/`create_credential` are transient — never persisted
  to Postgres or sent to any LLM (C1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from shared.refs import ConsumerRef, CredentialRef, PrincipalRef, ResourceRef, StoreRef


# ── Value types ────────────────────────────────────────────────────────────────

@dataclass
class CapabilityReport:
    read: bool = False
    write: bool = False
    rotate: bool = False
    revoke: bool = False
    error: str | None = None


@dataclass
class SecretValue:
    """Transient — must not be persisted to DB or logged."""
    value: str
    version: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class VersionId:
    id: str
    store_ref: StoreRef


@dataclass
class VerifyResult:
    success: bool
    message: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class CredentialMaterial:
    """
    Transient new credential from CloudConnector.create_credential (C1/C5).
    Held in-memory only; written to the target store/consumers and then discarded.
    Never logged, never persisted to Postgres, never sent to an LLM.
    """
    credential_id: str
    # Values deliberately kept as optional fields; callers must handle None.
    access_key_id: str | None = None
    secret_access_key: str | None = None
    metadata: dict = field(default_factory=dict)


# ── Protocols ──────────────────────────────────────────────────────────────────

@runtime_checkable
class SecretStoreConnector(Protocol):
    """Vault, AWS SSM Parameter Store, AWS Secrets Manager."""

    def test_connection(self) -> CapabilityReport:
        """Probe connection and per-capability (read/write/rotate/revoke) health."""
        ...

    def read(self, ref: StoreRef) -> SecretValue:
        """Read the current (or pinned-version) secret value."""
        ...

    def write_new_version(self, ref: StoreRef, value: SecretValue) -> VersionId:
        """Write a new version; old version remains readable until revoked."""
        ...

    def verify_store(self, ref: StoreRef) -> VerifyResult:
        """Confirm the new version is readable in the store (M2: store-level check)."""
        ...

    def revoke_old(self, ref: StoreRef, version: VersionId) -> None:
        """Delete / deactivate the old version after all consumers are verified."""
        ...


@runtime_checkable
class CloudConnector(Protocol):
    """AWS IAM — the credential *authority* for IAM access keys."""

    def enumerate_scope(self, principal: PrincipalRef) -> list[ResourceRef]:
        """List resources reachable by the principal (blast-radius, read-only)."""
        ...

    def create_credential(self, principal: PrincipalRef) -> CredentialMaterial:
        """
        Provision a new credential. Returns transient material (C1/C5).
        Compensation = delete_credential (used in rollback if store-write fails).
        """
        ...

    def disable_credential(self, credential: CredentialRef) -> None:
        """Deactivate (reversible) — the first step of disable-then-delete."""
        ...

    def delete_credential(self, credential: CredentialRef) -> None:
        """Permanently delete — the second, irreversible step (M1 fix, §5.3.4)."""
        ...


@runtime_checkable
class ConsumerConnector(Protocol):
    """k8s secrets, ECS/Lambda env vars, CI variables — consumer-side operations."""

    def discover(self, secret_id: str) -> list[ConsumerRef]:
        """Best-effort discovery of consumers for this secret (C2)."""
        ...

    def distribute(self, consumer: ConsumerRef, value: SecretValue) -> None:
        """Push the new secret value into the consumer."""
        ...

    def verify_consumer(self, consumer: ConsumerRef) -> VerifyResult:
        """
        Credential-level validation: confirm the consumer can authenticate with
        the new secret (C4). Does NOT assert full application health.
        """
        ...
