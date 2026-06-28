"""
LangGraph StateGraph for the investigation pipeline.

Graph structure:
    ingest → triage → [investigator → blast_radius → severity]
                   ↘→ END  (if routing == "skip")

Checkpointing:
    Uses AsyncPostgresSaver (psycopg3) with thread_id = investigation_id.
    PostgresSaver.setup() is called once at worker startup (idempotent DDL).

Usage:
    from worker.agents.graph import build_graph, setup_checkpointer

    await setup_checkpointer()            # once at startup
    graph = await build_graph(conninfo)   # per-investigation
    result = await graph.ainvoke(initial_state, config={...})
"""
from __future__ import annotations

import structlog

from langgraph.graph import END, StateGraph

from worker.agents.nodes import (
    blast_radius_node,
    ingest_node,
    investigator_node,
    severity_node,
    triage_node,
)
from worker.agents.state import InvestigationState

logger = structlog.get_logger(__name__)


def _triage_router(state: InvestigationState) -> str:
    """Conditional edge: route after triage based on state["routing"]."""
    routing = state.get("routing", "investigate")
    return routing  # "investigate" → investigator, "skip" → END


def compile_graph(checkpointer=None) -> StateGraph:
    """
    Build and compile the investigation StateGraph.

    Args:
        checkpointer: Optional LangGraph checkpointer (AsyncPostgresSaver).
                      Pass None for stateless (testing / no-persistence) runs.

    Returns:
        Compiled LangGraph Runnable.
    """
    builder = StateGraph(InvestigationState)

    # ── Nodes ──────────────────────────────────────────────────────────────────
    builder.add_node("ingest", ingest_node)
    builder.add_node("triage", triage_node)
    builder.add_node("investigator", investigator_node)
    builder.add_node("blast_radius", blast_radius_node)
    builder.add_node("severity", severity_node)

    # ── Edges ──────────────────────────────────────────────────────────────────
    builder.set_entry_point("ingest")
    builder.add_edge("ingest", "triage")

    # Conditional: triage → investigator OR END
    builder.add_conditional_edges(
        "triage",
        _triage_router,
        {
            "investigate": "investigator",
            "skip": END,
        },
    )

    builder.add_edge("investigator", "blast_radius")
    builder.add_edge("blast_radius", "severity")
    builder.add_edge("severity", END)

    # ── Compile ────────────────────────────────────────────────────────────────
    kwargs = {}
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer

    return builder.compile(**kwargs)


async def setup_checkpointer(conninfo: str) -> None:
    """
    Run AsyncPostgresSaver.setup() — creates the checkpoint tables if missing.
    This is idempotent and should be called once at worker startup.
    """
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        async with AsyncPostgresSaver.from_conn_string(conninfo) as saver:
            await saver.setup()
        logger.info("langgraph.checkpointer.setup_ok")
    except Exception as exc:
        # Non-fatal: investigation can run with MemorySaver fallback
        logger.warning("langgraph.checkpointer.setup_failed", error=str(exc))


async def make_checkpointer(conninfo: str):
    """
    Create and return an AsyncPostgresSaver context manager.
    Callers should use as an async context manager:

        async with make_checkpointer(conninfo) as cp:
            graph = compile_graph(checkpointer=cp)
            await graph.ainvoke(...)
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    return AsyncPostgresSaver.from_conn_string(conninfo)
