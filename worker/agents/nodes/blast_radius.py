"""
Blast-radius node — calls IamConnector.enumerate_scope + BlastRadiusBuilder.

Builds the in-memory graph (nodes + edges) representing the blast radius
of the secret's principal.  Results land in state["graph"].
"""
from __future__ import annotations

import asyncio
import functools
import uuid

import structlog

from shared.refs import PrincipalRef, StoreRef
from worker.agents.guardrails import guardrail
from worker.agents.state import BlastRadiusGraph, InvestigationState, SecretContext
from worker.blastradius.builder import BlastRadiusBuilder
from worker.connectors.iam import IamConnector
from worker.connectors.vault import VaultStoreConnector

logger = structlog.get_logger(__name__)

# Resource types considered "high privilege" for weighting purposes
_HIGH_PRIV_TYPES = {"iam", "rds", "secretsmanager", "kms", "sts", "ec2"}


@guardrail(timeout_s=90, node_name="blast_radius")
async def blast_radius_node(state: InvestigationState) -> InvestigationState:
    """
    Populates state["graph"] with GraphNodeData + GraphEdgeData + CoverageReport.
    """
    context: SecretContext | None = state.get("context")
    if context is None:
        return state  # type: ignore[return-value]

    loop = asyncio.get_event_loop()

    # ── 1. IAM enumerate_scope ─────────────────────────────────────────────────
    resources = []
    if context.principal_arn:
        principal = PrincipalRef(
            provider="aws",
            principal_type=context.principal_type or "iam_user",
            arn=context.principal_arn,
            account_id=context.account_id or "",
        )
        try:
            iam = IamConnector(
                role_arn=context.aws_role_arn,
                external_id=context.aws_external_id,
            )
            resources = await loop.run_in_executor(
                None, functools.partial(iam.enumerate_scope, principal)
            )
        except Exception as exc:
            logger.warning("blast_radius.iam_enumerate_error", error=str(exc))
    else:
        logger.debug("blast_radius.no_principal — skipping IAM enumeration")

    # ── 2. Vault verify_store ──────────────────────────────────────────────────
    store_verify = None
    if context.store_path:
        try:
            vault = VaultStoreConnector(
                addr=context.vault_addr,
                role_id=context.vault_role_id,
                secret_id=context.vault_secret_id,
            )
            ref = StoreRef(connector_type="vault", connector_id="", path=context.store_path)
            store_verify = await loop.run_in_executor(None, vault.verify_store, ref)
        except Exception as exc:
            logger.warning("blast_radius.vault_verify_error", error=str(exc))

    # ── 3. Build graph ─────────────────────────────────────────────────────────
    builder = BlastRadiusBuilder(
        secret_id=context.secret_id,
        workspace_id=context.workspace_id,
        environment=context.environment,
    )

    if context.principal_arn:
        principal_ref = PrincipalRef(
            provider="aws",
            principal_type=context.principal_type or "iam_user",
            arn=context.principal_arn,
            account_id=context.account_id or "",
        )
        nodes, edges, coverage = builder.build(
            principal=principal_ref,
            resources=resources,
            store_verify=store_verify,
        )
    else:
        # No principal found — build minimal graph (secret + optional store nodes only)
        nodes, edges, coverage = builder.build(
            principal=PrincipalRef(
                provider="aws",
                principal_type="iam_user",
                arn=f"arn:aws:iam::000000000000:user/unknown-{context.secret_id}",
                account_id="000000000000",
            ),
            resources=[],
            store_verify=store_verify,
        )

    high_priv_count = sum(
        1 for r in resources
        if r.resource_type.lower() in _HIGH_PRIV_TYPES
    )

    graph = BlastRadiusGraph(
        nodes=nodes,
        edges=edges,
        coverage=coverage,
        resource_count=len(resources),
        high_priv_count=high_priv_count,
    )

    logger.info(
        "blast_radius.done",
        secret_id=str(context.secret_id),
        nodes=len(nodes),
        edges=len(edges),
        resources=len(resources),
    )

    events = list(state.get("events") or [])
    events.append({
        "type": "node.complete",
        "node": "blast_radius",
        "resource_count": len(resources),
    })

    return {**state, "graph": graph, "events": events}  # type: ignore[return-value]
