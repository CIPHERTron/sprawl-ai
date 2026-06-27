"""
Python enums mirroring the Postgres CREATE TYPE enums in the Phase 8 schema.
These are the single source of truth for state values used across api, worker,
and migrations. DB enums are generated from these names.
"""
from enum import StrEnum


class WorkspaceKind(StrEnum):
    STANDARD = "standard"
    DEMO = "demo"


class Role(StrEnum):
    OWNER = "owner"
    APPROVER = "approver"
    VIEWER = "viewer"


class ConnectorType(StrEnum):
    VAULT = "vault"
    AWS_SSM = "aws_ssm"
    AWS_IAM = "aws_iam"
    AWS_SECRETS_MANAGER = "aws_secrets_manager"
    INFISICAL = "infisical"


class ConnectorStatus(StrEnum):
    UNTESTED = "untested"
    VERIFIED = "verified"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class ScanStatus(StrEnum):
    QUEUED = "queued"
    SCANNING = "scanning"
    COMPLETE = "complete"
    ERROR = "error"


class FindingState(StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    IGNORED = "ignored"


class SecretHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    AT_RISK = "at_risk"
    EXPOSED = "exposed"


class ExposureStatus(StrEnum):
    UNKNOWN = "unknown"
    LIVE_INFERRED = "live_inferred"
    PUBLIC_LEAK = "public_leak"
    INACTIVE = "inactive"


class SeverityBucket(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Environment(StrEnum):
    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"
    UNKNOWN = "unknown"


class NodeKind(StrEnum):
    SECRET = "secret"
    LOCATION = "location"
    CI = "ci"
    STORE_ENTRY = "store_entry"
    PRINCIPAL = "principal"
    RESOURCE = "resource"
    ENVIRONMENT = "environment"


class EdgeKind(StrEnum):
    FOUND_IN = "found_in"
    STORED_IN = "stored_in"
    IS_PRINCIPAL = "is_principal"
    GRANTS_ACCESS_TO = "grants_access_to"
    USED_BY = "used_by"
    CAN_ACCESS = "can_access"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class InvestigationStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class RotationStatus(StrEnum):
    # Pre-plan phase: row created, planner running in worker
    PROPOSED = "proposed"
    # Planning failed/aborted before a plan existed (N1 — terminal, releases lock)
    PLAN_FAILED = "plan_failed"
    # Plan ready, awaiting human approval
    PENDING_APPROVAL = "pending_approval"
    PROVISIONING = "provisioning"
    DISTRIBUTING = "distributing"
    VERIFYING = "verifying"
    # Waiting for human step-confirmation or re-confirmation after drift (D11/C6)
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    REVOKING = "revoking"
    # Terminal — success
    COMPLETED = "completed"
    # Rollback in progress
    ROLLING_BACK = "rolling_back"
    # Terminal — successfully rolled back; old secret still valid
    ROLLED_BACK = "rolled_back"
    # Terminal — rollback failed; requires manual intervention (critical)
    ROLLBACK_FAILED = "rollback_failed"
    # User rejected the plan (terminal)
    REJECTED = "rejected"
    # Plan TTL expired; requires re-plan (C6)
    NEEDS_REPLAN = "needs_replan"
    # Expired needs_replan swept to terminal by reaper (M3/§8.10); releases lock
    ABANDONED = "abandoned"


# Terminal rotation states — used by one_active_rotation partial unique index
ROTATION_TERMINAL_STATUSES: frozenset[RotationStatus] = frozenset({
    RotationStatus.COMPLETED,
    RotationStatus.ROLLED_BACK,
    RotationStatus.REJECTED,
    RotationStatus.ROLLBACK_FAILED,
    RotationStatus.ABANDONED,
    RotationStatus.PLAN_FAILED,
})


class StepKind(StrEnum):
    PROVISION = "provision"
    DISTRIBUTE = "distribute"
    VERIFY = "verify"
    REVOKE = "revoke"


class StepStatus(StrEnum):
    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    COMPENSATED = "compensated"
