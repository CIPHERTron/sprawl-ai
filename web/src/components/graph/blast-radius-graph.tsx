"use client";

import type { BlastRadius, GraphEdge, GraphNode, NodeKind } from "@/types/api";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { SprawlNode, type SprawlNodeType } from "./nodes/sprawl-node";
import { CoverageBanner } from "./coverage-banner";

// ── Node type registry ─────────────────────────────────────────────────────────
const nodeTypes = { sprawlNode: SprawlNode } satisfies Record<string, React.ComponentType<never>>;

// ── Layout ────────────────────────────────────────────────────────────────────
const LEVEL: Record<NodeKind, number> = {
  secret:      0,
  location:    1,
  ci:          1,
  principal:   1,
  store_entry: 2,
  resource:    2,
  environment: 3,
};
const NODE_W = 220;
const NODE_H = 80;
const H_GAP  = 60;
const V_GAP  = 110;

function computeLayout(nodes: GraphNode[]): Map<string, { x: number; y: number }> {
  const byLevel = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const lvl = LEVEL[n.kind] ?? 2;
    if (!byLevel.has(lvl)) byLevel.set(lvl, []);
    byLevel.get(lvl)!.push(n);
  }

  const positions = new Map<string, { x: number; y: number }>();
  for (const [lvl, lvlNodes] of byLevel) {
    const totalW = lvlNodes.length * NODE_W + (lvlNodes.length - 1) * H_GAP;
    lvlNodes.forEach((n, i) => {
      positions.set(n.id, {
        x: i * (NODE_W + H_GAP) - totalW / 2 + NODE_W / 2,
        y: lvl * (NODE_H + V_GAP),
      });
    });
  }
  return positions;
}

// ── Edge style by confidence ──────────────────────────────────────────────────
function edgeStyle(confidence: GraphEdge["confidence"]) {
  if (confidence === "high")   return { strokeDasharray: undefined, strokeOpacity: 0.9, strokeWidth: 2 };
  if (confidence === "medium") return { strokeDasharray: "6 3",     strokeOpacity: 0.7, strokeWidth: 1.5 };
  return                              { strokeDasharray: "2 4",     strokeOpacity: 0.45, strokeWidth: 1 };
}

function EDGE_LABEL(kind: GraphEdge["kind"]) {
  const map: Record<GraphEdge["kind"], string> = {
    found_in:         "found in",
    stored_in:        "stored in",
    is_principal:     "is principal",
    grants_access_to: "grants access to",
    used_by:          "used by",
    can_access:       "can access",
  };
  return map[kind] ?? kind;
}

// ── Converters ────────────────────────────────────────────────────────────────
function toFlowNodes(apiNodes: GraphNode[]): SprawlNodeType[] {
  const positions = computeLayout(apiNodes);
  return apiNodes.map((n) => ({
    id: n.id,
    type: "sprawlNode" as const,
    position: positions.get(n.id) ?? { x: 0, y: 0 },
    data: {
      kind:        n.kind,
      label:       n.label,
      environment: n.environment,
      attrs:       n.attrs,
    },
  }));
}

function toFlowEdges(apiEdges: GraphEdge[]): Edge[] {
  return apiEdges.map((e) => ({
    id:     e.id,
    source: e.src_node_id,
    target: e.dst_node_id,
    label:  EDGE_LABEL(e.kind),
    labelStyle: { fill: "rgba(255,255,255,0.4)", fontSize: 10 },
    labelBgStyle: { fill: "transparent" },
    style: {
      stroke: "#4ade80",
      ...edgeStyle(e.confidence),
    },
    animated: e.confidence === "high",
  }));
}

// ── Main component ─────────────────────────────────────────────────────────────
interface BlastRadiusGraphProps {
  data: BlastRadius;
  isDemo?: boolean;
}

function GraphInner({ data, isDemo }: BlastRadiusGraphProps) {
  const nodes = toFlowNodes(data.nodes);
  const edges = toFlowEdges(data.edges);

  return (
    <div className="relative flex h-full w-full flex-col">
      {/* Coverage banner + Demo badge */}
      <div className="flex items-center gap-3 border-b border-white/8 bg-[#0d0d0d] px-4 py-2">
        <div className="min-w-0 flex-1">
          <CoverageBanner
            secret={data.secret}
            coverage={data.coverage}
          />
        </div>
        {isDemo && (
          <span className="shrink-0 rounded-full bg-amber-500/15 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-amber-400">
            Demo workspace
          </span>
        )}
      </div>

      {/* React Flow canvas */}
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          minZoom={0.3}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
          style={{ background: "#0a0a0a" }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={24}
            size={1}
            color="rgba(255,255,255,0.06)"
          />
          <Controls
            style={{
              background: "#1a1a1a",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 8,
            }}
          />
        </ReactFlow>
      </div>
    </div>
  );
}

export function BlastRadiusGraph(props: BlastRadiusGraphProps) {
  return (
    <ReactFlowProvider>
      <GraphInner {...props} />
    </ReactFlowProvider>
  );
}
