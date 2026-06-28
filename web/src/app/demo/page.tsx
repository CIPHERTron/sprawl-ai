"use client";

import { createDemoSession, listSecrets } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function DemoPage() {
  const router = useRouter();
  const setDemoSession = useAuthStore((s) => s.setDemoSession);
  const [status, setStatus] = useState<"loading" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const res = await createDemoSession();
        if (cancelled) return;

        const { token, workspace_id, session_id, expires_at } = res.data;
        setDemoSession({ token, workspaceId: workspace_id, sessionId: session_id, expiresAt: expires_at });

        const secrets = await listSecrets(workspace_id, token);
        if (cancelled) return;

        const firstSecret = secrets.data[0];
        if (firstSecret) {
          router.replace(`/workspace/${workspace_id}/secrets/${firstSecret.id}/graph`);
        } else {
          router.replace(`/workspace/${workspace_id}/secrets`);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to start demo");
          setStatus("error");
        }
      }
    }
    boot();
    return () => { cancelled = true; };
  }, [router, setDemoSession]);

  return (
    <main className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        {status === "loading" ? (
          <>
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />
            <p className="text-sm text-white/50">Seeding demo workspace…</p>
          </>
        ) : (
          <>
            <p className="text-sm text-red-300">Error: {error}</p>
            <Link href="/" className="text-sm text-emerald-400 underline">
              Go back
            </Link>
          </>
        )}
      </div>
    </main>
  );
}
