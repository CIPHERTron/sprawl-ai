"use client";

import type { Secret, SeverityBucket } from "@/types/api";
import { cn } from "@/lib/utils";
import { AlertTriangleIcon, ChevronRightIcon, ShieldIcon } from "lucide-react";
import Link from "next/link";

function bucketStyle(b: SeverityBucket | null | undefined) {
  return {
    critical: "bg-red-500/15 text-red-300 ring-red-500/30",
    high:     "bg-orange-500/15 text-orange-300 ring-orange-500/30",
    medium:   "bg-amber-500/15 text-amber-300 ring-amber-500/30",
    low:      "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  }[b ?? "low"] ?? "bg-white/5 text-white/40 ring-white/10";
}

function envDot(env: string) {
  return { prod: "bg-red-400", staging: "bg-amber-400", dev: "bg-emerald-400" }[env] ?? "bg-white/25";
}

interface SecretCardProps {
  secret: Secret;
  workspaceId: string;
}

export function SecretCard({ secret, workspaceId }: SecretCardProps) {
  return (
    <Link
      href={`/workspace/${workspaceId}/secrets/${secret.id}/graph`}
      className="group flex items-center gap-4 rounded-xl border border-white/8 bg-[#0f0f0f] px-4 py-3.5 transition-colors hover:border-white/15 hover:bg-white/3"
    >
      {/* Icon */}
      <div className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ring-1",
        secret.health === "exposed"
          ? "bg-red-500/10 ring-red-500/30"
          : "bg-white/5 ring-white/10"
      )}>
        {secret.health === "exposed" ? (
          <AlertTriangleIcon className="h-4.5 w-4.5 text-red-400" />
        ) : (
          <ShieldIcon className="h-4.5 w-4.5 text-white/40" />
        )}
      </div>

      {/* Meta */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-white/85">
            {secret.type.replace(/_/g, " ")}
          </span>
          <span className={cn("rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 shrink-0", bucketStyle(secret.severity_bucket))}>
            {secret.severity_bucket ?? "unknown"}
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/35">
          <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", envDot(secret.environment))} />
          <span className="capitalize">{secret.environment}</span>
          <span className="opacity-40">·</span>
          <span className="capitalize">{secret.exposure_status.replace(/_/g, " ")}</span>
        </div>
      </div>

      {/* Score */}
      {secret.severity_score != null && (
        <span className="shrink-0 text-sm font-semibold tabular-nums text-white/40">
          {secret.severity_score}
        </span>
      )}

      <ChevronRightIcon className="h-4 w-4 shrink-0 text-white/20 transition-colors group-hover:text-white/50" />
    </Link>
  );
}
