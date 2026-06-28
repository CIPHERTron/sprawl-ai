"use client";

import { BlastRadiusGraph } from "@/components/graph/blast-radius-graph";
import { getBlastRadius } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { useQuery } from "@tanstack/react-query";
import { use } from "react";

interface PageProps {
  params: Promise<{ workspaceId: string; secretId: string }>;
}

export default function GraphPage({ params }: PageProps) {
  const { workspaceId, secretId } = use(params);
  const token = useAuthStore((s) => s.token)!;
  const isDemo = useAuthStore((s) => s.isDemo);

  const { data, isLoading, error } = useQuery({
    queryKey: ["blast-radius", workspaceId, secretId],
    queryFn: () => getBlastRadius(workspaceId, secretId, token),
    enabled: !!token,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <span className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-emerald-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-6 text-sm text-red-300">
          {error.message}
        </div>
      </div>
    );
  }

  if (!data?.data) return null;

  return (
    <div className="h-full">
      <BlastRadiusGraph data={data.data} isDemo={isDemo} />
    </div>
  );
}
