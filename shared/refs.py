"""
Canonical reference types used across api, worker, and connectors.
These are pure data — no DB or network dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StoreRef:
    """Points to a secret in a secret store (Vault, SSM, …)."""
    connector_type: str       # 'vault' | 'aws_ssm' | 'aws_secrets_manager'
    connector_id: str         # FK to connectors.id
    path: str                 # store path / parameter name
    version: str | None = None


@dataclass
class ConsumerRef:
    """Identifies a system that uses a secret (k8s, ECS, Lambda, CI, …)."""
    kind: str                 # 'k8s_secret' | 'ecs_env' | 'lambda_env' | 'ci_var' | 'code'
    id: str                   # stable identifier (e.g. namespace/name, cluster/service)
    label: str                # human-readable
    metadata: dict = field(default_factory=dict)


@dataclass
class PrincipalRef:
    """Identifies a cloud principal (IAM user / role) that a credential IS."""
    provider: str             # 'aws'
    principal_type: str       # 'iam_user' | 'iam_role'
    arn: str
    account_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class CredentialRef:
    """Identifies a specific credential object (e.g. an IAM access key)."""
    provider: str             # 'aws'
    credential_type: str      # 'access_key'
    credential_id: str        # e.g. AKIA…
    metadata: dict = field(default_factory=dict)


@dataclass
class ResourceRef:
    """A cloud resource reachable by a principal (blast-radius node)."""
    provider: str             # 'aws'
    resource_type: str        # 's3_bucket' | 'rds_instance' | …
    arn: str
    label: str
    environment: str = "unknown"  # 'prod' | 'staging' | 'dev' | 'unknown'
    metadata: dict = field(default_factory=dict)
