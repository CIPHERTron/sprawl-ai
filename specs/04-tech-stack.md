# Phase 4 — Tech Stack

> Finalizes the technology choices for Sprawl AI with a justification per decision,
> alternatives considered, and the key libraries per service. Builds on
> [Phase 1–3](./03-prd.md). Optimized for the locked constraints below.

---

## Decisions locked in Phase 4

| # | Decision |
|---|---|
| D14 | **Go deferred to v1.** MVP/Slice 0 ingestion is Python (FastAPI + Redis workers); dedicated Go service is a v1 upgrade. |
| D15 | **LLM = LiteLLM abstraction, default local Ollama** ($0/self-host), hosted API as opt-in escape hatch. |
| D16 | **Rotation engine = Postgres-backed durable state machine** for MVP; **Temporal** in v1. |
| D17 | **Tracing = Langfuse** (OSS, self-hostable); LangSmith optional. |

---

## Guiding constraints (from locked decisions)

| Constraint | Source | Implication for the stack |
|---|---|---|
| **$0 to build** | D4 + §2.7 | Prefer OSS / free tiers; no paid SaaS in the critical path |
| **OSS + self-hostable** | D6 | Everything must run from a single `docker compose up`; no hard SaaS dependency |
| **Agentic core (LangGraph)** | USP 1 | Python agent service is non-negotiable |
| **Rich visual graph** | USP 2 | First-class graph viz library on the frontend |
| **Verify-before-revoke + rollback** | Safety rule | Durable, resumable workflow execution with compensating actions |
| **Slice 0 first, solo build** | §2.3.1 | Minimize moving parts / languages for the first cut |

---

## 4.1 Stack at a glance (final)

| Layer | Choice | Slice 0? |
|---|---|---|
| Frontend | **Next.js (App Router) + TypeScript + Tailwind + shadcn/ui** | ✅ |
| Graph viz | **React Flow** (`@xyflow/react`) | ✅ |
| Agent + API service | **Python 3.12 + FastAPI + LangGraph** | ✅ |
| Ingestion/glue | **Python (MVP)** → dedicated **Go** service in v1 | Python only |
| LLM access | **Provider-agnostic via LiteLLM**; dev/self-host default **Ollama (local)**, hosted API optional | ✅ |
| Detection | **gitleaks** (CLI, invoked) | ✅ |
| Secret stores | **HashiCorp Vault** (`hvac`) + **AWS SSM/IAM** (`boto3`) | Vault only |
| Primary DB | **PostgreSQL 16 + pgvector** | ✅ |
| Graph storage | **Postgres (nodes/edges tables)** — not a separate graph DB | ✅ |
| Queue / cache / locks | **Redis** | ✅ |
| Rotation workflow engine | **Postgres-backed durable state machine + worker** (MVP); **Temporal** as v1 upgrade | ✅ (state machine) |
| Agent tracing | **Langfuse** (OSS, self-hostable) — LangSmith optional | ✅ |
| Auth | **Auth.js (NextAuth)** with GitHub OAuth | ✅ |
| Packaging / local / self-host | **Docker Compose** (canonical artifact) | ✅ |
| Hosted demo | **Fly.io** (or Railway) | ✅ (demo mode) |

---

## 4.2 Frontend

**Choice: Next.js (App Router) + TypeScript + Tailwind + shadcn/ui.**

- **Why:** confirms the Phase 1 proposal. Next.js gives SSR/routing/API routes in one app,
  shadcn/ui yields a modern, ownable component set (copy-in, not a dependency lock-in),
  Tailwind keeps styling fast. Strong portfolio signal and great Cursor DX.
- **Graph viz — React Flow (`@xyflow/react`):** best balance of looks, interactivity
  (pan/zoom/expand/custom nodes), and DX for our node/edge model (§3.7).
  - *Alternatives:* **Cytoscape.js** (better for very large/complex graphs, heavier API) —
    revisit if graphs exceed ~1k nodes; **D3 force** (max control, most work). React Flow
    wins for MVP polish-per-effort.
- **Key libs:** `@xyflow/react`, `@tanstack/react-query` (server state), `zustand` (light UI
  state), `tailwindcss`, `shadcn/ui` (Radix under the hood), `recharts` (posture trends),
  `auth.js`, `zod` (shared validation).

## 4.3 Agent + API service

**Choice: Python 3.12 + FastAPI + LangGraph.**

- **Why:** LangGraph (the agentic core, USP 1) is Python-first; FastAPI gives typed,
  async HTTP for the API and webhook receiver. One service hosts both the REST API and the
  agent graphs for MVP simplicity.
- **Agent design** is detailed in Phase 5; here we lock the runtime: **LangGraph** for agent
  orchestration with **deterministic guardrails** wrapping any action node.
- **Key libs:** `fastapi`, `uvicorn`, `langgraph`, `langchain-core`, `litellm`, `pydantic` v2,
  `sqlalchemy` 2.x + `alembic` (migrations), `psycopg`/`asyncpg`, `pgvector`, `redis-py`,
  `hvac` (Vault), `boto3` (AWS), `langfuse`, `httpx`, `tenacity` (retries).

## 4.4 Ingestion / glue — the Go question

**Decision: MVP/Slice 0 do ingestion in Python; introduce a dedicated Go service in v1.**

- **Why defer Go:** the Phase 1 vision lists a Go service for high-concurrency webhook
  ingestion and cloud API fan-out. That's a great *scale* and *portfolio* story — but for a
  **solo Slice 0**, a third language triples cognitive load for volume we don't yet have.
  FastAPI + Redis workers handle MVP webhook/scan throughput comfortably.
- **When Go earns its place (v1):** when ingestion concurrency, fan-out to many cloud
  resources, or webhook bursts justify it. At that point a Go service is a deliberate,
  showcaseable upgrade — not premature complexity.
- **Risk noted:** if "polyglot incl. Go" is a hard resume goal, we can pull it into MVP, but
  I recommend earning it in v1.

## 4.5 LLM access (the parked decision)

**Choice: provider-agnostic via LiteLLM; default to local Ollama for $0 dev/self-host;
hosted API as an opt-in for quality.**

- **Why abstraction first:** D6 (self-hostable) + D4 ($0) mean we can't hard-depend on a
  paid API. **LiteLLM** gives one interface across Ollama, OpenAI, Anthropic, etc. — swap by
  config.
- **Default dev/self-host:** **Ollama** running a capable local model (e.g., a Llama/Qwen
  class) → genuinely $0 and fully self-hostable, satisfying the "build it for free" goal.
- **Quality escape hatch:** for the best demo/agent reasoning, allow a hosted model
  (e.g., a small, cheap GPT/Claude tier) via the same interface. Usage-based, opt-in, not
  required to run the product.
- **Cost guardrail (from §2.6):** gate deep agent reasoning to high-severity findings; use
  cheap heuristics first.
- **Embeddings (pgvector):** local embedding model via Ollama/sentence-transformers to keep
  vector features free.

## 4.6 Data layer

**Choice: PostgreSQL 16 + pgvector; Redis for queue/cache/locks.**

- **Why Postgres for everything (incl. the graph):** one durable store for relational data,
  audit log, **blast-radius graph (nodes/edges tables)**, and **pgvector** embeddings. A
  dedicated graph DB (Neo4j) is *not* justified at MVP scale and would add ops + cost; our
  graphs are per-secret and bounded. Revisit only if cross-secret graph queries demand it.
- **pgvector use:** semantic similarity for finding correlation / dedupe hints and
  agent retrieval over prior investigations (detailed in Phase 8).
- **Redis use:** task queue backend, agent/run state cache, **rotation/secret locks**
  (invariant: one active rotation per secret), rate-limit buckets.
- **Key libs:** `postgres:16` + `pgvector`, `redis:7`, `alembic` migrations.

## 4.7 Rotation workflow engine (safety-critical)

**Choice: a Postgres-backed durable state machine + worker for MVP; Temporal as the v1 upgrade.**

- **Why not Temporal in MVP:** Temporal (OSS, self-hostable, free) is *the* right tool for
  durable, resumable, compensating workflows — a perfect fit for verify-before-revoke +
  rollback and a strong portfolio item. But it's a heavy new subsystem for Slice 0.
- **MVP approach:** model the rotation state machine (§3.6) as **persisted state in
  Postgres**, driven by an idempotent worker, with explicit **compensating actions**
  (rollback) per step and a hard **gate** before revoke. This is enough to honor every
  safety invariant for a single-secret, step-by-step flow.
- **v1 upgrade path:** migrate the rotation orchestration to **Temporal** when we add bulk
  rotation and need stronger durability guarantees at scale.
- **Worker lib:** `arq` (async, Redis-based, lightweight) for MVP; `celery` if we outgrow it.

## 4.8 Detection & integrations

- **gitleaks** invoked as a CLI/subprocess (or container), output parsed and normalized.
  TruffleHog added in v1 (verified-secret signal).
- **Vault** via `hvac` (AppRole auth, D9); **AWS** via `boto3` (AssumeRole + External ID, D9).
- Connector credentials stored encrypted in **our own Vault** (D10).

## 4.9 Auth

**Choice: Auth.js (NextAuth) with GitHub OAuth.** Aligns with the GitHub-centric onboarding
(F1), minimal friction, free. RBAC tables defined now, enforced in v1. Sessions in Postgres.

## 4.10 Tracing & observability

- **Langfuse (OSS, self-hostable)** for LLM/agent traces — keeps us $0 and self-host-aligned;
  **LangSmith** supported as an optional hosted alternative.
- App logs structured (JSON); basic metrics via Prometheus-friendly endpoints (lightweight
  for MVP).

## 4.11 Packaging, deployment & repo

- **Docker Compose is the canonical artifact** (D6): `web` (Next.js), `api` (FastAPI+agents),
  `worker` (arq), `postgres+pgvector`, `redis`, `vault`, `langfuse`, `ollama`. One command to
  self-host the whole product.
- **Hosted demo** (demo mode, D7) deployed to **Fly.io** (or Railway) — small, cheap/free
  footprint; demo uses seeded data + sandbox, so no real connectors or heavy compute.
- **Monorepo** layout (frontend + services + infra) — finalized in the implementation-plan
  step after Phase 8.

---

## 4.12 Alternatives considered (summary)

| Decision | Chosen | Rejected (why) |
|---|---|---|
| Graph viz | React Flow | Cytoscape (heavier, needed only at scale), D3 (more effort) |
| Graph storage | Postgres tables | Neo4j (ops + cost, unjustified at MVP scale) |
| Rotation engine | PG state machine (MVP) | Temporal now (too heavy for Slice 0; planned v1) |
| Ingestion lang | Python (MVP) | Go now (third language, premature for solo Slice 0; planned v1) |
| LLM | LiteLLM + Ollama default | Hard dependency on a paid API (breaks $0 + self-host) |
| Tracing | Langfuse (OSS) | LangSmith-only (hosted; kept as option) |
| Worker | arq | Celery (heavier; fallback if needed) |

---

## 4.13 Version pins (initial targets)

> Exact versions resolved at implementation time via package managers; these are intended majors.

- Node 20 LTS · Next.js 15 · React 19 · TypeScript 5.x
- Python 3.12 · FastAPI (latest) · LangGraph (latest) · Pydantic 2.x · SQLAlchemy 2.x
- PostgreSQL 16 + pgvector · Redis 7 · Vault (latest CE) · Ollama (latest)
