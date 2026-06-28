"use client";

import { Sidebar } from "@/components/layout/sidebar";
import { useAuthStore } from "@/lib/store";
import { useRouter } from "next/navigation";
import { use, useEffect } from "react";

interface WorkspaceLayoutProps {
  children: React.ReactNode;
  params: Promise<{ workspaceId: string }>;
}

export default function WorkspaceLayout({ children, params }: WorkspaceLayoutProps) {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);
  const isDemo = useAuthStore((s) => s.isDemo);
  const isExpired = useAuthStore((s) => s.isExpired);

  // In M8 this will be replaced by Auth.js session check.
  // For now: redirect unauthenticated visitors to the landing page.
  useEffect(() => {
    if (!token || isExpired()) {
      router.replace("/");
    }
  }, [token, isExpired, router]);

  // Next.js 15 App Router passes params as a Promise; unwrap with React's use().
  const { workspaceId } = use(params);

  if (!token) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar workspaceId={workspaceId} isDemo={isDemo} />
      <main className="flex min-h-0 flex-1 flex-col overflow-auto">
        {children}
      </main>
    </div>
  );
}
