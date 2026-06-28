import type { RotationStatus } from "@/types/api";
import { cn } from "@/lib/utils";

const STATUS_CONFIG: Record<
  RotationStatus,
  { label: string; className: string }
> = {
  proposed:               { label: "Proposed",              className: "bg-white/8 text-white/50 ring-white/10" },
  plan_failed:            { label: "Plan Failed",           className: "bg-red-500/15 text-red-400 ring-red-500/30" },
  pending_approval:       { label: "Pending Approval",      className: "bg-amber-500/15 text-amber-300 ring-amber-500/30" },
  provisioning:           { label: "Provisioning",          className: "bg-blue-500/15 text-blue-300 ring-blue-500/30" },
  distributing:           { label: "Distributing",          className: "bg-blue-500/15 text-blue-300 ring-blue-500/30" },
  verifying:              { label: "Verifying",             className: "bg-blue-500/15 text-blue-300 ring-blue-500/30" },
  awaiting_confirmation:  { label: "Awaiting Confirmation", className: "bg-yellow-500/15 text-yellow-300 ring-yellow-500/30" },
  revoking:               { label: "Revoking",              className: "bg-orange-500/15 text-orange-300 ring-orange-500/30" },
  completed:              { label: "Completed",             className: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30" },
  rolling_back:           { label: "Rolling Back",          className: "bg-orange-500/15 text-orange-300 ring-orange-500/30" },
  rolled_back:            { label: "Rolled Back",           className: "bg-white/8 text-white/50 ring-white/10" },
  rollback_failed:        { label: "Rollback Failed",       className: "bg-red-500/15 text-red-400 ring-red-500/30" },
  rejected:               { label: "Rejected",              className: "bg-white/8 text-white/40 ring-white/10" },
  needs_replan:           { label: "Needs Replan",          className: "bg-amber-500/15 text-amber-300 ring-amber-500/30" },
  abandoned:              { label: "Abandoned",             className: "bg-white/8 text-white/30 ring-white/10" },
};

interface Props {
  status: RotationStatus;
  size?: "sm" | "md";
}

export function RotationStatusBadge({ status, size = "md" }: Props) {
  const config = STATUS_CONFIG[status] ?? {
    label: status,
    className: "bg-white/5 text-white/40 ring-white/10",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full font-medium ring-1",
        size === "sm"
          ? "px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
          : "px-2 py-0.5 text-xs",
        config.className
      )}
    >
      {config.label}
    </span>
  );
}

/** Returns true for statuses where the rotation is in active execution. */
export function isActiveStatus(status: RotationStatus): boolean {
  return ["provisioning", "distributing", "verifying", "revoking", "rolling_back"].includes(status);
}

/** Returns true for terminal (no further transitions) statuses. */
export function isTerminalStatus(status: RotationStatus): boolean {
  return ["completed", "rolled_back", "rollback_failed", "rejected", "abandoned", "plan_failed"].includes(status);
}
