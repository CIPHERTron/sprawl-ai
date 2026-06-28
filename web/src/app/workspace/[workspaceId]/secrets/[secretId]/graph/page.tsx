"use client";

import { BlastRadiusGraph } from "@/components/graph/blast-radius-graph";
import { getBlastRadius, triggerRotation } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { use, useState } from "react";
import { useRouter } from "next/navigation";

interface PageProps {
  params: Promise<{ workspaceId: string; secretId: string }>;
}

export default function GraphPage({ params }: PageProps) {
  const { workspaceId, secretId } = use(params);
  const token = useAuthStore((s) => s.token)!;
  const isDemo = useAuthStore((s) => s.isDemo);
  const router = useRouter();
  const queryClient = useQueryClient();

  const [rotateError, setRotateError] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["blast-radius", workspaceId, secretId],
    queryFn: () => getBlastRadius(workspaceId, secretId, token),
    enabled: !!token,
  });

  const rotateMutation = useMutation({
    mutationFn: () => triggerRotation(workspaceId, secretId, token),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["rotations", workspaceId] });
      router.push(`/workspace/${workspaceId}/rotations`);
      // The rotations page will auto-select the new rotation once loaded.
      void res;
    },
    onError: (err: Error) => {
      setRotateError(err.message);
    },
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
    <div className="h-full flex flex-col">
      {rotateError && (
        <div className="shrink-0 border-b border-red-500/20 bg-red-500/8 px-4 py-2 text-[12px] text-red-300">
          {rotateError}
        </div>
      )}
      <div className="flex-1 min-h-0">
        <BlastRadiusGraph
          data={data.data}
          isDemo={isDemo}
          onRotate={() => {
            setRotateError(null);
            rotateMutation.mutate();
          }}
          rotateLoading={rotateMutation.isPending}
        />
      </div>
    </div>
  );
}
