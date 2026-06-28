"""
InvestigationState — the shared state dict that flows through the LangGraph.

§5.2.2 defines the canonical shape.  All fields are optional so each node
can be run independently and state evolves incrementally.

Supporting types live in this module so imports are single-source-of-truth.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from worker.blastradius.builder import CoverageReport, GraphEdgeData, GraphNodeData
from worker.severity.engine import SeverityFactors


# ── Supporting types ──────────────────────────────────────────────────────────

@dataclass
class FindingLocation:
    """A code location where a secret was found."""
    repo: str              # repo full_name (e.g. 'org/repo')
    file_path: str
    line: int | None = None
    commit_sha: str | None = None
    file_snippet: str | None = None  # fetched by investigator node (optional)


@dataclass
class SecretContext:
    """Enriched context built up by ingest + investigator nodes."""
    secret_id: uuid.UUID
    workspace_id: uuid.UUID
    investigation_id: uuid.UUID

    # From DB
    secret_type: str = "unknown"
    environment: str = "unknown"
    exposure_status: str = "unknown"
    health: str = "unknown"
    provider: str = "unknown"

    # Finding locations (populated by ingest node)
    locations: list[FindingLocation] = field(default_factory=list)

    # Connector-fetched (populated by investigator node)
    principal_arn: str | None = None
    principal_type: str | None = None
    account_id: str | None = None
    store_path: str | None = None
    store_present: bool = False
    last_used_date: str | None = None
    last_used_service: str | None = None

    # Connector creds for the workspace (populated by ingest from DB)
    vault_addr: str | None = None
    vault_role_id: str | None = None
    vault_secret_id: str | None = None
    aws_role_arn: str | None = None
    aws_external_id: str | None = None
    github_token: str | None = None


@dataclass
class BlastRadiusGraph:
    """Graph output from blast_radius node."""
    nodes: list[GraphNodeData] = field(default_factory=list)
    edges: list[GraphEdgeData] = field(default_factory=list)
    coverage: CoverageReport | None = None
    resource_count: int = 0
    high_priv_count: int = 0


@dataclass
class SeverityResult:
    """Output of severity node."""
    score: int = 0
    bucket: str = "low"
    factors: SeverityFactors | None = None
    explanation: str | None = None


@dataclass
class AgentError:
    node: str
    message: str
    recoverable: bool = True


# ── LangGraph state ───────────────────────────────────────────────────────────

RoutingDecision = Literal["investigate", "skip"]


class InvestigationState(TypedDict, total=False):
    """
    The single state dict threaded through the LangGraph.

    All keys are optional (total=False) so nodes can add their contribution
    without requiring all other nodes to have run first.
    """
    # Input — set by the job before invoking the graph
    secret_id: str
    workspace_id: str
    investigation_id: str
    trace_id: str | None

    # Built by ingest node
    context: SecretContext

    # Routing decision (set by triage)
    routing: RoutingDecision
    triage_score: int          # cheap pre-investigation score

    # Built by blast_radius node
    graph: BlastRadiusGraph

    # Built by severity node
    severity: SeverityResult

    # Errors accumulated by any node (non-fatal)
    errors: list[AgentError]

    # Progress events published to Redis (list of event dicts; job reads these)
    events: list[dict]
