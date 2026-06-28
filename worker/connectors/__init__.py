"""
Connector registry — maps connector_type → implementation class.

Usage:
    from worker.connectors import get_store_connector, get_cloud_connector

    vault = get_store_connector("vault", creds={"addr": ..., "token": ...})
    iam   = get_cloud_connector("aws_iam", creds={"role_arn": ..., ...})
"""
from __future__ import annotations

from typing import Any

from worker.connectors.github import GitHubConnector
from worker.connectors.iam import IamConnector
from worker.connectors.vault import VaultStoreConnector

_STORE_REGISTRY: dict[str, type] = {
    "vault": VaultStoreConnector,
}

_CLOUD_REGISTRY: dict[str, type] = {
    "aws_iam": IamConnector,
}


def get_store_connector(connector_type: str, creds: dict[str, Any]):
    """Return an initialised SecretStoreConnector for *connector_type*."""
    cls = _STORE_REGISTRY.get(connector_type)
    if cls is None:
        raise ValueError(f"Unknown store connector type: {connector_type!r}")
    return cls(**creds)


def get_cloud_connector(connector_type: str, creds: dict[str, Any]):
    """Return an initialised CloudConnector for *connector_type*."""
    cls = _CLOUD_REGISTRY.get(connector_type)
    if cls is None:
        raise ValueError(f"Unknown cloud connector type: {connector_type!r}")
    return cls(**creds)


def get_github_connector(token: str | None = None) -> GitHubConnector:
    """Return a GitHubConnector. *token* is optional; returns empty results if absent."""
    return GitHubConnector(token=token)


__all__ = [
    "get_store_connector",
    "get_cloud_connector",
    "get_github_connector",
    "IamConnector",
    "VaultStoreConnector",
    "GitHubConnector",
]
