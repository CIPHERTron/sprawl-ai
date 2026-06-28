import type {
  ApiOk,
  AuditEntry,
  BlastRadius,
  DemoSession,
  PageResponse,
  Rotation,
  Secret,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, ...init } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  const json = await res.json();

  if (!json.ok) {
    throw new Error(json.error?.message ?? `HTTP ${res.status}`);
  }
  return json as T;
}

// ── Demo ───────────────────────────────────────────────────────────────────────
export async function createDemoSession(): Promise<ApiOk<DemoSession>> {
  return apiFetch<ApiOk<DemoSession>>("/demo/session", { method: "POST" });
}

export async function simulateFailure(
  sessionId: string,
  token: string
): Promise<ApiOk<unknown>> {
  return apiFetch<ApiOk<unknown>>(
    `/demo/session/${sessionId}/simulate-failure`,
    { method: "POST", token }
  );
}

// ── Secrets ───────────────────────────────────────────────────────────────────
export async function listSecrets(
  workspaceId: string,
  token: string
): Promise<PageResponse<Secret>> {
  return apiFetch<PageResponse<Secret>>(
    `/workspaces/${workspaceId}/secrets`,
    { token }
  );
}

export async function getSecret(
  workspaceId: string,
  secretId: string,
  token: string
): Promise<ApiOk<Secret>> {
  return apiFetch<ApiOk<Secret>>(
    `/workspaces/${workspaceId}/secrets/${secretId}`,
    { token }
  );
}

// ── Rotations ─────────────────────────────────────────────────────────────────
export async function listRotations(
  workspaceId: string,
  token: string
): Promise<PageResponse<Rotation>> {
  return apiFetch<PageResponse<Rotation>>(
    `/workspaces/${workspaceId}/rotations`,
    { token }
  );
}

export async function getRotation(
  workspaceId: string,
  rotationId: string,
  token: string
): Promise<ApiOk<Rotation>> {
  return apiFetch<ApiOk<Rotation>>(
    `/workspaces/${workspaceId}/rotations/${rotationId}`,
    { token }
  );
}

export async function triggerRotation(
  workspaceId: string,
  secretId: string,
  token: string
): Promise<ApiOk<{ rotation_id: string; status: string }>> {
  return apiFetch<ApiOk<{ rotation_id: string; status: string }>>(
    `/workspaces/${workspaceId}/secrets/${secretId}/rotate`,
    { method: "POST", token }
  );
}

export async function approveRotation(
  workspaceId: string,
  rotationId: string,
  token: string
): Promise<ApiOk<unknown>> {
  return apiFetch<ApiOk<unknown>>(
    `/workspaces/${workspaceId}/rotations/${rotationId}/approve`,
    { method: "POST", token }
  );
}

export async function rejectRotation(
  workspaceId: string,
  rotationId: string,
  token: string
): Promise<ApiOk<unknown>> {
  return apiFetch<ApiOk<unknown>>(
    `/workspaces/${workspaceId}/rotations/${rotationId}/reject`,
    { method: "POST", token }
  );
}

export async function confirmStep(
  workspaceId: string,
  rotationId: string,
  stepId: string,
  token: string
): Promise<ApiOk<unknown>> {
  return apiFetch<ApiOk<unknown>>(
    `/workspaces/${workspaceId}/rotations/${rotationId}/steps/${stepId}/confirm`,
    { method: "POST", token }
  );
}

// ── Audit ─────────────────────────────────────────────────────────────────────
export async function listAuditEvents(
  workspaceId: string,
  token: string,
  limit = 50,
  offset = 0
): Promise<PageResponse<AuditEntry>> {
  return apiFetch<PageResponse<AuditEntry>>(
    `/workspaces/${workspaceId}/audit?limit=${limit}&offset=${offset}`,
    { token }
  );
}

// ── Graph ─────────────────────────────────────────────────────────────────────
export async function getBlastRadius(
  workspaceId: string,
  secretId: string,
  token: string
): Promise<ApiOk<BlastRadius>> {
  return apiFetch<ApiOk<BlastRadius>>(
    `/workspaces/${workspaceId}/secrets/${secretId}/graph`,
    { token }
  );
}
