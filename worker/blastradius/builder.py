"""
BlastRadiusBuilder — constructs the in-memory graph of nodes and edges
from IAM enumerate_scope results + Vault verify_store results.

Outputs plain dataclasses — no DB writes here.  The investigate job writes
them to the graph_nodes / graph_edges / severities tables once the agent
completes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog

from shared.refs import PrincipalRef, ResourceRef
from shared.connectors.base import VerifyResult

logger = structlog.get_logger(__name__)

# ── Confidence levels (matches DB enum) ──────────────────────────────────────

CONFIDENCE_HIGH   = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW    = "low"

# Resource types that indicate elevated privilege
_HIGH_PRIV_SERVICES = {"iam", "rds", "secretsmanager", "kms", "sts"}

# ── Graph node/edge dataclasses ───────────────────────────────────────────────

@dataclass
class GraphNodeData:
    """
    In-memory representation; maps to graph_nodes table row.

    kind values (node_kind enum): secret | location | ci | store_entry | principal | resource | environment
    """
    id: uuid.UUID
    secret_id: uuid.UUID
    workspace_id: uuid.UUID
    kind: str
    label: str
    environment: str
    attrs: dict = field(default_factory=dict)


@dataclass
class GraphEdgeData:
    """
    In-memory representation; maps to graph_edges table row.

    kind values (edge_kind enum): found_in | stored_in | is_principal | grants_access_to | used_by | can_access
    """
    id: uuid.UUID
    secret_id: uuid.UUID
    workspace_id: uuid.UUID
    src_node_id: uuid.UUID
    dst_node_id: uuid.UUID
    kind: str
    confidence: str
    attrs: dict = field(default_factory=dict)


@dataclass
class CoverageReport:
    known_consumers: int   = 0
    unknown_consumers: int = 0
    confidence: str        = CONFIDENCE_LOW


# ── Builder ───────────────────────────────────────────────────────────────────

class BlastRadiusBuilder:
    """
    Build a blast-radius graph from connector outputs.

    Usage:
        builder = BlastRadiusBuilder(secret_id=..., workspace_id=...)
        nodes, edges, coverage = builder.build(
            principal=principal_ref,
            resources=iam_connector.enumerate_scope(principal),
            store_verify=vault_connector.verify_store(store_ref),
        )
    """

    def __init__(
        self,
        secret_id: uuid.UUID,
        workspace_id: uuid.UUID,
        environment: str = "unknown",
    ) -> None:
        self._secret_id = secret_id
        self._workspace_id = workspace_id
        self._environment = environment

    def build(
        self,
        principal: PrincipalRef,
        resources: list[ResourceRef],
        store_verify: VerifyResult | None = None,
    ) -> tuple[list[GraphNodeData], list[GraphEdgeData], CoverageReport]:
        """
        Return (nodes, edges, coverage) for the blast-radius graph.

        Graph structure:
            [secret node] --uses--> [principal node] --accesses--> [resource node, ...]
            [secret node] --reads_from--> [store node]  (if store_verify)
        """
        nodes: list[GraphNodeData] = []
        edges: list[GraphEdgeData] = []

        # 1. Secret node (anchor)
        secret_node = self._make_node(
            kind="secret",
            label=f"secret:{self._secret_id}",
            environment=self._environment,
            attrs={"secret_id": str(self._secret_id)},
        )
        nodes.append(secret_node)

        # 2. Principal node (IAM user / role)
        principal_node = self._make_node(
            kind="principal",
            label=principal.arn.split(":")[-1] if ":" in principal.arn else principal.arn,
            environment=self._environment,
            attrs={
                "arn": principal.arn,
                "provider": principal.provider,
                "principal_type": principal.principal_type,
                "account_id": principal.account_id,
            },
        )
        nodes.append(principal_node)

        # secret → principal (is_principal edge)
        edges.append(self._make_edge(
            src=secret_node.id,
            dst=principal_node.id,
            kind="is_principal",
            confidence=CONFIDENCE_HIGH,
        ))

        high_priv_count = 0

        # 3. Resource nodes
        for resource in resources:
            env = _infer_env(resource)
            is_high_priv = resource.resource_type.lower() in _HIGH_PRIV_SERVICES
            if is_high_priv:
                high_priv_count += 1

            res_node = self._make_node(
                kind="resource",
                label=resource.label,
                environment=env,
                attrs={
                    "arn": resource.arn,
                    "resource_type": resource.resource_type,
                    "provider": resource.provider,
                    "high_privilege": is_high_priv,
                },
            )
            nodes.append(res_node)

            # principal → resource (grants_access_to edge)
            confidence = CONFIDENCE_HIGH if is_high_priv else CONFIDENCE_MEDIUM
            edges.append(self._make_edge(
                src=principal_node.id,
                dst=res_node.id,
                kind="grants_access_to",
                confidence=confidence,
            ))

        # 4. Store node (from Vault verify)
        if store_verify is not None:
            store_node = self._make_node(
                kind="store_entry",
                label="vault",
                environment=self._environment,
                attrs={
                    "store_type": "vault",
                    "readable": store_verify.success,
                    **store_verify.metadata,
                },
            )
            nodes.append(store_node)
            edges.append(self._make_edge(
                src=secret_node.id,
                dst=store_node.id,
                kind="stored_in",
                confidence=CONFIDENCE_HIGH if store_verify.success else CONFIDENCE_LOW,
            ))

        # 5. Coverage report
        known = len(resources)
        overall_conf = (
            CONFIDENCE_HIGH if known > 5
            else CONFIDENCE_MEDIUM if known > 1
            else CONFIDENCE_LOW
        )
        coverage = CoverageReport(
            known_consumers=known,
            unknown_consumers=0,
            confidence=overall_conf,
        )

        logger.info(
            "blastradius.built",
            secret_id=str(self._secret_id),
            nodes=len(nodes),
            edges=len(edges),
            resource_count=len(resources),
            high_priv_count=high_priv_count,
        )
        return nodes, edges, coverage

    # ── Private helpers ────────────────────────────────────────────────────────

    def _make_node(self, kind: str, label: str, environment: str, attrs: dict) -> GraphNodeData:
        return GraphNodeData(
            id=uuid.uuid4(),
            secret_id=self._secret_id,
            workspace_id=self._workspace_id,
            kind=kind,
            label=label,
            environment=environment,
            attrs=attrs,
        )

    def _make_edge(
        self,
        src: uuid.UUID,
        dst: uuid.UUID,
        kind: str,
        confidence: str,
    ) -> GraphEdgeData:
        return GraphEdgeData(
            id=uuid.uuid4(),
            secret_id=self._secret_id,
            workspace_id=self._workspace_id,
            src_node_id=src,
            dst_node_id=dst,
            kind=kind,
            confidence=confidence,
        )


def _infer_env(resource: ResourceRef) -> str:
    """Guess environment from resource ARN tags or explicit field."""
    if resource.environment and resource.environment != "unknown":
        return resource.environment
    arn_lower = resource.arn.lower()
    for env in ("prod", "staging", "stg", "dev", "test"):
        if env in arn_lower:
            return env
    return "unknown"
