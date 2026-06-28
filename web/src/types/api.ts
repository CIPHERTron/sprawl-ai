// API response types — mirrors the FastAPI schemas

export interface ApiOk<T> {
  ok: true;
  data: T;
}

export interface ApiError {
  ok: false;
  error: { code: string; message: string; request_id: string | null };
}

export type ApiResponse<T> = ApiOk<T> | ApiError;

export interface PageResponse<T> {
  ok: true;
  data: T[];
  meta: { total: number; limit: number; offset: number };
}

// ── Demo ───────────────────────────────────────────────────────────────────────
export interface DemoSession {
  session_id: string;
  workspace_id: string;
  token: string;
  expires_at: string;
  is_demo: true;
}

// ── Secrets ───────────────────────────────────────────────────────────────────
export type SecretHealth = "unknown" | "healthy" | "at_risk" | "exposed";
export type SeverityBucket = "low" | "medium" | "high" | "critical";
export type Environment = "prod" | "staging" | "dev" | "unknown";
export type ExposureStatus =
  | "unknown"
  | "live_inferred"
  | "public_leak"
  | "inactive";

export interface Secret {
  id: string;
  type: string;
  provider: string | null;
  health: SecretHealth;
  environment: Environment;
  exposure_status: ExposureStatus;
  severity_score: number | null;
  severity_bucket: SeverityBucket | null;
  rotatable: boolean;
  first_seen: string;
  last_seen: string;
}

// ── Graph ─────────────────────────────────────────────────────────────────────
export type NodeKind =
  | "secret"
  | "location"
  | "ci"
  | "store_entry"
  | "principal"
  | "resource"
  | "environment";

export type EdgeKind =
  | "found_in"
  | "stored_in"
  | "is_principal"
  | "grants_access_to"
  | "used_by"
  | "can_access";

export type Confidence = "high" | "medium" | "low";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  environment: Environment;
  attrs: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  src_node_id: string;
  dst_node_id: string;
  kind: EdgeKind;
  confidence: Confidence;
  attrs: Record<string, unknown>;
}

export interface Coverage {
  known_consumers: number;
  unknown_consumers: number;
  confidence: string;
}

export interface BlastRadius {
  secret: Secret;
  nodes: GraphNode[];
  edges: GraphEdge[];
  coverage: Coverage | null;
}
