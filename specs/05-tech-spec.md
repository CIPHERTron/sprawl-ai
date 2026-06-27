# Phase 5 — Tech Spec

> Per-service responsibilities, the LangGraph agent design (agents, state, transitions,
> the verify-before-revoke gate, rollback), external integrations, auth, the security
> model, and API contracts. Builds on [Phase 1–4](./04-tech-stack.md).
> Scope = **MVP**, Slice 0 first.

---

## Decisions carried into this spec

| # | Value |
|---|---|
| D3 / D8 | Pluggable connectors; Vault CE default + SSM (free stores) |
| D9 | Auth: Vault **AppRole**, AWS **AssumeRole + External ID**, Infisical Machine Identity |
| D10 | Connector creds stored encrypted in our **own Vault** |
| D11 | Rotation = **step-by-step** approval + separate revoke confirmation |
| D12 | Incomplete coverage **blocks the revoke gate** |
| D15 | LLM via **LiteLLM**, default Ollama |
| D16 | Rotation executed by a **deterministic Postgres state machine**, not an LLM |
| Safety | **Verify-before-revoke + auto-rollback** is invariant |

> **Foundational safety principle:** *Agents propose; the deterministic engine disposes.*
> LLM agents **investigate and plan**. They never directly execute a destructive action.
> All state-changing operations run through deterministic, audited, idempotent code with a
> human gate.

---

## 5.1 Service topology & responsibilities

MVP runs as a small set of processes (one `docker compose`):

| Service | Runtime | Responsibilities |
|---|---|---|
| **web** | Next.js | UI, SSR, Auth.js session, calls `api`; SSE/WS client for live rotation/graph |
| **api** | FastAPI | REST API, GitHub webhook receiver, auth verification, **triggers/enqueues** agent + rotation work, serves SSE/WS streams. Does **not** run agents inline. |
| **worker** | Python (arq) | Executes all background + agent work: history scans, detection, **the LangGraph agent runtime (investigation + rotation planning)**, and **rotation state-machine steps** |
| **postgres** | PG16 + pgvector | System of record: entities, graph (nodes/edges), audit log, embeddings, rotation state |
| **redis** | Redis 7 | Job queue, run/state cache, **per-secret rotation locks**, rate-limit buckets |
| **vault** | Vault CE | Stores connector credentials (D10) + acts as a connector type |
| **langfuse** | Langfuse | Agent/LLM trace sink |
| **ollama** | Ollama | Local LLM + embeddings (default provider) |

**Boundary rule:** only `api` and `worker` touch Postgres/Vault/connectors. `web` never
talks to the DB or connectors directly (keeps the security surface in the backend).

**Agent execution location:** the **LangGraph runtime runs in `worker`** (background,
non-blocking, checkpointed/resumable). `api` only **triggers** agent/rotation work and
**streams** results via SSE — it never runs a multi-step agent inline on a request thread.

---

## 5.2 LangGraph agent design

### 5.2.1 Agents (roles)

| Agent | Input | Output | Tools |
|---|---|---|---|
| **Investigator** | a Finding / Secret id | enriched context (locations, principal, store presence) | GitHub read, store read, IAM read |
| **Blast-radius** | enriched context | graph nodes + edges with **confidence** | IAM policy read, resource enumeration, store lookups |
| **Severity** | graph + context | **deterministic score** (computed in code) + **LLM-generated explanation** of that score | scoring = rule engine; LLM = explanation only (T1) |
| **Rotation-planner** | secret + graph + connectors | an **ordered, step-wise rotation plan** with per-consumer steps, verification checks, coverage assessment | connector capability introspection |

All four run as nodes in an **investigation graph**. Each agent action node is wrapped by a
**guardrail** (see 5.2.4).

### 5.2.2 Shared graph state (typed)

```python
class InvestigationState(TypedDict):
    secret_id: str
    finding_ids: list[str]
    context: SecretContext          # locations, principal, store presence
    graph: BlastRadiusGraph         # nodes[], edges[] (each edge has confidence)
    severity: SeverityResult | None # score + rationale
    plan: RotationPlan | None       # ordered steps, coverage, checks
    coverage: CoverageReport        # known vs unknown consumers
    errors: list[AgentError]
    trace_id: str                   # Langfuse correlation
```

### 5.2.3 Investigation graph (flow)

```
        ┌──────────────┐
        │  ingest_node │  (normalize finding → secret identity)
        └──────┬───────┘
               ▼
        ┌──────────────┐     cheap heuristic severity assigned here
        │ triage_node  │────────────────┐
        └──────┬───────┘                │ low severity → stop (queue only)
               │ high severity / user-requested
               ▼
        ┌──────────────┐
        │ investigator │
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │ blast_radius │ (lazy-expandable; emits graph + confidence)
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │  severity    │ (deterministic score; LLM explains it)
        └──────┬───────┘
               ▼
        ┌────────────────┐
        │ rotation_planner│ (only when user initiates rotation)
        └──────┬─────────┘
               ▼
            plan ready → handed to the DETERMINISTIC rotation engine (5.4)
```

- **Severity is deterministic (T1):** the score is computed by a **rule engine**
  (`scope × environment × exposure`) in plain code — reproducible, defensible, and cheap. The
  LLM only produces the *human-readable explanation* of that score; it never decides the
  number. (Consistent with "agents propose; deterministic code disposes.") The cheap
  heuristic at `triage_node` and this full rule-based score share the same engine, run with
  more inputs.
- **Cost guardrail (D-§2.6):** deep agent path runs only for high-severity or on explicit
  user action; everything else gets heuristic severity + queue placement.
- **Lazy graph:** `blast_radius` can be re-invoked to expand a subgraph on demand (UI expand).
- **Checkpointing:** LangGraph state persisted (Postgres checkpointer) so investigations
  are resumable and traceable.

### 5.2.4 Deterministic guardrails (wrap every action)

- **No destructive tools in agents.** Agent tools are **read-only** + *plan-emitting*. The
  only write path is the rotation engine, which is deterministic code, not an LLM.
- **Schema-validated outputs** (Pydantic) — malformed agent output is rejected/retried, never
  acted on.
- **Allow-list tools** per agent; **timeouts + retry (tenacity)**; token/cost ceilings.
- **Every** tool call + LLM call is traced to Langfuse with `trace_id`.

---

## 5.3 Rotation engine (deterministic, safety-critical)

The planner agent produces a `RotationPlan`. Execution is **100% deterministic code** driven
by the Postgres state machine (D16), implementing §3.6.

### 5.3.1 RotationPlan shape

```python
class RotationStep(TypedDict):
    id: str
    kind: Literal["provision","distribute","verify","revoke"]
    target: ConsumerRef | StoreRef          # what this step touches
    compensation: CompensationRef           # how to undo it (rollback)
    requires_confirmation: bool             # step-wise approval (D11)

class RotationPlan(TypedDict):
    secret_id: str
    new_secret_ref: StoreRef                # where the new value lands
    steps: list[RotationStep]               # ordered
    coverage: CoverageReport                # known/unknown consumers (D12)
```

### 5.3.2 Execution invariants (enforced in code)

1. **Gate:** `revoke` steps are unreachable until **all** `verify` steps pass.
2. **Coverage gate (D12):** if `coverage.unknown > 0` or any critical edge is low-confidence,
   the revoke step is **blocked** pending explicit human confirmation.
3. **Step-wise approval (D11):** each `distribute` step + the `revoke` step set
   `requires_confirmation = true`; the worker pauses until the API records confirmation.
4. **Auto-rollback:** any failure/abort before revoke runs each completed step's
   `compensation` in reverse order; old secret stays primary → no outage.
5. **Idempotency:** every step is keyed (`rotation_id`, `step_id`); re-execution is safe.
6. **Single active rotation per secret:** Redis lock; second attempt rejected.
7. **rollback_failed = critical:** freeze the secret, page the user, full audit.
8. **Execution-time re-validation (C6):** a plan has a **TTL**; before each `distribute`
   step and **immediately before the revoke gate**, the engine **re-runs coverage +
   connector-health checks**. If consumers/infra changed since planning (new consumer
   appeared, connector degraded, coverage dropped), the rotation **pauses and re-prompts**
   rather than executing a stale plan. Plan expiry → re-plan required.

### 5.3.3 Execution loop (worker)

```
load rotation state ─► find next pending step
   ├─ plan expired (TTL) → set NEEDS_REPLAN, stop
   ├─ before distribute/revoke → RE-VALIDATE coverage + connector health
   │      └ drift detected → set AWAITING_CONFIRMATION (re-prompt), stop
   ├─ requires_confirmation && not confirmed → set AWAITING_CONFIRMATION, stop
   ├─ execute step (idempotent) ─► success → persist, emit SSE, next step
   │                              └ failure → mark, trigger rollback chain
   └─ all verify passed && revoke confirmed → execute revoke → completed
```

State persisted in `rotation` + `rotation_step` tables (Phase 8). Progress streamed to UI via
SSE/WS.

### 5.3.4 Secret-value handling & provider edge cases

**Value handling (C1) — the trust boundary.** *Agents* operate only on **references**
(store path + version) and **metadata**; they never receive secret values. The
*deterministic engine* **does** handle real secret material — e.g., AWS returns a new IAM
secret access key **exactly once** at creation. Such material is:
- held **in-memory only**, for the minimum duration,
- written **only** to the target store/consumer(s),
- **never** persisted in our Postgres and **never** logged or sent to any LLM (redaction
  enforced at the logging layer; §5.7).

**AWS IAM edge cases (C5):**
- **2-key limit:** an IAM user may have at most **2 access keys**. Before `provision`, the
  engine pre-checks key count; if 2 exist, it surfaces a choice (delete an unused/old key
  first, identified via *last-used*) rather than failing opaquely.
- **Orphaned-key safety:** `provision`'s **compensation = delete the newly created key**. If
  key creation succeeds but the subsequent store write fails, rollback deletes the new key so
  a failed provision can never leave a live, unmanaged credential (a fresh exposure).
- **Revoke = disable-then-delete:** old key is first **deactivated** (reversible) and only
  later deleted, giving a safer intermediate state.

### 5.3.5 Rotation model: store vs consumers, and type → connector (R3)

A rotation touches up to three distinct roles. Disambiguating them removes the last
ambiguity in how execution works:

| Role | What it is | Example |
|---|---|---|
| **Credential authority** | The system that *issues/revokes* the credential | AWS IAM (creates/disables access keys) |
| **Source-of-truth store** | Where the canonical new value is written | Vault / SSM (`new_secret_ref`) |
| **Consumers** | Where the value is actually used | k8s secret, ECS/Lambda env, CI variable, app config |

**Two consumer patterns (a plan may mix both):**
- **Pull consumers** read from the source-of-truth store at runtime → `distribute` is a no-op
  for them; updating the store value suffices.
- **Embedded consumers** hold their own copy (env var, CI secret, k8s Secret) → `distribute`
  **pushes** the new value into each one; each is its own confirmable step.

**Secret-type → connector responsibility map (MVP):**

| Secret type | provision | store new value | distribute | verify | revoke old |
|---|---|---|---|---|---|
| **`aws_iam_key`** (MVP) | CloudConnector `create_credential` | Store `write_new_version` (Vault/SSM) | push to embedded consumers; pull consumers no-op | `verify` (credential authenticates) | CloudConnector `disable_credential` → delete |
| Generic store-managed secret `[v1]` | (n/a — value supplied) | Store `write_new_version` | push/no-op per consumer | `verify` | Store `revoke_old` (old version) |

So for an IAM-key leak, **revoke is a CloudConnector action** (disable+delete the key), *not*
a store-version delete — the `revoke` step dispatches to the connector that owns the
credential authority for that secret type.

---

## 5.4 Connector framework

### 5.4.1 Interface (every connector implements)

```python
class SecretStoreConnector(Protocol):
    def test_connection(self) -> CapabilityReport: ...     # green/amber per capability
    def read(self, ref: StoreRef) -> SecretValue: ...
    def write_new_version(self, ref: StoreRef, value: SecretValue) -> VersionId: ...
    def verify(self, ref: StoreRef, consumer: ConsumerRef) -> VerifyResult: ...  # see C4 note
    def revoke_old(self, ref: StoreRef, version: VersionId) -> None: ...

class CloudConnector(Protocol):
    def enumerate_scope(self, principal: PrincipalRef) -> list[ResourceRef]: ...
    def create_credential(self, principal: PrincipalRef) -> CredentialMaterial: ...
    def disable_credential(self, credential: CredentialRef) -> None: ...
```

### 5.4.2 Connector config (from §2.8)

Stored as a `connector` row; **`auth` blob stored in Vault** (D10), referenced by handle.
On save → `test_connection` + least-privilege probe → `verified | degraded`.

| Type | Connection | Auth (D9) |
|---|---|---|
| `vault` | address, kv_mount, kv_version, path_prefix, TLS | AppRole (role_id + secret_id) |
| `aws_ssm` / `aws_iam` / `aws_secrets_manager` | region, path_prefix, kms_key_id | AssumeRole + External ID |
| `infisical` (v2) | site_url, project_id, env, secret_path | Machine Identity |

---

## 5.5 External integrations

### 5.5.1 GitHub App
- **Why a GitHub App** (not OAuth app / PAT): fine-grained, per-install, least-privilege,
  higher rate limits, webhook-native.
- **Scopes are split by capability (C3):**
  - **Scanning (always, read-only):** Repository **contents: read**, **metadata: read**;
    webhook events: `push`, `pull_request`, `repository`.
  - **Rotation write (opt-in, only if GitHub is a *consumer* to update):** e.g. **Actions
    secrets: write** to distribute a rotated secret to GitHub Actions. This is a **separate,
    explicitly-granted permission** the user opts into; without it, GitHub-side consumers are
    treated as *unverifiable* (→ coverage gate, D12), never silently skipped.
- **Webhook receiver** (`api`): verify `X-Hub-Signature-256` (HMAC); **dedupe by
  `X-GitHub-Delivery` id (C8)** (GitHub redelivers); ingestion jobs are idempotent → enqueue.
- **History scan:** on install, enqueue per-repo full-history scan (clone/treewalk → gitleaks).
- **Rate limits:** per-installation token; backoff + ETA surfaced (F1).

### 5.5.2 AWS (IAM + SSM; Secrets Manager in v1)
- **Auth:** customer creates an IAM role; we **AssumeRole with External ID** (no static keys).
- **IAM (read):** enumerate the leaked principal's effective permissions → reachable resources
  (feeds blast-radius). **IAM (act):** create new access key / disable+delete old (rotation;
  see §5.3.4 edge cases).
- **SSM Parameter Store:** SecureString read/write-new-version (KMS `aws/ssm`).
- **Write scopes for rotation are separate from read scopes (C3):** the read-only role
  enables inventory + blast-radius; the **act** permissions (key create/disable, consumer
  updates) are an **opt-in, explicitly-scoped** addition required only to *execute* rotation.
- Least-privilege policy templates shipped for the customer to apply.

### 5.5.3 Consumer discovery & verification

**Consumer discovery (C2) — the linchpin, stated honestly.** Verify-before-revoke is only as
safe as our knowledge of **where a secret is used**. There is no single source of truth, so
MVP discovery is **best-effort, multi-signal, and confidence-scored**:

| Signal | What it tells us | Confidence |
|---|---|---|
| **IAM credential last-used** | whether/when the credential is active | high (existence), low (which app) |
| **CloudTrail** events for the principal | which services/resources actually used it `[may be v1]` | medium–high |
| **k8s / ECS / Lambda env references** | configs that embed this secret | high (explicit) |
| **CI config / Actions secret references** | pipelines that use it | high (explicit) |
| **Repo/code references** | where the literal appears | high |
| **Naming/usage correlation** (agent-inferred) | likely consumers | low (⚠️ marked) |

- Discovered consumers become `used_by` edges with per-edge confidence (§3.7).
- **Honest limitation:** MVP **cannot guarantee completeness** of consumer discovery. The
  **coverage gate (D12) is the safety backstop** — unknown/low-confidence consumers **block
  the revoke** until a human explicitly decides. We never imply certainty we don't have.

**What `verify` actually proves (C4).** In MVP, `verify` performs **credential-level
validation** — it confirms the **new secret authenticates** in the consumer's context (e.g.,
`sts get-caller-identity` with the new key, or the consumer can read/use the new value). It
does **not** assert full end-to-end application health (that's beyond MVP). The UI/coverage
language reflects this so we never over-promise "everything still works."

- MVP consumer subset (per §2.5): k8s secret, ECS/Lambda env, CI variable; each implements
  `verify(...)`. Unknown consumers → `coverage.unknown++` → blocks gate (D12).

---

## 5.6 Auth & session model

- **User auth:** Auth.js (NextAuth) + GitHub OAuth with **stateless JWT sessions (R2)** —
  no DB session adapter, so `web` honors the §5.1 boundary (never touches Postgres). The JWT
  carries the minimal claims (`user_id`, `workspace_id`, `role`), signed; the user/workspace
  records of record live behind `api`.
- **API auth:** `web` → `api` calls carry the signed session JWT; `api` verifies the
  signature and resolves/authorizes `(user, workspace, role)` against Postgres.
- **Service auth:** `worker` ↔ `api` share internal credentials (not user-facing).
- **RBAC:** roles (Owner/Approver/Viewer) modeled now; **enforced in v1** (MVP = single Owner).
- **Webhook auth:** HMAC signature verification (GitHub App secret).

---

## 5.7 Security model

| Area | Design |
|---|---|
| **Connector credentials** | Stored only in **Vault** (D10), encrypted; never in Postgres plaintext; never logged; write-only in UI |
| **Secret values (C1)** | **Agents** operate only on **references** (store path + version) + metadata — never values. The **deterministic engine** does handle real material (e.g., a one-time IAM secret key): **in-memory only**, minimum duration, written **only** to the target store/consumer, **never** persisted in Postgres, logged, or sent to an LLM. |
| **Least privilege (C3)** | Scanning is **read-only**; rotation **write** scopes (GitHub Actions secrets: write, AWS act permissions, consumer updates) are **separate + opt-in**. Connector `path_prefix` scoping; read-only connectors allowed |
| **Destructive actions** | Only via deterministic engine, behind human gate (D11) + verify gate; never by an agent |
| **Audit** | Append-only, immutable; every detection/plan/approval/step/verify/revoke/rollback with actor + correlation id |
| **Demo/sandbox isolation (C7)** | Demo mode uses seeded data + **canned investigation/graph results (no live LLM calls)**; sessions are **ephemeral, auto-expiring, rate-limited**; **physically cannot** touch real connectors; clearly badged |
| **Transport** | TLS everywhere; signed webhooks; secrets redacted in logs/traces |
| **LLM safety** | Agents read-only + schema-validated; no secret *values* sent to hosted LLMs (operate on metadata/refs); local Ollama default keeps data on-box |

### 5.7.1 Bootstrapping / secret-zero (R1)

A secrets product must answer "what protects *your* secrets?" honestly.

- **Root of trust = the deployment platform's secret mechanism.** The one irreducible
  "secret zero" is the credential `api`/`worker` use to authenticate to **our own Vault**.
  It is **never** stored by the app; it is injected at runtime by the platform:
  - Self-host (Docker Compose): Vault **AppRole** `role_id`/`secret_id` (or a token) provided
    via environment/secret file managed by the operator.
  - Hosted: the platform's secret store (e.g., Fly.io secrets) injects it as an env var.
- **App → Vault auth:** `api`/`worker` authenticate to Vault via **AppRole** (short-lived
  tokens, renewable), then read connector `auth` blobs (D10) on demand. No long-lived
  Vault root token in app config.
- **Vault seal/unseal:** for self-host, document standard Vault unseal (manual or
  auto-unseal via a cloud KMS in v1). Vault starts **sealed**; nothing is readable until
  unsealed.
- **Least blast radius for secret-zero:** the AppRole is scoped to only the paths holding
  connector creds; rotating it is an operator runbook step.
- **Explicit acknowledgment:** we do not eliminate secret-zero (no system can); we **shrink
  and isolate** it to a single platform-managed credential and keep everything else in Vault.

---

## 5.8 API contracts (MVP, representative)

All under `/api/v1`, JSON, session-authenticated unless noted. Errors use a consistent
`{ error: { code, message, details } }` envelope.

### Auth & workspace
| Method | Path | Purpose |
|---|---|---|
| GET | `/me` | current user + workspace + role |
| GET | `/workspace` | workspace settings |

### Connectors
| Method | Path | Purpose |
|---|---|---|
| GET | `/connectors` | list |
| POST | `/connectors` | create (auth blob → Vault); runs test+probe |
| POST | `/connectors/{id}/test` | re-run connection + capability probe |
| PATCH/DELETE | `/connectors/{id}` | update / remove |

### GitHub / ingestion
| Method | Path | Purpose |
|---|---|---|
| POST | `/github/webhook` | **(HMAC auth)** event intake → enqueue |
| POST | `/repos/{id}/scan` | trigger history rescan |
| GET | `/scans/{id}` | scan status/progress |

### Findings, secrets, graph
| Method | Path | Purpose |
|---|---|---|
| GET | `/findings` | triage queue (filter/sort by severity) |
| PATCH | `/findings/{id}` | set state (confirm/false_positive/ignore) |
| GET | `/secrets` | inventory |
| GET | `/secrets/{id}` | detail + health |
| POST | `/secrets/{id}/investigate` | run/refresh agentic investigation |
| GET | `/secrets/{id}/graph` | blast-radius graph (nodes/edges/confidence) |
| POST | `/secrets/{id}/graph/expand` | lazy-expand a subgraph |
| GET | `/secrets/{id}/severity` | score + explanation |

### Rotation (the critical surface)
| Method | Path | Purpose |
|---|---|---|
| POST | `/secrets/{id}/rotation/plan` | generate a step-wise plan (planner agent) |
| GET | `/rotations/{id}` | full rotation state + steps + coverage |
| POST | `/rotations/{id}/approve` | approve the plan to begin |
| POST | `/rotations/{id}/steps/{stepId}/confirm` | **step-wise confirmation** (D11) |
| POST | `/rotations/{id}/revoke/confirm` | **explicit revoke confirmation** (D11/D12 gate) |
| POST | `/rotations/{id}/abort` | abort → triggers rollback |
| GET | `/rotations/{id}/stream` | **SSE/WS** live progress |

### Audit
| Method | Path | Purpose |
|---|---|---|
| GET | `/audit` | filterable audit log |

### Demo (hardened, C7)
| Method | Path | Purpose |
|---|---|---|
| POST | `/demo/session` | **(no auth, rate-limited)** spin an **ephemeral, auto-expiring** sandbox session; **canned** investigation/graph (no live LLM) |
| POST | `/demo/rotations/{id}/simulate-failure` | trigger the visible failure→rollback (D13) |

> **Demo abuse controls (C7):** per-IP + global rate limits; sessions TTL-expire and are
> garbage-collected; demo flows are **pre-baked** (deterministic, no live LLM/compute), so a
> public no-auth endpoint can't be turned into a cost/DoS vector and the launch demo is
> reproducible.

---

## 5.9 Eventing & queue contracts

- **Queue (Redis/arq):** job types — `scan_repo`, `ingest_findings`, `investigate_secret`,
  `rotation_step`. Each job idempotent + keyed.
- **Webhook dedupe (C8):** inbound GitHub events are deduped by **`X-GitHub-Delivery` id**
  (GitHub redelivers on retries); duplicates are dropped before enqueue, and ingestion jobs
  are idempotent as a second line of defense.
- **Locks:** `lock:rotation:{secret_id}` (single active rotation), `lock:scan:{repo_id}`.
- **Streaming:** rotation + graph-build progress pushed to UI via SSE (primary) / WS.
- **Checkpointing:** LangGraph state in Postgres; rotation state in `rotation*` tables.

---

## 5.10 Error handling & observability

- **Consistent error envelope** across API; typed error codes.
- **Retries:** `tenacity` on connector/LLM/network calls with backoff; idempotent steps.
- **Degraded connectors:** surfaced, not silently skipped (esp. mid-rotation → pause+alert).
- **Tracing:** Langfuse for agents/LLM; structured JSON app logs with `trace_id`/`correlation_id`.
- **Secret redaction** enforced in the logging layer.
