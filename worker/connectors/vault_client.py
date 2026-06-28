"""
Low-level Vault client wrapping `hvac`.

Authenticates using AppRole (role_id + secret_id) taken from worker_settings
or supplied directly.  All network calls are synchronous/blocking (hvac is sync);
call these from a thread pool executor when needed from async contexts.
"""
from __future__ import annotations

import hvac
import structlog

from worker.config import worker_settings

logger = structlog.get_logger(__name__)


class VaultClient:
    """
    Thin wrapper around hvac.Client that handles AppRole authentication
    and provides `get_secret` / `put_secret` for KV v2 mounts.
    """

    def __init__(
        self,
        addr: str | None = None,
        role_id: str | None = None,
        secret_id: str | None = None,
        namespace: str | None = None,
        mount_point: str = "secret",
    ) -> None:
        self._addr = addr or worker_settings.vault_addr
        self._role_id = role_id or worker_settings.vault_role_id
        self._secret_id = secret_id or worker_settings.vault_secret_id
        self._namespace = namespace
        self._mount_point = mount_point
        self._client: hvac.Client | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Authenticate with Vault. Re-uses existing token if still valid."""
        if self._client and self._client.is_authenticated():
            return

        kwargs: dict = {"url": self._addr}
        if self._namespace:
            kwargs["namespace"] = self._namespace

        self._client = hvac.Client(**kwargs)

        if not self._role_id or not self._secret_id:
            # Dev / test: try token-less connection (Vault dev mode allows this)
            logger.warning("vault.approle_creds_missing — skipping AppRole auth")
            return

        result = self._client.auth.approle.login(
            role_id=self._role_id,
            secret_id=self._secret_id,
        )
        logger.info("vault.authenticated", ttl=result["auth"]["lease_duration"])

    @property
    def client(self) -> hvac.Client:
        if self._client is None or not self._client.is_authenticated():
            self.connect()
        assert self._client is not None
        return self._client

    # ── KV v2 helpers ──────────────────────────────────────────────────────────

    def get_secret(self, path: str, version: int | None = None) -> dict:
        """
        Read a KV v2 secret at *path*.
        Returns the `data` dict (key→value), never the wrapper envelope.
        """
        try:
            resp = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._mount_point,
                version=version,
                raise_on_deleted_version=True,
            )
            return resp["data"]["data"]
        except Exception as exc:
            logger.error("vault.read_failed", path=path, error=str(exc))
            raise

    def put_secret(self, path: str, data: dict) -> dict:
        """
        Write a new KV v2 version at *path*.
        Returns the version metadata dict from Vault.
        """
        try:
            resp = self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=data,
                mount_point=self._mount_point,
            )
            version_id = resp["data"]["version"]
            logger.info("vault.wrote_version", path=path, version=version_id)
            return resp["data"]
        except Exception as exc:
            logger.error("vault.write_failed", path=path, error=str(exc))
            raise

    def delete_versions(self, path: str, versions: list[int]) -> None:
        """Permanently delete specific KV v2 versions (revoke old after rotation)."""
        try:
            self.client.secrets.kv.v2.delete_secret_versions(
                path=path,
                versions=versions,
                mount_point=self._mount_point,
            )
            logger.info("vault.versions_deleted", path=path, versions=versions)
        except Exception as exc:
            logger.error("vault.delete_failed", path=path, error=str(exc))
            raise
