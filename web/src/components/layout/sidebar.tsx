"use client";

import { cn } from "@/lib/utils";
import {
  ActivityIcon,
  KeyRoundIcon,
  PlugZapIcon,
  RefreshCwIcon,
  ShieldAlertIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { label: "Secrets", href: "secrets", icon: KeyRoundIcon },
  { label: "Findings", href: "findings", icon: ShieldAlertIcon },
  { label: "Rotations", href: "rotations", icon: RefreshCwIcon },
  { label: "Audit", href: "audit", icon: ActivityIcon },
  { label: "Connectors", href: "settings/connectors", icon: PlugZapIcon },
];

interface SidebarProps {
  workspaceId: string;
  isDemo?: boolean;
}

export function Sidebar({ workspaceId, isDemo }: SidebarProps) {
  const pathname = usePathname();
  const base = `/workspace/${workspaceId}`;

  return (
    <aside className="flex h-screen w-56 flex-col border-r border-white/8 bg-[#0d0d0d]">
      {/* Brand */}
      <div className="flex h-14 items-center gap-2.5 border-b border-white/8 px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/15">
          <ShieldAlertIcon className="h-4 w-4 text-emerald-400" />
        </div>
        <span className="text-sm font-semibold text-white">Sprawl AI</span>
        {isDemo && (
          <span className="ml-auto rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-400">
            Demo
          </span>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 px-2 py-3">
        {NAV.map(({ label, href, icon: Icon }) => {
          const to = `${base}/${href}`;
          const active = pathname.startsWith(to);
          return (
            <Link
              key={href}
              href={to}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-white/8 text-white"
                  : "text-white/50 hover:bg-white/5 hover:text-white/80"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-white/8 p-4">
        <p className="text-[11px] text-white/25">sprawl-ai v0.1.0</p>
      </div>
    </aside>
  );
}
