"use client";

import type { AuditEntry } from "@/types/api";
import { listAuditEvents } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { useWorkspaceSSE } from "@/lib/use-sse";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ActivityIcon, ShieldCheckIcon } from "lucide-react";
import { use } from "react";

interface PageProps {
  params: Promise<{ workspaceId: string }>;
}

const ACTION_COLORS: Record<string, string> = {
  "rotation.approved":        "text-emerald-400",
  "rotation.rejected":        "text-red-400",
  "rotation.triggered":       "text-blue-400",
  "rotation.completed":       "text-emerald-400",
  "rotation.rolled_back":     "text-orange-400",
  "rotation.step.confirmed":  "text-yellow-400",
  "rotation.step.executed":   "text-blue-300",
  "rotation.step.failed":     "text-red-400",
};

function actionColor(action: string): string {
  if (ACTION_COLORS[action]) return ACTION_COLORS[action];
  if (action.startsWith("rotation.")) return "text-white/60";
  if (action.includes("scan")) return "text-purple-400";
  return "text-white/50";
}

function RelativeTime({ iso }: { iso: string }) {
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60_000);
  const hrs  = Math.floor(diff / 3_600_000);

  const relative =
    mins < 1   ? "just now"
    : mins < 60 ? `${mins}m ago`
    : hrs < 24  ? `${hrs}h ago`
    : d.toLocaleDateString();

  return (
    <time dateTime={iso} title={d.toLocaleString()} className="shrink-0">
      {relative}
    </time>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  return (
    <div className="flex items-start gap-3 border-b border-white/4 px-5 py-3 hover:bg-white/2 transition-colors">
      {/* Action dot */}
      <div className="mt-1 shrink-0">
        <span className={`inline-block h-1.5 w-1.5 rounded-full bg-current ${actionColor(entry.action)}`} />
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className={`text-xs font-medium ${actionColor(entry.action)}`}>
            {entry.action}
          </span>
          {entry.target_id && (
            <span className="truncate font-mono text-[10px] text-white/25">
              {entry.target_type} {entry.target_id.slice(0, 8)}…
            </span>
          )}
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/30">
          <span className="truncate font-mono">{entry.actor}</span>
          <span className="opacity-40">·</span>
          <RelativeTime iso={entry.created_at} />
          <span className="opacity-40">·</span>
          <span className="font-mono text-[10px] text-white/20">{entry.hash.slice(0, 12)}…</span>
        </div>
      </div>
    </div>
  );
}

export default function AuditPage({ params }: PageProps) {
  const { workspaceId } = use(params);
  const token = useAuthStore((s) => s.token)!;
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["audit", workspaceId],
    queryFn: () => listAuditEvents(workspaceId, token),
    refetchInterval: 15_000,
    enabled: !!token,
  });

  // Refresh on new audit events via SSE
  useWorkspaceSSE(workspaceId, token, (event) => {
    if (event.type?.startsWith("audit.") || event.type?.startsWith("rotation.")) {
      queryClient.invalidateQueries({ queryKey: ["audit", workspaceId] });
    }
  });

  const entries: AuditEntry[] = data?.data ?? [];

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-8">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2.5">
          <ActivityIcon className="h-5 w-5 text-white/40" />
          <h1 className="text-xl font-semibold text-white">Audit Log</h1>
        </div>
        <p className="mt-1 text-sm text-white/40">
          Append-only, hash-chained record of all workspace actions.
        </p>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-white/40">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-white/60" />
          Loading…
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-300">
          {error.message}
        </div>
      )}

      {!isLoading && entries.length === 0 && !error && (
        <div className="flex flex-col items-center gap-3 py-16 text-center text-white/25">
          <ShieldCheckIcon className="h-8 w-8 opacity-40" />
          <p className="text-sm">No audit events yet.</p>
          <p className="text-[11px]">Events are recorded when you trigger rotations, approve plans, and confirm steps.</p>
        </div>
      )}

      {entries.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-white/6 bg-[#0f0f0f]">
          {/* Column header */}
          <div className="flex items-center gap-3 border-b border-white/6 bg-white/2 px-5 py-2">
            <div className="w-2 shrink-0" />
            <div className="flex-1 text-[10px] font-semibold uppercase tracking-widest text-white/20">
              Action
            </div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-white/20">
              Time
            </div>
          </div>

          {entries.map((e) => (
            <AuditRow key={e.id} entry={e} />
          ))}

          <div className="flex items-center justify-between border-t border-white/4 px-5 py-2.5 text-[11px] text-white/25">
            <span>{entries.length} of {data?.meta.total ?? entries.length} events</span>
            <span className="flex items-center gap-1">
              <ShieldCheckIcon className="h-3 w-3" />
              SHA-256 hash chain
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
