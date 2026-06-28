"use client";

import { SecretCard } from "@/components/secrets/secret-card";
import { listSecrets } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { useQuery } from "@tanstack/react-query";
import { use } from "react";

interface PageProps {
  params: Promise<{ workspaceId: string }>;
}

export default function SecretsPage({ params }: PageProps) {
  const { workspaceId } = use(params);
  const token = useAuthStore((s) => s.token)!;

  const { data, isLoading, error } = useQuery({
    queryKey: ["secrets", workspaceId],
    queryFn: () => listSecrets(workspaceId, token),
    enabled: !!token,
  });

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-white">Secrets</h1>
        <p className="mt-1 text-sm text-white/40">
          Detected credentials and their exposure risk.
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

      {data && (
        <div className="space-y-2">
          {data.data.length === 0 ? (
            <p className="text-sm text-white/30">No secrets found.</p>
          ) : (
            data.data.map((s) => (
              <SecretCard key={s.id} secret={s} workspaceId={workspaceId} />
            ))
          )}
        </div>
      )}
    </div>
  );
}
