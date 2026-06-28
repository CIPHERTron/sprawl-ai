"""
Centralised SQLAlchemy Postgres-native enum type objects.

All types use values_callable so SQLAlchemy sends the StrEnum .value
("demo") not the Python member name ("DEMO") to Postgres.
Import from here in all model files instead of defining locally.
"""
import sqlalchemy as sa

from shared.models.enums import (
    Confidence,
    ConnectorStatus,
    ConnectorType,
    EdgeKind,
    Environment,
    ExposureStatus,
    FindingState,
    InvestigationStatus,
    NodeKind,
    Role,
    RotationStatus,
    ScanStatus,
    SecretHealth,
    SeverityBucket,
    StepKind,
    StepStatus,
    WorkspaceKind,
)


def _pg_enum(enum_cls: type, name: str) -> sa.Enum:
    """Create a native Postgres enum type that uses .value not .name."""
    return sa.Enum(
        enum_cls,
        name=name,
        create_type=False,
        values_callable=lambda x: [e.value for e in x],
    )


workspace_kind_type = _pg_enum(WorkspaceKind, "workspace_kind")
role_type = _pg_enum(Role, "role")
connector_type_enum = _pg_enum(ConnectorType, "connector_type")
connector_status_enum = _pg_enum(ConnectorStatus, "connector_status")
scan_status_enum = _pg_enum(ScanStatus, "scan_status")
finding_state_enum = _pg_enum(FindingState, "finding_state")
secret_health_enum = _pg_enum(SecretHealth, "secret_health")
exposure_status_enum = _pg_enum(ExposureStatus, "exposure_status")
severity_bucket_enum = _pg_enum(SeverityBucket, "severity_bucket")
environment_enum = _pg_enum(Environment, "environment")
node_kind_enum = _pg_enum(NodeKind, "node_kind")
edge_kind_enum = _pg_enum(EdgeKind, "edge_kind")
confidence_enum = _pg_enum(Confidence, "confidence")
investigation_status_enum = _pg_enum(InvestigationStatus, "investigation_status")
rotation_status_enum = _pg_enum(RotationStatus, "rotation_status")
step_kind_enum = _pg_enum(StepKind, "step_kind")
step_status_enum = _pg_enum(StepStatus, "step_status")
