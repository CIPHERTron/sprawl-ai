"use client";

import type { Rotation } from "@/types/api";
import { listRotations } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { RotationStatusBadge } from "@/components/rotation/rotation-status-badge";
import { RotationPanel } from "@/components/rotation/rotation-panel";
import { useWorkspaceSSE } from "@/lib/use-sse";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCwIcon } from "lucide-react";
import { use, useEffect, useState } from "react";
import Link from "next/link";

interface PageProps {
  params: Promise<{ workspaceId: string }>;
}

function RelativeTime({ iso }: { iso: string }) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  const hrs  = Math.floor(diff / 3_600_000);
  const days = Math.floor(diff / 86_400_000);
  const label =
    mins < 1   ? "just now"
    : mins < 60 ? `${mins}m ago`
    : hrs < 24  ? `${hrs}h ago`
    : `${days}d ago`;
  return <span>{label}</span>;
}

interface RotationCardProps {
  rotation: Rotation;
  selected: boolean;
  onClick: () => void;
}

function RotationCard({ rotation, selected, onClick }: RotationCardProps) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-xl border px-4 py-3.5 transition-colors ${
        selected
          ? "border-white/20 bg-white/6"
          : "border-white/6 bg-[#0f0f0f] hover:border-white/12 hover:bg-white/3"
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/5 ring-1 ring-white/10">
          <RefreshCwIcon className="h-3.5 w-3.5 text-white/40" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-white/85">
              {rotation.secret_type
                ? rotation.secret_type.replace(/_/g, " ")
                : "Secret Rotation"}
            </span>
            <RotationStatusBadge status={rotation.status} size="sm" />
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-white/30">
            <span className="font-mono">{rotation.id.slice(0, 8)}…</span>
            <span className="opacity-40">·</span>
            <RelativeTime iso={rotation.created_at} />
          </div>
        </div>
      </div>
    </button>
  );
}

export default function RotationsPage({ params }: PageProps) {
  const { workspaceId } = use(params);
  const token     = useAuthStore((s) => s.token)!;
  const isDemo    = useAuthStore((s) => s.isDemo);
  const sessionId = useAuthStore((s) => s.sessionId);
  const queryClient = useQueryClient();

  const [selectedId, setSelectedId] = useState<string | null>(null);

  // List all rotations
  const { data, isLoading, error } = useQuery({
    queryKey: ["rotations", workspaceId],
    queryFn: () => listRotations(workspaceId, token),
    refetchInterval: 10_000,
    enabled: !!token,
  });

  // Invalidate on any rotation SSE event
  useWorkspaceSSE(workspaceId, token, (event) => {
    if (event.type?.startsWith("rotation.")) {
      queryClient.invalidateQueries({ queryKey: ["rotations", workspaceId] });
      if (selectedId && event.rotation_id === selectedId) {
        queryClient.invalidateQueries({ queryKey: ["rotation", workspaceId, selectedId] });
      }
    }
  });

  const rotations: Rotation[] = data?.data ?? [];

  // Auto-select the first rotation once data loads
  useEffect(() => {
    if (rotations.length > 0 && selectedId === null) {
      setSelectedId(rotations[0].id);
    }
  }, [rotations, selectedId]);

  return (
    <div className="flex h-full min-h-0">
      {/* Left: rotation list */}
      <div className="flex w-80 shrink-0 flex-col border-r border-white/6 overflow-y-auto">
        <div className="sticky top-0 z-10 border-b border-white/6 bg-[#0d0d0d] px-5 py-4">
          <h1 className="text-sm font-semibold text-white">Rotations</h1>
          <p className="mt-0.5 text-[11px] text-white/35">
            {rotations.length} rotation{rotations.length !== 1 ? "s" : ""}
          </p>
        </div>

        <div className="flex-1 space-y-1.5 p-3">
          {isLoading && (
            <div className="flex items-center gap-2 px-2 pt-4 text-sm text-white/30">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/15 border-t-white/50" />
              Loading…
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-red-500/15 bg-red-500/8 p-3 text-[12px] text-red-300">
              {error.message}
            </div>
          )}

          {!isLoading && rotations.length === 0 && (
            <div className="flex flex-col gap-3 px-2 pt-6 text-center">
              <p className="text-sm text-white/30">No rotations yet.</p>
              <p className="text-[11px] text-white/20">
                Trigger a rotation from the{" "}
                <Link
                  href={`/workspace/${workspaceId}/secrets`}
                  className="text-emerald-400/70 hover:text-emerald-400 underline underline-offset-2"
                >
                  secret graph
                </Link>
                .
              </p>
            </div>
          )}

          {rotations.map((r) => (
            <RotationCard
              key={r.id}
              rotation={r}
              selected={selectedId === r.id}
              onClick={() => setSelectedId(r.id)}
            />
          ))}
        </div>
      </div>

      {/* Right: detail panel */}
      <div className="flex-1 overflow-y-auto">
        {selectedId ? (
          <div className="mx-auto max-w-2xl px-8 py-8">
            <RotationPanel
              workspaceId={workspaceId}
              rotationId={selectedId}
              token={token}
              isDemo={isDemo}
              sessionId={sessionId}
              onBack={() => setSelectedId(null)}
            />
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-white/25">
              Select a rotation from the list to see details.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
