"use client";

import { cn } from "@/lib/utils";
import type { Environment, NodeKind } from "@/types/api";
import {
  ActivityIcon,
  DatabaseIcon,
  GlobeIcon,
  KeyRoundIcon,
  ServerIcon,
  ShieldIcon,
  UserIcon,
} from "lucide-react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

// ── Colour helpers ─────────────────────────────────────────────────────────────
export function envColors(env: Environment) {
  return {
    prod:    { ring: "ring-red-500/40",    bg: "bg-red-500/10",    text: "text-red-300",    dot: "bg-red-400"     },
    staging: { ring: "ring-amber-500/40",  bg: "bg-amber-500/10",  text: "text-amber-300",  dot: "bg-amber-400"   },
    dev:     { ring: "ring-emerald-500/40",bg: "bg-emerald-500/10",text: "text-emerald-300",dot: "bg-emerald-400" },
    unknown: { ring: "ring-white/10",      bg: "bg-white/5",       text: "text-white/50",   dot: "bg-white/30"    },
  }[env] ?? { ring: "ring-white/10", bg: "bg-white/5", text: "text-white/50", dot: "bg-white/30" };
}

export function kindIcon(kind: NodeKind) {
  const icons: Record<NodeKind, React.ElementType> = {
    secret:      KeyRoundIcon,
    principal:   UserIcon,
    resource:    DatabaseIcon,
    environment: GlobeIcon,
    location:    ServerIcon,
    ci:          ActivityIcon,
    store_entry: ShieldIcon,
  };
  return icons[kind] ?? ServerIcon;
}

export function kindColors(kind: NodeKind) {
  const map: Record<NodeKind, { ring: string; bg: string; icon: string }> = {
    secret:      { ring: "ring-red-500/50",     bg: "bg-red-500/12",     icon: "text-red-400"     },
    principal:   { ring: "ring-blue-500/40",    bg: "bg-blue-500/10",    icon: "text-blue-400"    },
    resource:    { ring: "ring-amber-500/40",   bg: "bg-amber-500/10",   icon: "text-amber-400"   },
    environment: { ring: "ring-emerald-500/40", bg: "bg-emerald-500/10", icon: "text-emerald-400" },
    location:    { ring: "ring-white/15",       bg: "bg-white/5",        icon: "text-white/50"    },
    ci:          { ring: "ring-purple-500/40",  bg: "bg-purple-500/10",  icon: "text-purple-400"  },
    store_entry: { ring: "ring-teal-500/40",    bg: "bg-teal-500/10",    icon: "text-teal-400"    },
  };
  return map[kind] ?? map.location;
}

// ── Base graph node ────────────────────────────────────────────────────────────
export type GraphNodeData = {
  kind: NodeKind;
  label: string;
  environment: Environment;
  attrs: Record<string, unknown>;
  isHighlighted?: boolean;
};

// Full React Flow node type — data + discriminant for nodeTypes registry
export type SprawlNodeType = Node<GraphNodeData, "sprawlNode">;

export function SprawlNode({ data, selected }: NodeProps<SprawlNodeType>) {
  const { kind, label, environment, isHighlighted } = data;
  const k = kindColors(kind);
  const e = envColors(environment);
  const Icon = kindIcon(kind);

  return (
    <div
      className={cn(
        "relative min-w-[160px] max-w-[220px] rounded-xl border p-3 shadow-xl transition-all",
        "bg-[#131313] ring-1",
        k.ring,
        selected && "ring-2 ring-white/40",
        isHighlighted && "ring-2 ring-emerald-400/60"
      )}
    >
      <Handle type="target" position={Position.Top} className="bg-white/20! border-white/10!" />

      <div className="flex items-start gap-2.5">
        {/* Kind icon */}
        <div className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", k.bg)}>
          <Icon className={cn("h-3.5 w-3.5", k.icon)} />
        </div>

        <div className="min-w-0 flex-1">
          {/* Kind badge */}
          <div className="mb-1 flex items-center gap-1.5">
            <span className="text-[10px] font-medium uppercase tracking-wide text-white/35">
              {kind.replace("_", " ")}
            </span>
            {/* Environment dot */}
            <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", e.dot)} title={environment} />
          </div>
          {/* Label */}
          <p className="truncate text-xs font-medium text-white/85" title={label}>
            {label}
          </p>
        </div>
      </div>

      <Handle type="source" position={Position.Bottom} className="bg-white/20! border-white/10!" />
    </div>
  );
}
