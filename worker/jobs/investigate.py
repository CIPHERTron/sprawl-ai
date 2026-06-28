"""
investigate_secret — arq job that runs the full investigation pipeline.

Flow:
  1. Validate secret exists + update Investigation.status = 'running'
  2. Initialise Langfuse trace
  3. Build initial InvestigationState and invoke the LangGraph
  4. On each node's SSE event: PUBLISH investigation.update to Redis
  5. Write GraphNode + GraphEdge + Severity rows to Postgres
  6. Update Secret.severity_score/bucket + Investigation.status = 'complete'
  7. PUBLISH investigation.complete
  8. Append audit entry
  9. On any exception: mark Investigation.status = 'error', publish error event
"""
from __future__ import annotations

import json
import uuid

import structlog
from sqlalchemy import text

from worker.agents.graph import compile_graph, make_checkpointer
from worker.agents.state import InvestigationState
from worker.audit import audit
from worker.config import worker_settings
from worker.db import async_session_maker
from worker.redis import publish_event

logger = structlog.get_logger(__name__)


async def investigate_secret(
    ctx: dict,
    *,
    secret_id: str,
    investigation_id: str,
    workspace_id: str,
) -> dict:
    """
    arq job: run the investigation pipeline for a single secret.

    Returns a summary dict on success or raises on fatal error.
    """
    log = logger.bind(
        secret_id=secret_id,
        investigation_id=investigation_id,
        workspace_id=workspace_id,
    )
    log.info("investigate_secret.start")

    trace_id: str | None = None

    try:
        # ── 1. Mark investigation as running ───────────────────────────────────
        async with async_session_maker() as db:
            async with db.begin():
                await db.execute(
                    text("""
                        UPDATE investigations
                        SET status = 'running', started_at = now()
                        WHERE id = :id AND workspace_id = :workspace_id
                    """),
                    {"id": investigation_id, "workspace_id": workspace_id},
                )

        await publish_event(workspace_id, "investigation.started", {
            "investigation_id": investigation_id,
            "secret_id": secret_id,
        })

        # ── 2. Initialise Langfuse trace (optional) ────────────────────────────
        trace_id = _init_trace(investigation_id, secret_id, workspace_id)
        if trace_id:
            async with async_session_maker() as db:
                async with db.begin():
                    await db.execute(
                        text("UPDATE investigations SET trace_id = :tid WHERE id = :id"),
                        {"tid": trace_id, "id": investigation_id},
                    )

        # ── 3. Build initial state ─────────────────────────────────────────────
        initial_state: InvestigationState = {
            "secret_id": secret_id,
            "workspace_id": workspace_id,
            "investigation_id": investigation_id,
            "trace_id": trace_id,
            "errors": [],
            "events": [],
        }

        # ── 4. Run LangGraph ───────────────────────────────────────────────────
        config = {
            "configurable": {
                "thread_id": f"{investigation_id}",
            }
        }

        try:
            cp_ctx = await make_checkpointer(worker_settings.pg_dsn)
            async with cp_ctx as checkpointer:
                graph = compile_graph(checkpointer=checkpointer)
                final_state = await graph.ainvoke(initial_state, config=config)
        except Exception as cp_exc:
            # Checkpointer unavailable — run without persistence
            log.warning("investigate_secret.checkpointer_fallback", error=str(cp_exc))
            graph = compile_graph(checkpointer=None)
            final_state = await graph.ainvoke(initial_state)

        # Publish intermediate node events from state
        for evt in final_state.get("events") or []:
            await publish_event(workspace_id, evt.get("type", "node.event"), {
                "investigation_id": investigation_id,
                **{k: v for k, v in evt.items() if k != "type"},
            })

        # ── 5. Persist graph + severity ────────────────────────────────────────
        graph_data  = final_state.get("graph")
        severity    = final_state.get("severity")
        context     = final_state.get("context")

        async with async_session_maker() as db:
            async with db.begin():
                if graph_data:
                    for node in graph_data.nodes:
                        await db.execute(
                            text("""
                                INSERT INTO graph_nodes
                                    (id, workspace_id, secret_id, kind, label, environment, attrs)
                                VALUES
                                    (:id, :workspace_id, :secret_id, :kind, :label, :environment, CAST(:attrs AS jsonb))
                                ON CONFLICT (id) DO NOTHING
                            """),
                            {
                                "id": str(node.id),
                                "workspace_id": workspace_id,
                                "secret_id": secret_id,
                                "kind": node.kind,
                                "label": node.label,
                                "environment": _canonical_env(node.environment),
                                "attrs": json.dumps(node.attrs),
                            },
                        )
                    for edge in graph_data.edges:
                        await db.execute(
                            text("""
                                INSERT INTO graph_edges
                                    (id, workspace_id, secret_id,
                                     src_node_id, dst_node_id, kind, confidence, attrs)
                                VALUES
                                    (:id, :workspace_id, :secret_id,
                                     :src, :dst, :kind, :confidence, CAST(:attrs AS jsonb))
                                ON CONFLICT (id) DO NOTHING
                            """),
                            {
                                "id": str(edge.id),
                                "workspace_id": workspace_id,
                                "secret_id": secret_id,
                                "src": str(edge.src_node_id),
                                "dst": str(edge.dst_node_id),
                                "kind": edge.kind,
                                "confidence": edge.confidence,
                                "attrs": json.dumps(edge.attrs),
                            },
                        )

                if severity:
                    from dataclasses import asdict
                    factors_dict = asdict(severity.factors) if severity.factors else {}
                    await db.execute(
                        text("""
                            INSERT INTO severities
                                (id, workspace_id, secret_id, score, factors, explanation)
                            VALUES
                                (:id, :workspace_id, :secret_id, :score, CAST(:factors AS jsonb), :explanation)
                            ON CONFLICT DO NOTHING
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "workspace_id": workspace_id,
                            "secret_id": secret_id,
                            "score": severity.score,
                            "factors": json.dumps(factors_dict),
                            "explanation": severity.explanation,
                        },
                    )

                    # Update secret severity fields
                    await db.execute(
                        text("""
                            UPDATE secrets
                            SET severity_score = :score, severity_bucket = :bucket
                            WHERE id = :id
                        """),
                        {
                            "score": severity.score,
                            "bucket": severity.bucket,
                            "id": secret_id,
                        },
                    )

                # ── 6. Update investigation to complete ────────────────────────
                coverage_json = None
                if graph_data and graph_data.coverage:
                    from dataclasses import asdict
                    coverage_json = json.dumps(asdict(graph_data.coverage))

                await db.execute(
                    text("""
                        UPDATE investigations
                        SET
                            status       = 'complete',
                            finished_at  = now(),
                            coverage     = CAST(:coverage AS jsonb)
                        WHERE id = :id
                    """),
                    {"id": investigation_id, "coverage": coverage_json},
                )

                # ── 7. Audit ───────────────────────────────────────────────────
                await audit(
                    db,
                    workspace_id=workspace_id,
                    actor="system",
                    action="investigation.complete",
                    target_type="investigation",
                    target_id=investigation_id,
                    after={
                        "status": "complete",
                        "score": severity.score if severity else None,
                        "bucket": severity.bucket if severity else None,
                    },
                )

        # ── 8. Publish complete event ──────────────────────────────────────────
        await publish_event(workspace_id, "investigation.complete", {
            "investigation_id": investigation_id,
            "secret_id": secret_id,
            "score": severity.score if severity else None,
            "bucket": severity.bucket if severity else None,
        })

        log.info(
            "investigate_secret.complete",
            score=severity.score if severity else None,
            bucket=severity.bucket if severity else None,
            nodes=len(graph_data.nodes) if graph_data else 0,
        )
        return {
            "investigation_id": investigation_id,
            "score": severity.score if severity else None,
            "bucket": severity.bucket if severity else None,
        }

    except Exception as exc:
        log.exception("investigate_secret.error", error=str(exc))

        # Mark investigation as error
        try:
            async with async_session_maker() as db:
                async with db.begin():
                    await db.execute(
                        text("""
                            UPDATE investigations
                            SET status = 'error', finished_at = now()
                            WHERE id = :id
                        """),
                        {"id": investigation_id},
                    )
                    await audit(
                        db,
                        workspace_id=workspace_id,
                        actor="system",
                        action="investigation.error",
                        target_type="investigation",
                        target_id=investigation_id,
                        after={"status": "error", "error": str(exc)},
                    )
        except Exception as inner_exc:
            log.error("investigate_secret.error_handling_failed", inner_error=str(inner_exc))

        await publish_event(workspace_id, "investigation.error", {
            "investigation_id": investigation_id,
            "secret_id": secret_id,
            "error": str(exc),
        })
        raise


_ENV_CANONICAL = {"production": "prod", "staging": "staging", "dev": "dev", "development": "dev"}

def _canonical_env(env: str) -> str:
    """Map free-text environment strings to the Postgres enum values."""
    return _ENV_CANONICAL.get(env.lower(), "unknown")


def _init_trace(investigation_id: str, secret_id: str, workspace_id: str) -> str | None:
    """Create a Langfuse trace; return the trace ID or None if Langfuse is unconfigured."""
    if not worker_settings.langfuse_public_key:
        return None
    try:
        from langfuse import Langfuse
        lf = Langfuse(
            public_key=worker_settings.langfuse_public_key,
            secret_key=worker_settings.langfuse_secret_key,
            host=worker_settings.langfuse_host,
        )
        trace = lf.trace(
            name="investigate_secret",
            metadata={
                "investigation_id": investigation_id,
                "secret_id": secret_id,
                "workspace_id": workspace_id,
            },
        )
        return trace.id
    except Exception as exc:
        logger.warning("langfuse.trace_init_failed", error=str(exc))
        return None
