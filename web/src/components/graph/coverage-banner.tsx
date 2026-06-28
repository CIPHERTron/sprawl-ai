"use client";

import type { Coverage, Secret, SeverityBucket } from "@/types/api";
import { cn } from "@/lib/utils";
import { AlertTriangleIcon, CheckCircle2Icon, ShieldIcon } from "lucide-react";

function severityColors(bucket: SeverityBucket | null | undefined) {
  const map = {
    critical: { bg: "bg-red-500/15",    text: "text-red-300",    ring: "ring-red-500/40"    },
    high:     { bg: "bg-orange-500/15", text: "text-orange-300", ring: "ring-orange-500/40" },
    medium:   { bg: "bg-amber-500/15",  text: "text-amber-300",  ring: "ring-amber-500/40"  },
    low:      { bg: "bg-emerald-500/15",text: "text-emerald-300",ring: "ring-emerald-500/40"},
  };
  return map[bucket ?? "low"];
}

interface CoverageBannerProps {
  secret: Secret;
  coverage: Coverage | null | undefined;
}

export function CoverageBanner({ secret, coverage }: CoverageBannerProps) {
  const sc = severityColors(secret.severity_bucket);
  const isExposed = secret.health === "exposed";

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {/* Health indicator */}
      <div className="flex items-center gap-1.5">
        {isExposed ? (
          <AlertTriangleIcon className="h-3.5 w-3.5 text-red-400" />
        ) : (
          <CheckCircle2Icon className="h-3.5 w-3.5 text-emerald-400" />
        )}
        <span className={cn("text-xs font-medium", isExposed ? "text-red-300" : "text-emerald-300")}>
          {secret.health.replace("_", " ")}
        </span>
      </div>

      {/* Severity */}
      {secret.severity_bucket && (
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1", sc.bg, sc.text, sc.ring)}>
          {secret.severity_bucket}
          {secret.severity_score != null && ` · ${secret.severity_score}`}
        </span>
      )}

      {/* Secret type */}
      <div className="flex items-center gap-1.5 text-white/40">
        <ShieldIcon className="h-3 w-3" />
        <span className="text-[11px]">{secret.type.replace(/_/g, " ")}</span>
      </div>

      {/* Coverage */}
      {coverage && (
        <div className="flex items-center gap-1 text-[11px] text-white/40">
          <span className="text-white/60 font-medium">{coverage.known_consumers}</span> known consumer{coverage.known_consumers !== 1 && "s"}
          {coverage.unknown_consumers > 0 && (
            <>
              <span className="mx-0.5 opacity-30">·</span>
              <span className="text-amber-400/80 font-medium">{coverage.unknown_consumers}</span> unknown
            </>
          )}
        </div>
      )}
    </div>
  );
}
