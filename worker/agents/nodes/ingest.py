"""
Ingest node — reads Secret + Finding rows from Postgres and populates
state["context"] with the data needed by subsequent nodes.

No connector calls are made here.  This node is purely a DB read.

The node also loads connector credentials from the workspace's connector
rows so that investigator / blast_radius nodes have them available in state
(credentials flow in-memory; they are never written back to state via DB).
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import text

from worker.agents.guardrails import guardrail
from worker.agents.state import FindingLocation, InvestigationState, SecretContext
from worker.db import async_session_maker

logger = structlog.get_logger(__name__)


@guardrail(timeout_s=30, node_name="ingest")
async def ingest_node(state: InvestigationState) -> InvestigationState:
    """
    Reads:
        - secrets table (type, provider, health, environment, exposure_status)
        - findings table (file_path, commit_sha, repo, line_number)
        - connectors table (type, config) for the workspace

    Writes:
        state["context"] — SecretContext populated with DB data
    """
    secret_id = uuid.UUID(state["secret_id"])
    workspace_id = uuid.UUID(state["workspace_id"])
    investigation_id = uuid.UUID(state["investigation_id"])

    async with async_session_maker() as db:
        # ── 1. Load secret ─────────────────────────────────────────────────────
        secret_row = await db.execute(
            text("""
                SELECT type, provider, health, environment, exposure_status
                FROM secrets
                WHERE id = :id AND workspace_id = :workspace_id
                LIMIT 1
            """),
            {"id": secret_id, "workspace_id": workspace_id},
        )
        secret = secret_row.mappings().one_or_none()
        if secret is None:
            raise ValueError(f"Secret {secret_id} not found in workspace {workspace_id}")

        context = SecretContext(
            secret_id=secret_id,
            workspace_id=workspace_id,
            investigation_id=investigation_id,
            secret_type=secret["type"] or "unknown",
            environment=secret["environment"] or "unknown",
            exposure_status=secret["exposure_status"] or "unknown",
            health=secret["health"] or "unknown",
            provider=secret["provider"] or "unknown",
        )

        # ── 2. Load findings (join repos for full_name) ────────────────────────
        findings_rows = await db.execute(
            text("""
                SELECT f.file_path, f.commit_sha, f.line, r.full_name AS repo
                FROM findings f
                LEFT JOIN repos r ON r.id = f.repo_id
                WHERE f.secret_id = :secret_id
                ORDER BY f.last_seen DESC
                LIMIT 20
            """),
            {"secret_id": secret_id},
        )
        for row in findings_rows.mappings():
            if row["repo"] and row["file_path"]:
                context.locations.append(
                    FindingLocation(
                        repo=str(row["repo"]),
                        file_path=str(row["file_path"]),
                        commit_sha=row["commit_sha"],
                        line=row["line"],
                    )
                )

        # ── 3. Load connector credentials for this workspace ───────────────────
        # connectors.connection is the JSONB column holding runtime credentials/config
        connector_rows = await db.execute(
            text("""
                SELECT type, connection, path_prefix
                FROM connectors
                WHERE workspace_id = :workspace_id
            """),
            {"workspace_id": workspace_id},
        )
        for conn in connector_rows.mappings():
            cfg = conn["connection"] or {}
            ctype = str(conn["type"] or "")
            if ctype == "vault":
                context.vault_addr = cfg.get("addr")
                context.vault_role_id = cfg.get("role_id")
                context.vault_secret_id = cfg.get("secret_id")
                # path_prefix is the KV mount prefix; store_path set from secret store_ref
                context.store_path = conn.get("path_prefix") or cfg.get("secret_path")
            elif ctype == "aws_iam":
                context.aws_role_arn = cfg.get("role_arn")
                context.aws_external_id = cfg.get("external_id")
                if cfg.get("principal_arn"):
                    context.principal_arn = cfg["principal_arn"]
                    context.principal_type = "iam_user"
                    context.account_id = cfg.get("account_id", "")
            elif ctype == "github":
                context.github_token = cfg.get("token")

        # Also read principal_ref + store_ref from the secret row if available
        secret_detail_row = await db.execute(
            text("SELECT principal_ref, store_ref FROM secrets WHERE id = :id"),
            {"id": secret_id},
        )
        detail = secret_detail_row.mappings().one_or_none()
        if detail:
            pr = detail["principal_ref"] or {}
            if pr.get("arn") and not context.principal_arn:
                context.principal_arn = pr["arn"]
                context.principal_type = pr.get("principal_type", "iam_user")
                context.account_id = pr.get("account_id", "")
            sr = detail["store_ref"] or {}
            if sr.get("path") and not context.store_path:
                context.store_path = sr["path"]

    logger.info(
        "ingest.done",
        secret_id=str(secret_id),
        locations=len(context.locations),
        secret_type=context.secret_type,
    )

    events = list(state.get("events") or [])
    events.append({"type": "node.complete", "node": "ingest"})

    return {**state, "context": context, "events": events}  # type: ignore[return-value]
