# Phase 6 — Architecture Flow

> End-to-end flow + sequence diagrams for the critical paths: event ingestion → agentic
> investigation → blast-radius build → severity → safe rotation → audit, plus rollback and
> demo flows. Builds on the [Tech Spec](./05-tech-spec.md). Diagrams use Mermaid.

---

## Components referenced (from §5.1)

`web` (Next.js) · `api` (FastAPI) · `worker` (arq) · `postgres` (PG16+pgvector) ·
`redis` · `vault` · `ollama`/LLM (via LiteLLM) · external: **GitHub**, **AWS (IAM/SSM)**,
**consumers** (k8s/ECS/Lambda/CI).

---

## 6.1 System context (level 1)

```mermaid
flowchart LR
    user([DevOps Engineer])
    gh[GitHub]
    aws[AWS IAM / SSM]
    cons[Consumers<br/>k8s / ECS / Lambda / CI]

    subgraph Sprawl AI
      web[web - Next.js]
      api[api - FastAPI]
      worker[worker - arq + LangGraph runtime]
      pg[(postgres + pgvector)]
      rd[(redis)]
      vault[(vault)]
      llm[LLM via LiteLLM<br/>Ollama default]
    end

    user --> web --> api
    api <--> pg
    api <--> rd
    worker <--> pg
    worker <--> rd
    api & worker --> vault
    api & worker --> llm
    gh -- webhooks --> api
    worker -- read/act --> aws
    worker -- distribute/verify --> cons
    worker -- clone/scan --> gh
    api -- read --> gh
```

---

## 6.2 End-to-end pipeline (happy path)

```mermaid
flowchart TD
    A[GitHub event / install] --> B[Ingest + dedupe to secret identity]
    B --> C[Heuristic severity + queue]
    C -->|high sev or user click| D[Agentic investigation]
    D --> E[Resolve principal<br/>AKIA to IAM user]
    E --> F[Blast-radius build<br/>nodes/edges + confidence]
    F --> G[Deterministic severity score<br/>+ LLM explanation]
    G --> H{User initiates rotation?}
    H -->|no| I[Stay in triage / posture]
    H -->|yes| J[Rotation planner to step-wise plan + coverage]
    J --> K[Verify-before-revoke execution]
    K --> L[(Audit log every step)]
    K --> M[Secret = healthy]
```

---

## 6.3 Onboarding & historical scan

```mermaid
sequenceDiagram
    actor U as DevOps Eng
    participant W as web
    participant A as api
    participant Q as redis (queue)
    participant K as worker
    participant G as GitHub
    participant P as postgres

    U->>W: Sign in (GitHub OAuth)
    W->>A: session JWT (user, workspace, role)
    U->>G: Install GitHub App (select repos)
    G->>A: installation webhook (HMAC verified, delivery-id deduped)
    A->>P: persist installation + repos
    A->>Q: enqueue scan_repo per repo
    K->>G: clone / tree-walk history
    K->>K: run gitleaks, normalize
    K->>P: upsert findings -> dedupe to secret identity
    K->>A: progress events
    A-->>W: SSE scan progress
    Note over K,P: cheap heuristic severity assigned at ingest
```

---

## 6.4 Live webhook ingestion (push event)

```mermaid
sequenceDiagram
    participant G as GitHub
    participant A as api
    participant Q as redis
    participant K as worker
    participant P as postgres

    G->>A: push webhook
    A->>A: verify HMAC + dedupe by X-GitHub-Delivery
    A->>Q: enqueue ingest_findings (idempotent)
    K->>K: gitleaks on changed refs
    K->>P: upsert finding -> secret identity
    alt high severity
        K->>Q: enqueue investigate_secret
    else low severity
        K->>P: queue placement only
    end
```

---

## 6.5 Agentic investigation → blast-radius build

```mermaid
sequenceDiagram
    participant A as api (trigger/stream)
    participant K as worker (LangGraph runtime)
    participant L as LLM (LiteLLM/Ollama)
    participant AWS as AWS IAM/SSM
    participant G as GitHub (read)
    participant P as postgres
    participant LF as Langfuse

    A->>K: enqueue investigate_secret
    Note over K: investigation graph (checkpointed in postgres)
    K->>G: investigator: gather locations
    K->>AWS: resolve principal (GetAccessKeyLastUsed, AKIA to user)
    K->>AWS: blast_radius: read IAM policy, enumerate resources
    K->>P: store store-presence (Vault/SSM lookups)
    K->>K: build nodes/edges with per-edge confidence
    K->>K: severity = deterministic rule engine (scope x env x exposure)
    K->>L: generate explanation of the score (no secret values)
    K->>P: persist graph + severity + coverage
    K->>LF: trace every tool/LLM call (trace_id)
    K-->>A: complete -> SSE to web
    Note over K: guardrails: read-only tools, schema-validated outputs
```

---

## 6.6 Safe rotation — the critical path (verify-before-revoke)

```mermaid
sequenceDiagram
    actor U as Approver
    participant W as web
    participant A as api
    participant K as worker (engine)
    participant V as vault/SSM (store)
    participant AWS as AWS IAM (authority)
    participant C as consumers
    participant P as postgres (state+audit)

    U->>A: POST rotation/plan
    A->>K: enqueue plan (planner agent runs in worker)
    K->>K: planner builds step-wise plan + coverage
    K-->>A: plan ready
    A-->>W: plan via SSE (with COVERAGE WARNING if unknown consumers)
    U->>A: approve plan
    A->>P: acquire rotation lock, state=provisioning

    Note over K: re-validate coverage + connector health (TTL)
    K->>AWS: provision new IAM key (pre-check 2-key limit)
    K->>V: write_new_version(new value)
    K->>P: step ok (compensation = delete new key)

    loop each consumer (step-wise confirm, D11)
        U->>A: confirm distribute step
        K->>C: push new value (embedded) / no-op (pull)
        K->>C: verify -> credential authenticates
        K->>P: step ok, emit SSE
    end

    Note over K,P: GATE - all verify passed?
    K->>P: re-validate coverage immediately before revoke
    U->>A: explicit revoke confirmation (D11/D12)
    K->>AWS: disable old key -> later delete
    K->>P: state=completed, secret=healthy
    A-->>W: done (SSE)
```

**Invariants visible here:** plan TTL + re-validation (C6), step-wise confirmation (D11),
coverage gate (D12), revoke only after all verifies pass, every transition audited.

---

## 6.7 Rollback path (failure before the gate)

```mermaid
sequenceDiagram
    participant K as worker (engine)
    participant V as vault/SSM
    participant AWS as AWS IAM
    participant C as consumers
    participant P as postgres
    actor U as User

    Note over K: failure or abort at any step before revoke
    K->>P: state=rolling_back
    loop completed steps in REVERSE (each step's own compensation)
        K->>C: undo distribute (restore prior value) if distributed
        K->>V: remove new version if written
        K->>AWS: delete newly created key if provisioned
        K->>P: compensation ok
    end
    alt rollback success
        K->>P: state=rolled_back (OLD secret still valid -> no outage)
        K-->>U: report safe rollback
    else rollback failure
        K->>P: state=rollback_failed (CRITICAL)
        K-->>U: page + freeze secret + full audit
    end
```

---

## 6.8 Demo mode (no-auth, sandbox, canned)

```mermaid
sequenceDiagram
    actor V as Visitor
    participant W as web
    participant A as api
    participant S as sandbox/seed (canned)

    V->>A: POST /demo/session (no auth, rate-limited)
    A->>S: spin ephemeral seeded org (planted AWS key)
    A-->>W: seeded findings + canned graph (no live LLM)
    V->>W: walk: graph -> severity -> step-wise plan -> approve
    V->>A: run sandboxed rotation (sandbox only)
    opt Simulate verification failure (D13)
        V->>A: POST simulate-failure
        A->>S: force fail -> show AUTO-ROLLBACK (old stays valid)
    end
    Note over A,S: physically cannot touch real connectors, TTL auto-expire
```

---

## 6.9 Blast-radius graph data flow

```mermaid
flowchart LR
    F[Finding: AKIA... in repo] --> SI[Secret identity]
    SI --> PR[IAM principal<br/>via GetAccessKeyLastUsed]
    PR --> POL[IAM effective policy]
    POL --> RES[Reachable resources<br/>S3 / RDS / ...]
    SI --> LOC[Locations: repo/commit/path]
    SI --> ST[Store presence: Vault/SSM]
    SI --> CON[Consumers: k8s/ECS/Lambda/CI]
    PR & RES & LOC & ST & CON --> GRAPH[(nodes + edges<br/>per-edge confidence)]
    GRAPH --> ENV[Prod/Staging overlay<br/>+ severity coloring]
```

Each edge carries a **confidence** (high/medium/low, §3.7); incomplete/low-confidence
coverage drives the **coverage banner** and the rotation **coverage gate** (D12).

---

## 6.10 Key failure-mode flows

```mermaid
flowchart TD
    subgraph Provisioning
      P1[create new key fails] --> P2[abort - nothing changed]
      P3[key created, store write fails] --> P4[compensation: delete new key]
    end
    subgraph Coverage
      C1[unknown/low-confidence consumer] --> C2[block revoke gate]
      C2 --> C3[explicit human: proceed or abort]
    end
    subgraph Drift
      D1[plan stale / infra changed] --> D2[pause + re-prompt or re-plan]
    end
    subgraph Revoke
      R1[disable old key fails] --> R2[old still primary - alert - manual]
    end
    subgraph Rollback
      B1[rollback fails] --> B2[CRITICAL: freeze + page + audit]
    end
```

---

## 6.11 Cross-cutting flow notes

- **Idempotency + locks:** `lock:rotation:{secret}`, `lock:scan:{repo}`; every job keyed.
- **Streaming:** scan, investigation, and rotation progress all stream via **SSE** (primary).
- **Audit:** every node/step in the above diagrams emits an append-only, hash-chainable audit
  entry with actor + `correlation_id`.
- **Secret-zero:** `api`/`worker` authenticate to `vault` via platform-injected AppRole
  (§5.7.1) before any connector cred is read.
