"use client";

import type { Rotation, RotationStatus } from "@/types/api";
import { approveRotation, getRotation, rejectRotation, simulateFailure } from "@/lib/api";
import { isTerminalStatus, RotationStatusBadge } from "./rotation-status-badge";
import { StepTimeline } from "./step-timeline";
import { useWorkspaceSSE } from "@/lib/use-sse";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangleIcon, ArrowLeftIcon, LoaderIcon, ZapIcon } from "lucide-react";

interface Props {
  workspaceId: string;
  rotationId: string;
  sessionId: string | null;
  token: string;
  isDemo: boolean;
  onBack?: () => void;
}

export function RotationPanel({
  workspaceId,
  rotationId,
  sessionId,
  token,
  isDemo,
  onBack,
}: Props) {
  const queryClient = useQueryClient();

  // ── Data ────────────────────────────────────────────────────────────────────
  const { data, isLoading, error } = useQuery({
    queryKey: ["rotation", workspaceId, rotationId],
    queryFn: () => getRotation(workspaceId, rotationId, token),
    // Poll every 4 s as SSE fallback; disable once terminal
    refetchInterval: (q) => {
      const s = q.state.data?.data?.status as RotationStatus | undefined;
      return s && isTerminalStatus(s) ? false : 4_000;
    },
    enabled: !!token,
  });

  // ── SSE live refresh ────────────────────────────────────────────────────────
  useWorkspaceSSE(workspaceId, token, (event) => {
    if (
      event.type?.startsWith("rotation.") &&
      (event.rotation_id === rotationId || !event.rotation_id)
    ) {
      queryClient.invalidateQueries({ queryKey: ["rotation", workspaceId, rotationId] });
      queryClient.invalidateQueries({ queryKey: ["rotations", workspaceId] });
    }
  });

  // ── Mutations ───────────────────────────────────────────────────────────────
  const approveMutation = useMutation({
    mutationFn: () => approveRotation(workspaceId, rotationId, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rotation", workspaceId, rotationId] });
      queryClient.invalidateQueries({ queryKey: ["rotations", workspaceId] });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () => rejectRotation(workspaceId, rotationId, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rotation", workspaceId, rotationId] });
      queryClient.invalidateQueries({ queryKey: ["rotations", workspaceId] });
    },
  });

  const simFailMutation = useMutation({
    mutationFn: () => simulateFailure(sessionId!, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rotation", workspaceId, rotationId] });
      queryClient.invalidateQueries({ queryKey: ["rotations", workspaceId] });
    },
  });

  // ── Render ──────────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <LoaderIcon className="h-5 w-5 animate-spin text-white/30" />
      </div>
    );
  }

  if (error || !data?.data) {
    return (
      <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-300">
        {error?.message ?? "Failed to load rotation."}
      </div>
    );
  }

  const rotation = data.data;
  const plan = rotation.plan;
  const coverage = rotation.coverage ?? plan?.coverage;
  const hasUnknownConsumers = (coverage?.unknown_consumers ?? 0) > 0;
  const terminal = isTerminalStatus(rotation.status);
  const canApprove = rotation.status === "pending_approval";
  const canReject = ["pending_approval", "awaiting_confirmation"].includes(rotation.status);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start gap-3">
        {onBack && (
          <button
            onClick={onBack}
            className="mt-0.5 rounded-md p-1 text-white/40 hover:bg-white/5 hover:text-white/70 transition-colors"
          >
            <ArrowLeftIcon className="h-4 w-4" />
          </button>
        )}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-white/85">
              {rotation.secret_type
                ? rotation.secret_type.replace(/_/g, " ")
                : "Secret Rotation"}
            </h2>
            <RotationStatusBadge status={rotation.status} />
            {!terminal && (
              <span className="ml-auto flex items-center gap-1 text-[11px] text-white/30">
                <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                Live
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-white/30">
            {rotationId} &middot; {new Date(rotation.created_at).toLocaleString()}
          </p>
        </div>
      </div>

      {/* Coverage warning */}
      {hasUnknownConsumers && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/8 px-3 py-2.5">
          <AlertTriangleIcon className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <div className="text-[12px] text-amber-200/80">
            <span className="font-medium">{coverage!.unknown_consumers} unknown consumer(s)</span>
            {" "}detected. The revoke gate will block until you confirm you&rsquo;ve notified them.
          </div>
        </div>
      )}

      {/* Plan summary */}
      {plan?.summary && (
        <div className="rounded-lg border border-white/6 bg-white/2 px-3 py-2.5">
          <p className="text-[11px] font-medium uppercase tracking-wide text-white/25">
            Plan · {plan.steps.length} steps
          </p>
          <p className="mt-1 text-[12px] text-white/55 leading-relaxed">{plan.summary}</p>
          {plan.created_by && (
            <p className="mt-1.5 text-[10px] text-white/25">
              by {plan.created_by} · model {plan.model}
            </p>
          )}
        </div>
      )}

      {/* Step timeline */}
      {plan && plan.steps.length > 0 && (
        <StepTimeline rotation={rotation} workspaceId={workspaceId} token={token} />
      )}

      {/* Plan error */}
      {rotation.plan_error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/8 px-3 py-2.5 text-[12px] text-red-300">
          <span className="font-medium">Plan error:</span> {rotation.plan_error}
        </div>
      )}

      {/* Action bar */}
      {!terminal && (
        <div className="flex flex-wrap items-center gap-2 border-t border-white/6 pt-4">
          {canApprove && (
            <button
              onClick={() => approveMutation.mutate()}
              disabled={approveMutation.isPending}
              className="flex items-center gap-1.5 rounded-md bg-emerald-500/20 px-4 py-2 text-sm font-medium text-emerald-300 ring-1 ring-emerald-500/30 transition-colors hover:bg-emerald-500/30 disabled:opacity-50"
            >
              {approveMutation.isPending ? (
                <LoaderIcon className="h-3.5 w-3.5 animate-spin" />
              ) : null}
              Approve &amp; Run
            </button>
          )}

          {canReject && (
            <button
              onClick={() => rejectMutation.mutate()}
              disabled={rejectMutation.isPending}
              className="flex items-center gap-1.5 rounded-md bg-white/5 px-4 py-2 text-sm font-medium text-white/50 ring-1 ring-white/10 transition-colors hover:bg-white/8 hover:text-white/70 disabled:opacity-50"
            >
              {rejectMutation.isPending ? (
                <LoaderIcon className="h-3.5 w-3.5 animate-spin" />
              ) : null}
              Reject
            </button>
          )}

          {/* Demo-only: simulate failure */}
          {isDemo && sessionId && canApprove && (
            <button
              onClick={() => simFailMutation.mutate()}
              disabled={simFailMutation.isPending}
              className="ml-auto flex items-center gap-1.5 rounded-md bg-red-500/10 px-3 py-2 text-xs font-medium text-red-400 ring-1 ring-red-500/20 transition-colors hover:bg-red-500/18 disabled:opacity-50"
              title="Injects a verify-step failure to demonstrate auto-rollback"
            >
              <ZapIcon className="h-3 w-3" />
              {simFailMutation.isPending ? "Injecting…" : "Simulate Failure"}
            </button>
          )}
        </div>
      )}

      {/* Mutation errors */}
      {approveMutation.error && (
        <p className="text-[12px] text-red-400">{approveMutation.error.message}</p>
      )}
      {rejectMutation.error && (
        <p className="text-[12px] text-red-400">{rejectMutation.error.message}</p>
      )}
    </div>
  );
}
