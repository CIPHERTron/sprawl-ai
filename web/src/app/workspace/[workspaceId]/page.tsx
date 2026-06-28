import { redirect } from "next/navigation";

interface PageProps {
  params: Promise<{ workspaceId: string }>;
}

export default async function WorkspacePage({ params }: PageProps) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}/secrets`);
}
