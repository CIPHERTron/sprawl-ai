# Phase 8 — System Design (LLD + DB Design)

> Low-level design: module/package structure, the full DB schema (tables, columns, types,
> relationships, indexes, pgvector), audit-log design, the LangGraph node-level design, the
> rotation-engine/connector class design, and detailed API endpoint specs. Builds on
> [HLD](./07-system-design-hld.md). Scope = **MVP / Slice 0**.

---

## Decisions anchored here

| # | Value |
|---|---|
| §5.1 | agents in `worker`; `api` triggers/streams; `web` no DB |
| D10/D16 | connector creds in Vault; rotation = deterministic PG state machine |
| R2 | stateless JWT (no session table) |
| C1 | engine handles secret values transiently; never persisted |
| Audit | append-only + hash-chained (tamper-evident) |
| Tenancy | every row carries `workspace_id` (single-tenant MVP, forward-compatible) |

---

## 8.1 Module / package structure

### `api` (FastAPI)
```
api/
  main.py                # app, middleware (authz, rate-limit, error envelope)
  routers/               # connectors, github, findings, secrets, graph,
                         #   rotations, audit, demo, me
  auth/                  # jwt verify, rbac, workspace resolution
  schemas/               # pydantic request/response models (shared via zod mirror)
  services/              # thin orchestration: enqueue jobs, read models
  streaming/             # SSE fan-out (subscribes redis pub/sub)
  webhooks/github.py     # HMAC verify + delivery-id dedupe
  db/                    # sqlalchemy session, repositories (read-mostly)
```

### `worker` (arq + LangGraph)
```
worker/
  jobs/                  # scan_repo, ingest_findings, investigate_secret,
                         #   plan_rotation, rotation_step
  detection/             # gitleaks runner + normalizer + dedupe→identity
  agents/                # langgraph graphs + nodes (see 8.4)
    state.py             # InvestigationState
    nodes/               # ingest, triage, investigator, blast_radius,
                         #   severity, rotation_planner
    guardrails.py        # tool allow-list, schema validation, cost ceilings
  rotation/              # deterministic engine (state machine, 8.5)
    engine.py            # step executor, gate, rollback
    steps.py             # provision / distribute / verify / revoke
  connectors/            # framework + impls (8.6)
    base.py              # SecretStoreConnector / CloudConnector / ConsumerConnector protocols
    vault.py  ssm.py  iam.py  consumers/...
  severity/engine.py     # deterministic scoring
  blastradius/builder.py # graph assembly + confidence
  llm/client.py          # litellm wrapper + langfuse tracing
  vaultclient.py         # AppRole auth, cred fetch
  audit/log.py           # hash-chained append
```

### Shared
```
shared/
  models/                # enums + dataclasses mirrored by api & worker
  refs.py                # StoreRef, ConsumerRef, PrincipalRef, CredentialRef
```

---

## 8.2 Database schema (PostgreSQL 16 + pgvector)

> Conventions: PK `id uuid default gen_random_uuid()`; `created_at/updated_at timestamptz`;
> every business table has `workspace_id uuid not null references workspaces(id)`;
> JSONB for flexible attrs; enums via Postgres `CREATE TYPE`.

### Enums
```sql
CREATE TYPE workspace_kind  AS ENUM ('standard','demo');
CREATE TYPE role            AS ENUM ('owner','approver','viewer');
CREATE TYPE connector_type  AS ENUM ('vault','aws_ssm','aws_iam','aws_secrets_manager','infisical');
CREATE TYPE connector_status AS ENUM ('untested','verified','degraded','disabled');
CREATE TYPE scan_status     AS ENUM ('queued','scanning','complete','error');
CREATE TYPE finding_state   AS ENUM ('new','triaged','confirmed','false_positive','ignored');
CREATE TYPE secret_health   AS ENUM ('unknown','healthy','at_risk','exposed');
CREATE TYPE exposure_status AS ENUM ('unknown','live_inferred','public_leak','inactive');  -- L2
CREATE TYPE severity_bucket AS ENUM ('low','medium','high','critical');                    -- L1
CREATE TYPE environment     AS ENUM ('prod','staging','dev','unknown');
CREATE TYPE node_kind       AS ENUM ('secret','location','ci','store_entry','principal','resource','environment');
CREATE TYPE edge_kind       AS ENUM ('found_in','stored_in','is_principal','grants_access_to','used_by','can_access');
CREATE TYPE confidence      AS ENUM ('high','medium','low');
CREATE TYPE investigation_status AS ENUM ('running','complete','error');                    -- N5
-- Lifecycle: 'proposed' = row created + planning queued/running (no plan yet, N1).
--   success → 'pending_approval'; planning failure/abort-before-plan → 'plan_failed' (terminal).
-- 'plan_failed' (N1) and 'abandoned' (M3, expired needs_replan) are terminal and release the lock.
CREATE TYPE rotation_status AS ENUM ('proposed','plan_failed','pending_approval','provisioning',
                                     'distributing','verifying','awaiting_confirmation','revoking',
                                     'completed','rolling_back','rolled_back','rollback_failed',
                                     'rejected','needs_replan','abandoned');
CREATE TYPE step_kind       AS ENUM ('provision','distribute','verify','revoke');
CREATE TYPE step_status     AS ENUM ('pending','awaiting_confirmation','running','done','failed','compensated');
```

### Identity & tenancy
```sql
CREATE TABLE workspaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  kind workspace_kind NOT NULL DEFAULT 'standard',  -- H4: demo isolation
  demo_session_id text,                             -- set for kind='demo'
  expires_at timestamptz,                           -- H4: TTL for demo GC
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON workspaces (kind, expires_at);      -- sweeper scans this
-- H4: every /demo/session mints a fresh kind='demo' workspace with expires_at.
--     All demo secrets/findings/graph rows live under it (same tables, workspace_id-scoped),
--     so they are physically segregated from 'standard' data. A periodic sweeper deletes
--     expired demo workspaces; ON DELETE CASCADE cleans up all child rows. Demo workspaces
--     are never allowed to reference real connectors (enforced in api, §5.7/C7).

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  github_id bigint UNIQUE NOT NULL,
  email text, name text, avatar_url text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  role role NOT NULL DEFAULT 'owner',
  PRIMARY KEY (user_id, workspace_id)
);
-- No sessions table (stateless JWT, R2).
```

### Connectors (auth blob lives in Vault, D10)
```sql
CREATE TABLE connectors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  type connector_type NOT NULL,
  name text NOT NULL,
  environment environment NOT NULL DEFAULT 'unknown',
  path_prefix text,
  connection jsonb NOT NULL DEFAULT '{}',     -- non-secret conn details
  vault_auth_handle text NOT NULL,            -- pointer into Vault (no secret here)
  capabilities jsonb NOT NULL DEFAULT '{}',   -- {read,write,rotate,revoke} probe result
  status connector_status NOT NULL DEFAULT 'untested',
  last_tested_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON connectors (workspace_id, type);
```

### Sources: GitHub installs, repos, scans
```sql
CREATE TABLE github_installations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  installation_id bigint UNIQUE NOT NULL,
  account_login text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE repos (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  installation_id uuid NOT NULL REFERENCES github_installations(id) ON DELETE CASCADE,
  full_name text NOT NULL,
  default_branch text,
  UNIQUE (workspace_id, full_name)
);

CREATE TABLE scans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  repo_id uuid NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  type text NOT NULL,                          -- 'history' | 'incremental'
  status scan_status NOT NULL DEFAULT 'queued',
  head_sha text NOT NULL,                       -- M4: resolved before insert (not nullable)
  forced boolean NOT NULL DEFAULT false,        -- N2: manual rescan bypasses same-sha dedupe
  progress numeric DEFAULT 0,
  error text,
  started_at timestamptz, finished_at timestamptz
);
-- M4: dedupe webhook/auto scans by (repo, type, sha); head_sha non-null so dedupe is real.
-- N2: only de-duplicate *non-forced* scans, so an explicit `POST /repos/{id}/scan` rescan at an
--     unchanged head_sha is always allowed (it sets forced=true) instead of silently no-op (§7.4).
CREATE UNIQUE INDEX scans_dedupe ON scans (repo_id, type, head_sha) WHERE NOT forced;
```

### Secrets & findings
```sql
CREATE TABLE secrets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  fingerprint text NOT NULL,                    -- canonical identity (hash, NOT the value)
  type text NOT NULL,                           -- 'aws_iam_key','stripe', ...
  provider text,
  principal_ref jsonb,                          -- resolved IAM principal (no secret)
  store_ref jsonb,                              -- where it's managed (Vault/SSM)
  health secret_health NOT NULL DEFAULT 'unknown',
  environment environment NOT NULL DEFAULT 'unknown',
  exposure_status exposure_status NOT NULL DEFAULT 'unknown',  -- L2: now an enum
  severity_score int,                           -- denormalized latest score (0..100)
  severity_bucket severity_bucket,              -- L1: derived bucket, denormalized
  rotatable boolean NOT NULL DEFAULT false,     -- MVP: true only for supported types
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, fingerprint)
);
CREATE INDEX ON secrets (workspace_id, health);
CREATE INDEX ON secrets (workspace_id, severity_score DESC);

CREATE TABLE findings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  secret_id uuid REFERENCES secrets(id) ON DELETE SET NULL,
  repo_id uuid REFERENCES repos(id) ON DELETE CASCADE,
  detector text NOT NULL DEFAULT 'gitleaks',
  rule_id text,
  commit_sha text, file_path text, line int,
  match_hash text NOT NULL,                     -- hash of match, never the secret
  state finding_state NOT NULL DEFAULT 'new',
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, match_hash, repo_id, commit_sha, file_path, line)
);
CREATE INDEX ON findings (workspace_id, state);
CREATE INDEX ON findings (secret_id);
```

### Blast-radius graph
```sql
CREATE TABLE graph_nodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  secret_id uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
  kind node_kind NOT NULL,
  label text NOT NULL,
  environment environment NOT NULL DEFAULT 'unknown',
  attrs jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON graph_nodes (secret_id);

CREATE TABLE graph_edges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  secret_id uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
  src_node_id uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  dst_node_id uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  kind edge_kind NOT NULL,
  confidence confidence NOT NULL DEFAULT 'medium',
  attrs jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ON graph_edges (secret_id);
CREATE INDEX ON graph_edges (src_node_id);
```

### Severity (history; latest denormalized onto secrets)
```sql
CREATE TABLE severities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  secret_id uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
  score int NOT NULL,                           -- deterministic (T1)
  factors jsonb NOT NULL,                       -- {scope, environment, exposure}
  explanation text,                             -- LLM-generated
  computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON severities (secret_id, computed_at DESC);
```

### Investigations & rotations (state machine)
```sql
CREATE TABLE investigations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  secret_id uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
  status investigation_status NOT NULL DEFAULT 'running',  -- N5: enum
  trace_id text,                                -- Langfuse correlation
  coverage jsonb,                               -- known/unknown consumers
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
-- M5: at most one in-flight investigation per secret; the investigate_secret job upserts
--     against this so concurrent triggers collapse to one run (matches HLD H4 idempotency).
CREATE UNIQUE INDEX one_active_investigation
  ON investigations (secret_id)
  WHERE status = 'running';

CREATE TABLE rotations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  secret_id uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
  status rotation_status NOT NULL DEFAULT 'proposed',
  plan jsonb,                                   -- H1: NULL during the pre-plan phase
                                               --     ('proposed'); populated at 'pending_approval'
  plan_error text,                              -- N1: why planning failed (for 'plan_failed')
  coverage jsonb NOT NULL DEFAULT '{}',
  new_secret_ref jsonb,
  plan_expires_at timestamptz,                  -- TTL (C6)
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- N1: a plan is required for every state EXCEPT the pre-plan states. 'proposed' = planning
  --     in progress; 'plan_failed' = planning failed/aborted before a plan existed. Every
  --     other state (incl. terminal 'rejected'/'abandoned') is only reachable after a plan,
  --     so it must be present.
  CONSTRAINT plan_present_when_actionable
    CHECK (plan IS NOT NULL OR status IN ('proposed','plan_failed'))
);
-- M3/N1: 'needs_replan' stays active (blocks new rotations) until re-planned or swept to
--     'abandoned'. Terminal states below — incl. 'plan_failed' (N1) — release the lock so the
--     secret can be rotated again (e.g. user retries after a planning failure).
CREATE UNIQUE INDEX one_active_rotation
  ON rotations (secret_id)
  WHERE status NOT IN ('completed','rolled_back','rejected','rollback_failed',
                       'abandoned','plan_failed');

CREATE TABLE rotation_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,  -- N4: convention parity
  rotation_id uuid NOT NULL REFERENCES rotations(id) ON DELETE CASCADE,
  idx int NOT NULL,                             -- order
  kind step_kind NOT NULL,
  target jsonb NOT NULL,                        -- ConsumerRef | StoreRef
  compensation jsonb,                           -- how to undo
  requires_confirmation boolean NOT NULL DEFAULT false,
  status step_status NOT NULL DEFAULT 'pending',
  confirmed_by uuid REFERENCES users(id),
  confirmed_at timestamptz,
  executed_at timestamptz,
  error text,
  UNIQUE (rotation_id, idx)                     -- idempotency (rotation_id, step)
);
```

### Audit (append-only, hash-chained) — see 8.3
```sql
CREATE TABLE audit_log (
  id bigserial PRIMARY KEY,                     -- monotonic ordering
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  actor text NOT NULL,                          -- user id | 'system'
  action text NOT NULL,
  target_type text, target_id text,
  before jsonb, after jsonb,
  correlation_id text,
  prev_hash text,                               -- chain
  hash text NOT NULL,                           -- sha256(prev_hash + canonical(payload))
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_log (workspace_id, created_at DESC);
CREATE INDEX ON audit_log (target_type, target_id);
CREATE INDEX ON audit_log (workspace_id, id);   -- N3: chain replay/verify, ordered by id per workspace
-- App-level append-only; DB role for app has INSERT/SELECT only (no UPDATE/DELETE).
```

### Vectors (pgvector)
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE embeddings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  secret_id uuid REFERENCES secrets(id) ON DELETE CASCADE,
  kind text NOT NULL,                           -- 'finding_context','investigation_summary'
  embedding vector(768) NOT NULL,               -- dim = chosen embed model
  meta jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops);
```

### LangGraph checkpoints (agent resumability)
```text
-- H3: We do NOT hand-roll this. LangGraph's official `PostgresSaver`
-- (langgraph-checkpoint-postgres) owns its own schema — `checkpoints`,
-- `checkpoint_writes`, `checkpoint_blobs` — created via its `.setup()` migration.
-- We run that migration into the same database (separate concern from our app tables)
-- and use thread_id = investigation_id / rotation_id to correlate.
--
-- Cleanup: because these tables are library-owned (no FK to our `secrets`/`investigations`),
-- deleting a secret/investigation does NOT cascade to checkpoints. The investigate/rotation
-- finalizer (and the demo sweeper, H4) explicitly deletes checkpoints by thread_id to avoid
-- orphans. (If we ever need workspace scoping, we encode it into thread_id.)
```

---

## 8.3 Audit log design (tamper-evident)

- **Append-only** at two levels: app never issues UPDATE/DELETE; the app's DB role is granted
  only `INSERT, SELECT` on `audit_log`.
- **Hash chain:** `hash = sha256(prev_hash || canonical_json(entry_without_hash))`, where
  `prev_hash` = the previous row's `hash` (per workspace). Tampering breaks the chain.
- **Concurrency (H2) — chain writes must be serialized per workspace.** `api` and multiple
  `worker` processes all append, so a naïve read-prev-then-insert races and forks the chain.
  Every append runs inside a transaction that first takes a **per-workspace advisory lock**
  (`pg_advisory_xact_lock(hashtext('audit:'||workspace_id))`), then reads the latest `hash`
  (ordered by `id`) and inserts. The lock serializes appends per workspace (cheap; audit
  volume is low) while keeping different workspaces parallel. `id bigserial` gives the canonical
  order the verifier replays.
- **Verification job:** a periodic check recomputes the chain (ordered by `id`, per workspace)
  and flags breaks.
- **What's logged:** detection, investigation start/finish, severity computed, plan created,
  plan approved, each step confirm/execute, verify result, revoke, rollback, connector CRUD,
  rotation outcome. Each carries `actor`, `correlation_id`, `before/after`.
- **No secrets** in audit payloads (refs/metadata only).

---

## 8.4 LangGraph node-level design

`InvestigationState` (shared, §5.2.2). Graph compiled with LangGraph's **`PostgresSaver`
checkpointer** (library-owned tables, H3; `thread_id` = investigation/rotation id). Each node
is pure-ish: reads state, calls allow-listed tools, returns a state delta. Guardrails wrap
every node.

| Node | Reads | Tools (read-only) | Writes to state | Transitions |
|---|---|---|---|---|
| `ingest` | finding(s) | — | `secret_id`, `context.locations` | → `triage` |
| `triage` | context | severity rule engine (cheap) | `severity` (heuristic) | low → END; high/user → `investigator` |
| `investigator` | context | GitHub read, store read, IAM read (`GetAccessKeyLastUsed`) | `context.principal`, `context.store_presence` | → `blast_radius` |
| `blast_radius` | context | IAM policy read, resource enum, CloudTrail `[v1]` | `graph.nodes/edges` (+confidence), `coverage` | → `severity` |
| `severity` | graph, context | **rule engine (deterministic)** + LLM (explanation only) | `severity.score/factors/explanation` | → END (or `rotation_planner` if requested) |
| `rotation_planner` | secret, graph, connectors | connector capability introspection | `plan`, `coverage` | success → `pending_approval`; failure/abort → `plan_failed` (terminal, N1) |

- **Guardrails (`guardrails.py`):** tool allow-list per node, Pydantic-validated outputs
  (reject+retry on malformed), per-node timeout, token/cost ceiling, Langfuse span per call.
- **No write tools** in any node — planning emits a `RotationPlan`; only the deterministic
  engine acts.
- **Lazy expansion:** `blast_radius` re-invocable with a subgraph root for UI "expand".

---

## 8.5 Rotation engine LLD (deterministic)

```
class RotationEngine:
    def tick(rotation_id):            # called by rotation_step job
        r = load(rotation_id); lock(secret_id)
        if r.plan_expired(): set('needs_replan'); return
        step = next_pending(r)
        if step.kind in ('distribute','revoke'):
            revalidate_coverage_and_health(r)   # C6
            if drift: set('awaiting_confirmation'); return
        if step.requires_confirmation and not step.confirmed:
            set('awaiting_confirmation'); return
        try:
            execute(step)                       # idempotent by (rotation_id, idx)
            mark(step,'done'); emit_sse(); audit()
        except StepError:
            rollback(r)                          # compensate completed steps in reverse
    def gate(r): return all(s.done for s in r.verify_steps)
    def execute_revoke(r):
        assert gate(r) and revoke_confirmed(r)   # invariants 1,2 (§5.3.2)
        ...
    def rollback(r):
        for s in reversed(r.completed_steps):
            try: run(s.compensation)
            except: set('rollback_failed'); page(); freeze(); return
        set('rolled_back')                        # old secret still valid
```

- **Step executors** (`steps.py`) map to connector calls per the **type→connector map** (§5.3.5).
- **Idempotency:** each `execute(step)` keyed on `(rotation_id, idx)`; safe to re-run after crash.
- **Concurrency:** Redis `lock:rotation:{secret}` + the partial unique index `one_active_rotation`.

---

## 8.6 Connector module (class design)

> Three protocols (`base.py`). `verify` lives on two of them on purpose — they prove
> different things (M2): `SecretStoreConnector.verify` confirms the **new value resolves in
> the store**; `ConsumerConnector.verify` confirms a **specific consumer authenticates with
> the new credential** (C4). The engine's `verify` step dispatches to the connector that owns
> the step's target.

```
class SecretStoreConnector(Protocol):  # vault.py, ssm.py, secrets_manager.py
    test_connection() -> CapabilityReport
    read(ref) -> SecretValue
    write_new_version(ref, value) -> VersionId
    verify_store(ref) -> VerifyResult              # M2: new version readable in the store
    revoke_old(ref, version) -> None

class CloudConnector(Protocol):        # iam.py
    enumerate_scope(principal) -> [ResourceRef]
    create_credential(principal) -> CredentialMaterial   # transient (C1/C5)
    disable_credential(cred) -> None                # reversible
    delete_credential(cred) -> None                 # M1: the 'delete' half of disable-then-delete (§5.3.4)

class ConsumerConnector(Protocol):     # consumers/{k8s,ecs,lambda,ci}.py
    discover(secret) -> [ConsumerRef]              # best-effort (C2)
    distribute(consumer, value) -> None
    verify_consumer(consumer) -> VerifyResult      # M2: credential-level validation at the consumer (C4)
```

- **Registry** maps `connector_type` → impl; config loaded from `connectors` row; **auth fetched
  from Vault** via `vault_auth_handle` at call time (never cached to disk).
- **CapabilityReport** persisted to `connectors.capabilities` after probe.
- **§8.1 alignment:** `base.py` declares all three protocols
  (`SecretStoreConnector` / `CloudConnector` / `ConsumerConnector`).

---

## 8.7 API endpoint specs (detailed examples)

> All `/api/v1`, JWT-auth (except webhook/demo), error envelope `{error:{code,message,details}}`.

**Create connector**
```
POST /connectors
{ "type":"vault","name":"Prod Vault","environment":"prod","path_prefix":"sprawl/",
  "connection":{"address":"https://vault:8200","kv_mount":"secret","kv_version":"2"},
  "auth":{"method":"approle","role_id":"...","secret_id":"..."} }   # auth → Vault, not DB
→ 201 { "id":"...","status":"verified","capabilities":{"read":true,"write":true,"rotate":true} }
```

**Generate rotation plan (async)**
```
POST /secrets/{id}/rotation/plan
→ 202 { "rotation_id":"...","status":"proposed" }     # plan streamed via SSE
GET  /rotations/{id}
→ 200 { "status":"pending_approval","plan":{...},"coverage":{"known":3,"unknown":1},
        "plan_expires_at":"..." }
# planning failure/abort-before-plan is terminal and releases the lock (N1):
→ 200 { "status":"plan_failed","plan":null,"plan_error":"planner timeout" }   # user may retry
```

**Approve + step-wise confirm + revoke (D11/D12)**
```
POST /rotations/{id}/approve                       → 200 {status:"provisioning"}
POST /rotations/{id}/steps/{stepId}/confirm        → 200 {step:"done", next:"..."}
POST /rotations/{id}/revoke/confirm                # blocked if coverage gate open (409)
→ 409 { error:{ code:"COVERAGE_GATE_OPEN", details:{unknown:1} } }
POST /rotations/{id}/abort                          → 200 {status:"rolling_back"}
GET  /rotations/{id}/stream                         # SSE: step events, state changes
```

**Findings / graph**
```
GET /findings?state=new&sort=severity_desc
GET /secrets/{id}/graph
→ 200 { "nodes":[{id,kind,label,environment,attrs}],
        "edges":[{src,dst,kind,confidence}],
        "coverage":{"known":3,"unknown":1} }
POST /secrets/{id}/graph/expand { "node_id":"..." }
```

**Demo (no-auth, rate-limited)**
```
POST /demo/session                         → 200 {session, seeded data, canned}
POST /demo/rotations/{id}/simulate-failure → 200 {status:"rolling_back"}
```

---

## 8.8 Key algorithms (LLD)

**Severity (deterministic, T1)** — `severity/engine.py`
```
score = w_scope*scope_factor(graph)        # # reachable resources, privilege level
      + w_env*env_factor(environment)       # prod >> staging >> dev
      + w_exp*exposure_factor(secret)       # public leak, still-live(inferred)
# normalized 0..100; bucket → low/med/high/critical; LLM writes the prose explanation only
```

**Dedupe → secret identity** — `detection/`
```
fingerprint = hash(normalized_secret_type + provider + canonical_principal_or_value_hash)
# findings with same fingerprint attach to one secret; never store the raw value
```

**Coverage** — `blastradius/builder.py`
```
known = consumers with explicit refs (k8s/ecs/lambda/ci/code)
unknown = inferred-only or none; coverage.unknown>0 ⇒ revoke gate blocked (D12)
```

---

## 8.9 Indexing & performance notes

- Hot queries: triage queue (`secrets(workspace_id, severity_score DESC)`), findings by state,
  graph by `secret_id`, audit by time — all indexed above.
- **pgvector**: HNSW index, cosine ops; embeddings used for dedupe hints + agent retrieval.
- Partial unique index enforces **one active rotation per secret** at the DB level.
- JSONB for evolving shapes (plan, attrs, coverage); promote to columns if they become hot.
- Audit/findings are the growth tables → partition by `workspace_id`/time when needed (§7.5).

---

## 8.10 Background sweepers (periodic jobs)

- **Demo GC (H4):** deletes `workspaces` where `kind='demo' AND expires_at < now()`; cascade
  removes all child rows; also deletes LangGraph checkpoints for those threads (H3).
- **Rotation reaper (M3):** moves `needs_replan` rotations past a grace window to `abandoned`
  (a terminal state), releasing `one_active_rotation` so the secret can be rotated again.
- **Audit verifier (H2):** recomputes the per-workspace hash chain and flags breaks.

## 8.11 Open scope & data-integrity notes

- `rotatable=false` secret types: full inventory + blast-radius + severity, **manual rotation**
  guidance (no automated engine path) — MVP supports `aws_iam_key`.
- RBAC columns exist (`memberships.role`) but enforcement is **v1**; MVP = single Owner.
- All tables `workspace_id`-scoped now so multi-tenant is additive, not a migration.
- **L3 — `updated_at`:** application-managed (set in the repository layer on write); no DB
  trigger in MVP. Add a trigger if out-of-band writes ever appear.
- **L4 — graph edge integrity:** that `graph_edges.src_node_id`/`dst_node_id` share the edge's
  `secret_id` is enforced in `blastradius/builder.py` (the only writer), not by a DB constraint.
- **L5 — audit/checkpoint FKs:** `audit_log.workspace_id` deliberately has **no `ON DELETE
  CASCADE`** (audit outlives the workspace; deletion is an explicit retention decision).
  LangGraph checkpoint tables are library-owned and cleaned via the finalizer/sweepers (H3).
