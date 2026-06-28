"use client";

import type { Rotation, RotationPlanStep, RotationStep, StepKind } from "@/types/api";
import { cn } from "@/lib/utils";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { confirmStep } from "@/lib/api";
import {
  CheckIcon,
  CircleIcon,
  ClockIcon,
  LoaderIcon,
  PackageIcon,
  RefreshCwIcon,
  SendIcon,
  ShieldCheckIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";

// ── Step kind display ──────────────────────────────────────────────────────────
const KIND_META: Record<StepKind, { label: string; icon: React.ElementType; color: string }> = {
  provision: { label: "Provision",  icon: PackageIcon,     color: "text-blue-400" },
  distribute:{ label: "Distribute", icon: SendIcon,        color: "text-purple-400" },
  verify:    { label: "Verify",     icon: ShieldCheckIcon, color: "text-cyan-400" },
  revoke:    { label: "Revoke",     icon: Trash2Icon,      color: "text-orange-400" },
};

// ── Step status icons ──────────────────────────────────────────────────────────
function StepIcon({ status, isActive }: { status: RotationStep["status"] | "waiting"; isActive?: boolean }) {
  if (isActive) {
    return <LoaderIcon className="h-4 w-4 animate-spin text-blue-400" />;
  }
  switch (status) {
    case "done":
      return <CheckIcon className="h-4 w-4 text-emerald-400" />;
    case "failed":
      return <XIcon className="h-4 w-4 text-red-400" />;
    case "compensated":
      return <RefreshCwIcon className="h-4 w-4 text-orange-400" />;
    case "waiting":
      return <ClockIcon className="h-4 w-4 text-yellow-400" />;
    default:
      return <CircleIcon className="h-4 w-4 text-white/20" />;
  }
}

// ── Individual step row ────────────────────────────────────────────────────────
interface StepRowProps {
  planStep: RotationPlanStep;
  execStep: RotationStep | undefined;
  isNext: boolean;
  isActive: boolean;
  workspaceId: string;
  rotationId: string;
  token: string;
}

function StepRow({
  planStep,
  execStep,
  isNext,
  isActive,
  workspaceId,
  rotationId,
  token,
}: StepRowProps) {
  const queryClient = useQueryClient();

  const confirmMutation = useMutation({
    mutationFn: () => confirmStep(workspaceId, rotationId, execStep!.id, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rotation", workspaceId, rotationId] });
      queryClient.invalidateQueries({ queryKey: ["rotations", workspaceId] });
    },
  });

  const kind = planStep.kind;
  const meta = KIND_META[kind];
  const KindIcon = meta.icon;

  const stepStatus = execStep?.status ?? "pending";
  const needsConfirm =
    execStep?.requires_confirmation &&
    stepStatus === "pending" &&
    isNext;

  const displayStatus: "done" | "failed" | "compensated" | "waiting" | "pending" =
    needsConfirm ? "waiting" : stepStatus as "done" | "failed" | "compensated" | "pending";

  return (
    <div
      className={cn(
        "flex gap-3 rounded-lg border px-4 py-3 transition-colors",
        stepStatus === "done"
          ? "border-emerald-500/15 bg-emerald-500/5"
          : stepStatus === "failed"
          ? "border-red-500/20 bg-red-500/5"
          : stepStatus === "compensated"
          ? "border-orange-500/20 bg-orange-500/5"
          : needsConfirm
          ? "border-yellow-500/25 bg-yellow-500/5"
          : isActive
          ? "border-blue-500/20 bg-blue-500/5"
          : "border-white/5 bg-white/2"
      )}
    >
      {/* Status icon */}
      <div className="mt-0.5 shrink-0">
        <StepIcon status={displayStatus} isActive={isActive} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <KindIcon className={cn("h-3.5 w-3.5 shrink-0", meta.color)} />
          <span className="text-sm font-medium text-white/85">{meta.label}</span>
          {execStep?.executed_at && (
            <span className="ml-auto text-[11px] text-white/30 shrink-0">
              {new Date(execStep.executed_at).toLocaleTimeString()}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[12px] text-white/45 leading-relaxed">
          {planStep.description}
        </p>

        {/* Error */}
        {execStep?.error && (
          <p className="mt-1.5 rounded border border-red-500/20 bg-red-500/10 px-2 py-1 text-[11px] text-red-300">
            {execStep.error}
          </p>
        )}

        {/* Confirm button */}
        {needsConfirm && (
          <button
            onClick={() => confirmMutation.mutate()}
            disabled={confirmMutation.isPending}
            className="mt-2 flex items-center gap-1.5 rounded-md bg-yellow-500/20 px-3 py-1.5 text-xs font-medium text-yellow-200 ring-1 ring-yellow-500/30 transition-colors hover:bg-yellow-500/30 disabled:opacity-50"
          >
            {confirmMutation.isPending ? (
              <LoaderIcon className="h-3 w-3 animate-spin" />
            ) : (
              <CheckIcon className="h-3 w-3" />
            )}
            Confirm this step
          </button>
        )}
      </div>
    </div>
  );
}

// ── Full step timeline ─────────────────────────────────────────────────────────
interface StepTimelineProps {
  rotation: Rotation;
  workspaceId: string;
  token: string;
}

export function StepTimeline({ rotation, workspaceId, token }: StepTimelineProps) {
  const planSteps = rotation.plan?.steps ?? [];
  const execSteps = rotation.steps ?? [];

  // Index exec steps by their idx field
  const execByIdx = new Map<number, RotationStep>(
    execSteps.map((s) => [s.idx, s])
  );

  // Find the first pending step
  const firstPendingIdx = planSteps.findIndex((ps) => {
    const es = execByIdx.get(ps.idx);
    return !es || es.status === "pending";
  });

  const activeStatuses = new Set([
    "provisioning", "distributing", "verifying", "revoking", "rolling_back",
  ]);
  const isEngineActive = activeStatuses.has(rotation.status);

  return (
    <div className="space-y-2">
      {planSteps.map((ps, i) => {
        const execStep = execByIdx.get(ps.idx ?? i);
        const isNext = (ps.idx ?? i) === firstPendingIdx;
        const isActive = isEngineActive && isNext;

        return (
          <StepRow
            key={ps.idx ?? i}
            planStep={ps}
            execStep={execStep}
            isNext={isNext}
            isActive={isActive}
            workspaceId={workspaceId}
            rotationId={rotation.id}
            token={token}
          />
        );
      })}

      {planSteps.length === 0 && (
        <p className="text-sm text-white/30">No steps in plan.</p>
      )}
    </div>
  );
}
