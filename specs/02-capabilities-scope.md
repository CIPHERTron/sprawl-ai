# Phase 2 — Capabilities & Scope

> Defines the full capability surface of Sprawl AI, what ships in MVP vs later, the user
> stories that justify each capability, and the explicit non-goals for MVP. Builds on the
> Phase 1 [Product Definition](./01-product-definition.md).

---

## Carried-forward decisions (from Phase 1)

| # | Locked value (impacts scope) |
|---|---|
| D1 | Primary persona = **Platform / DevOps Engineer**. Scope prioritizes their daily workflow. |
| D2 | North Star = **# of secrets kept "healthy."** Capabilities must move secrets toward/keep them healthy. |
| D3 | **Not a vault.** Pluggable **connector / secret-store model**. **Revised:** MVP ships **two free secret stores** — **HashiCorp Vault Community Edition (self-hosted, default)** and **AWS SSM Parameter Store**; **AWS Secrets Manager** moves to v1 (it is *not* free). See §2.7. |
| D4 | **All free.** No billing, entitlements, or plan-gating in scope. |
| D5 | Vocabulary: **"healthy secret."** |

## Decisions locked in Phase 2

| # | Decision | Locked value |
|---|---|---|
| D6 | **Open-source + self-hostable** | First-class stance. The product is OSS and can be run by the user on their own infra (with their own Vault). This is the core trust strategy for a security tool from an unknown author. |
| D7 | **No-signup demo mode** | Ships as part of **Slice 0** (not a later add-on): a seeded fake org/secret lets anyone watch the full flow with no signup and no connected accounts. Primary asset for ProductHunt + recruiter clicks. |
| D8 | **Default secret store = HashiCorp Vault CE** (self-hosted) | Vault Community Edition is the MVP default store; **OpenBao** (MPL 2.0) is the supported zero-license-caveat drop-in. SSM Parameter Store is the second free store. |
| D9 | **Default connector auth patterns** | Vault → **AppRole**; AWS → **AssumeRole + External ID**; Infisical → **Machine Identity**. Static long-lived keys allowed but discouraged. |
| D10 | **Connector credentials stored in our own Vault** | Connector `auth` secrets live encrypted in the product's own Vault instance, never plaintext in Postgres. |

---

## 2.1 Release ladder (definitions)

| Release | Goal | Theme |
|---|---|---|
| **MVP** | Prove the full loop end-to-end on **GitHub + AWS** for the DevOps persona | *Detect → Understand → Safely rotate → Stay aware* |
| **v1** | Harden + deepen within GitHub + AWS; turn posture into a daily habit | *Continuous posture & proactive hygiene* |
| **v2** | Reduce human toil; broaden connectors; team workflows | *Trust earned → guided autonomy* |
| **vNext** | Go wide across clouds/SCMs; advanced intelligence | *Breadth & platform* |

**Guiding rule:** MVP goes **deep, not wide**. Every MVP capability is end-to-end functional on GitHub + AWS before any breadth is added.

---

## 2.2 Capability map

Capabilities are grouped into **9 pillars**. Each row is tagged with the release it lands in.

### Pillar 1 — Detection & Ingestion
*Reuse, don't rebuild. We consume detectors and SCM events; we don't write a new scanner.*

| Capability | Release |
|---|---|
| GitHub App install + webhook ingestion (push, PR, repo events) | **MVP** |
| Historical repo scan on connect (full-history backfill) | **MVP** |
| Run/parse **gitleaks** as the bundled detector | **MVP** |
| Add **TruffleHog** as a second detector (verified-secret signal) | **v1** |
| Dedup + correlate findings into a single canonical **secret identity** | **MVP** |
| Ingest findings from **external scanners** (import API / GitGuardian) | **v2** |
| Detect secrets in **CI configs & logs** (GitHub Actions) | **v1** |
| Detect secrets in **container images / k8s manifests** | **vNext** |

### Pillar 2 — Secret Inventory & Posture *(the DAU engine)*
*The standing "are we OK?" surface. This is what earns the daily open.*

| Capability | Release |
|---|---|
| Canonical **secret inventory** (one row per real secret, all locations) | **MVP** |
| Secret **metadata**: type, provider, first-seen, last-seen, locations | **MVP** |
| **Health status** per secret (healthy / at-risk / exposed / unknown) | **MVP** |
| **Posture dashboard** (org-level health summary + trend) | **MVP** |
| **Staleness / age** tracking + stale-secret surfacing | **v1** |
| **Drift detection**: secret in code/CI vs registered in secret manager | **v1** |
| **Over-privilege detection** (IAM scope vs actual usage) | **v1** |
| **Scheduled posture re-scan** (recurring) | **v1** |
| **Risk score** per org/team + historical trend line | **v2** |

### Pillar 3 — Blast-Radius Intelligence *(the visual centerpiece)*
*Turn "a key leaked" into "here's everything it can touch."*

| Capability | Release |
|---|---|
| Build a **blast-radius graph** per secret (secret → repos/CI/envs/cloud resources) | **MVP** |
| **Reachability mapping**: what each node can access (IAM scope, resources) | **MVP** |
| **Interactive force-directed graph UI** (expand, focus, filter) | **MVP** |
| **Prod vs staging** classification of impacted resources | **MVP** |
| **Confidence / coverage indicator** per edge (how sure we are) | **MVP** |
| Graph **diff over time** (how blast radius changed) | **v2** |
| **What-if simulation** ("if I revoke this, what breaks?") | **v2** |

### Pillar 4 — Severity & Prioritization
*Cut through alert noise with consequence-based ranking.*

| Capability | Release |
|---|---|
| **Severity scoring** from blast radius (scope × environment × exposure) | **MVP** |
| **Prioritized triage queue** (most dangerous first) | **MVP** |
| **Exposure status** (is the secret still live/valid? publicly leaked?) | **MVP** |
| **Live validity check** (probe whether the credential still authenticates) | **v1** |
| **Custom severity policies** per org | **v2** |

### Pillar 5 — Safe Rotation *(the painkiller)*
*Human-in-the-loop, verify-before-revoke, automatic rollback.*

| Capability | Release |
|---|---|
| Agent-generated **rotation plan** (steps, affected consumers, order) | **MVP** |
| **Human approval gate** before any execution | **MVP** |
| **One-click execute** of approved plan | **MVP** |
| **Verify-before-revoke**: provision new secret, verify everywhere, *then* revoke old | **MVP** |
| **Automatic rollback** on verification failure (never leave a broken state) | **MVP** |
| **Rotation status / live progress** view (animated flow) | **MVP** |
| **Scheduled / proactive rotation** (rotate before expiry/age threshold) | **v1** |
| **Bulk rotation** (multiple secrets in one guided run) | **v2** |
| **Policy-driven auto-rotation** (no human gate, opt-in, post-trust) | **v2** |

### Pillar 6 — Connectors & Integrations *(pluggable, per D3)*
*Abstract connector interface: read / write / verify / rotate / revoke.*

| Capability | Release |
|---|---|
| **Connector framework** (abstract interface for secret stores & cloud) | **MVP** |
| **GitHub** connector (App-based, least-privilege scopes) | **MVP** |
| **AWS IAM** connector (enumerate scope, create/disable keys) | **MVP** |
| **HashiCorp Vault** connector (Community Edition, self-hosted; KV v2 read/write/version) — *free, default secret store* | **MVP** |
| **AWS SSM Parameter Store** connector (SecureString — read/write/version) — *free, second secret store* | **MVP** |
| **AWS Secrets Manager** connector (read/write/version secrets) — *paid; added later* | **v1** |
| **Consumer connectors** for verification (k8s, ECS/Lambda env, CI) | **MVP** (subset) → **v1** |
| **Infisical** connector (modern OSS secret manager) | **v2** |
| **GCP Secret Manager / Azure Key Vault** connectors | **vNext** |
| **GitLab / Bitbucket** SCM connectors | **vNext** |

### Pillar 7 — Agentic Investigation *(LangGraph)*
*Multi-agent reasoning that correlates signals no single scanner sees.*

| Capability | Release |
|---|---|
| **Investigator agent**: from a finding, gather context across connectors | **MVP** |
| **Blast-radius agent**: build/expand the reachability graph | **MVP** |
| **Severity agent**: assess and explain risk | **MVP** |
| **Rotation-planner agent**: produce a safe, ordered plan | **MVP** |
| **Deterministic guardrails** around agent actions (no destructive act without gate) | **MVP** |
| **Agent run trace / explainability** surfaced to user (LangSmith-backed) | **MVP** |
| **Natural-language query** over inventory/blast-radius ("what can touch prod RDS?") | **v2** |

### Pillar 8 — Notifications & Workflow
| Capability | Release |
|---|---|
| **In-app notifications** (new exposed secret, rotation result) | **MVP** |
| **Slack alerts** (high-severity findings, approvals needed) | **v1** |
| **Email digests** (posture summary) | **v1** |
| **Ticketing integration** (Jira/Linear issue per finding) | **v2** |
| **Approval via Slack** (approve rotation from chat) | **v2** |

### Pillar 9 — Platform, Auth & Audit
| Capability | Release |
|---|---|
| **Auth / accounts** (org + user) | **MVP** |
| **Org / workspace model** (one org = one connected GitHub+AWS) | **MVP** |
| **Immutable audit log** (every detection, plan, approval, rotation, rollback) | **MVP** |
| **RBAC** (admin / approver / viewer roles) | **v1** |
| **SSO / SAML** | **v2** |
| **Compliance exports** (SOC2-style evidence) | **vNext** |

---

## 2.3 MVP capability summary (the one-screen view)

```
DETECT            UNDERSTAND              ROTATE SAFELY            STAY AWARE
─────────         ──────────────          ───────────────         ─────────────
GitHub App   ──►  Blast-radius graph ──►  Plan (agent)       ──►  Posture dashboard
gitleaks          Reachability/IAM        Human approval          Health status
History scan      Prod vs staging         Verify-before-revoke    Audit log
Dedup→identity    Severity + triage       Auto-rollback           In-app alerts
                  (agentic investigation) Live rotation view
```

**MVP definition of done:** A DevOps engineer connects GitHub + AWS, sees a prioritized
list of real exposed secrets, opens one to view its blast-radius graph and severity,
approves an agent-proposed rotation plan, watches it execute with verify-before-revoke,
and the audit log records the whole thing — with automatic rollback if verification fails.

---

## 2.3.1 Slice 0 — the finishable demo cut

> **Purpose:** the smallest end-to-end vertical slice that proves the whole story and is
> realistically finishable solo. Build this **completely** before broadening to full MVP.
> This is the target for the resume demo + a ProductHunt / OSS launch.

### The one-path story Slice 0 must deliver
```
Connect a GitHub repo  ─►  Detect ONE secret  ─►  Agent investigates
   ─►  Blast-radius graph lights up  ─►  Severity + plan shown
   ─►  Human approves  ─►  SANDBOXED safe rotation (verify-before-revoke)
   ─►  Auto-rollback on failure  ─►  Audit log entry
```

### In scope for Slice 0
| Area | Slice 0 cut |
|---|---|
| Detection | GitHub repo connect + **gitleaks** on history; one canonical secret identity |
| Secret store | **HashiCorp Vault (self-hosted)** only (skip SSM until later) |
| Cloud | **AWS IAM** read scope for one credential type (e.g., IAM access key) |
| Agents | All 4 agents, but on a **single secret** path (investigator → blast-radius → severity → planner) |
| Blast radius | Interactive graph for that secret, with confidence indicator |
| Rotation | **Verify-before-revoke + rollback in a sandbox** (test AWS resources / Vault), clearly labeled as demo-safe — not someone's prod |
| Posture | A minimal inventory list (no full dashboard yet) |
| Audit | Immutable log of the run |
| **Demo mode** | **Seeded fake org/secret** so anyone can watch the full flow with **no signup and no connected accounts** |

### Explicitly NOT in Slice 0 (deferred to full MVP)
- Multiple secret types / bulk findings, SSM connector, posture dashboard & trends,
  notifications, multi-tenant accounts/RBAC, scheduled work, drift/staleness/over-privilege.

### Slice 0 definition of done
A visitor opens **demo mode**, watches a leaked key light up its blast-radius graph,
approves the agent's plan, and sees a sandboxed verify-before-revoke rotation complete
(or cleanly roll back) with an audit trail — **without connecting any real account.**
A 60–90s screen recording of this path is a first-class deliverable.

### Supporting decisions (locked — see top of doc)
- **D6 — Open-source + self-hostable**: flips the "trust an unknown solo security tool"
  problem (audit the code, run it yourself, uses your own Vault).
- **D7 — No-signup demo mode** ships as part of Slice 0 (not a later add-on): highest-leverage
  asset for both PH conversion and recruiter clicks.

---

## 2.4 User stories (by persona)

### Persona A — Platform / DevOps Engineer (PRIMARY)
| # | As a DevOps engineer, I want to… | So that… | Release |
|---|---|---|---|
| A1 | connect GitHub + AWS in a few clicks | I can start without heavy setup | MVP |
| A2 | see all exposed secrets ranked by real danger | I fix what matters first | MVP |
| A3 | view a visual blast radius for any secret | I understand impact before acting | MVP |
| A4 | know whether an exposed key touches prod or staging | I gauge urgency correctly | MVP |
| A5 | get an agent-proposed rotation plan | I don't have to design it myself | MVP |
| A6 | approve and one-click rotate safely | prod never breaks during rotation | MVP |
| A7 | have rotation auto-rollback on failure | a bad rotation can't take down prod | MVP |
| A8 | see an org posture dashboard | I get a daily "are we OK?" read | MVP |
| A9 | be told when a secret is stale/over-privileged | I proactively reduce risk | v1 |
| A10 | schedule rotations before expiry | hygiene happens without me remembering | v1 |
| A11 | catch drift between code and secret manager | config and reality stay in sync | v1 |

### Persona B — Security Engineer / AppSec
| # | As a security engineer, I want to… | So that… | Release |
|---|---|---|---|
| B1 | triage findings by consequence, not raw count | I escape alert fatigue | MVP |
| B2 | see *why* a secret is severe (explainable) | I trust and can justify the ranking | MVP |
| B3 | confirm whether a leaked secret is still live | I know if it's an active incident | v1 |
| B4 | get Slack alerts for high-severity exposures | I respond fast | v1 |
| B5 | query the graph in natural language | I investigate ad hoc | v2 |

### Persona C — Eng Lead / CISO
| # | As an eng lead, I want to… | So that… | Release |
|---|---|---|---|
| C1 | see a posture trend over time | I can prove we're improving | v1 |
| C2 | have an immutable audit trail of every rotation | we're accountable & compliant | MVP |
| C3 | get a weekly posture digest | I stay informed without logging in | v1 |
| C4 | enforce RBAC on who can approve rotations | risky actions are controlled | v1 |

---

## 2.5 MVP non-goals (explicitly OUT)

| Not in MVP | Why | Lands in |
|---|---|---|
| Clouds beyond AWS (GCP/Azure) | Depth-first discipline | vNext |
| SCMs beyond GitHub (GitLab/Bitbucket) | Depth-first discipline | vNext |
| Fully autonomous rotation (no human gate) | Trust must be earned first | v2 |
| Writing our own secret scanner | We reuse gitleaks/TruffleHog | — (never) |
| Being a secret vault / storage | We integrate, not store (D3) | — (never) |
| Billing / plans / entitlements | All free (D4) | post-MVP |
| SIEM / log analytics platform | Not our category | — (never) |
| Custom detector authoring | Niche; reuse defaults | vNext |
| **Managed multi-tenant cloud SaaS** (hosted-for-you offering) | We ship **OSS + self-hostable** first (D6); a managed SaaS is a later, separate effort | vNext |
| SSO/SAML, advanced RBAC | Single-team MVP scope | v1/v2 |
| Bulk & scheduled rotation | Get single safe rotation perfect first | v1 |
| Slack/Jira/Linear integrations | Core loop first | v1/v2 |

---

## 2.6 Scope risks to watch

| Risk | Mitigation in scope |
|---|---|
| **Verification connectors are the hard part** of verify-before-revoke (knowing *every* consumer) | MVP ships a **known subset** of consumer connectors + explicit coverage/confidence UX; unknown consumers are flagged, not silently assumed safe |
| **Blast-radius completeness** can mislead | Confidence indicator is MVP, not optional |
| **MVP scope creep via "just one more connector"** | Connector framework is MVP, but only GitHub + AWS implementations ship in MVP |
| **Agent cost/latency** for every finding | Severity-gate expensive agent work; cheap heuristics first, deep agentic investigation for high-severity |

---

## 2.7 MVP cost / free-tier analysis

**Goal:** build the entire MVP on GitHub + AWS without paying for any subscription.
All figures verified as of **June 2026**.

### GitHub — $0
| Need | Free tier |
|---|---|
| GitHub App (webhooks, org/repo install) | Free |
| Webhook ingestion + REST/GraphQL API | Free (5,000 req/hr per installation) |
| Repo history + event scanning | Free, including on the GitHub Free plan |

### Secret stores — pick free ones
| Store | MVP use | Free tier reality |
|---|---|---|
| **HashiCorp Vault — Community Edition (self-hosted)** | **Default** secret store (KV v2 read/write/version) | ✅ **Free** — runs in Docker alongside our stack. BSL 1.1 license permits our use (only restricts reselling Vault as a competing hosted service). **OpenBao** (MPL 2.0 fork, Vault-API-compatible) is a fully-OSS drop-in if zero license caveats are desired. |
| **AWS SSM Parameter Store** (Standard, `SecureString`) | **Second** secret store | ✅ **Free indefinitely** — 10,000 params/region, no storage charge, standard API calls free |
| **AWS Secrets Manager** | (deferred to v1) | ❌ **No permanent free tier** — $0.40/secret/month + $0.05/10k API calls. New accounts get $200 credits (6 mo) or a legacy 30-day trial only. |
| **Infisical** | (deferred to v2) | ⚠️ Free plan exists but **gates secret versioning & rotation** to paid (limits: 5 identities / 3 projects / 3 envs). Good later connector, awkward as the MVP primary. |

### AWS — other services
| Service | MVP use | Free tier reality |
|---|---|---|
| **IAM** | Enumerate scope, create/disable access keys | ✅ Always free |
| **KMS** (only if using SSM SecureString) | Encrypt/decrypt parameter values | ✅ Free using AWS-managed `aws/ssm` key; KMS free tier = 20,000 requests/month (avoid customer-managed keys = $1/mo each) |

### Decision: two free secret stores in MVP
We make **HashiCorp Vault Community Edition (self-hosted in Docker) the default MVP secret
store**, and ship **AWS SSM Parameter Store** as a second free connector. Both cost **$0**.
This keeps MVP infra cost at zero, gives a stronger portfolio story (Vault is the canonical
enterprise secret manager), and **demonstrates the pluggable-connector USP (D3) on day one**
rather than just claiming it. **AWS Secrets Manager** (paid) is added in **v1**; **Infisical**
in **v2**. We orchestrate rotation *on top of* these stores, so a store's own built-in
rotation feature is not required.

### Out-of-scope cost note (not GitHub/AWS)
The **LLM API** powering the LangGraph agents (e.g., OpenAI/Anthropic) is a separate,
usage-based cost and is **not** covered by GitHub/AWS free tiers. To keep MVP build cost
at zero, options include: a local open model (Ollama) for development, free/low-cost API
tiers, or capping deep agent work to high-severity findings (already noted in §2.6).
This will be finalized in Phase 4 (Tech Stack).

---

## 2.8 Connector configuration model (overview)

What we collect to configure a **secret-store connector** under the pluggable model (D3).
Detailed API/schema is finalized in Phase 5 (Tech Spec); onboarding UX in Phase 3 (PRD).

### Common fields (every connector)
| Field | Purpose | Sensitive |
|---|---|---|
| `name` | Human label ("Prod Vault") | No |
| `type` | `vault` \| `aws_ssm` \| `aws_secrets_manager` \| `infisical` | No |
| `environment` | prod / staging / dev — feeds severity | No |
| `path_prefix` / scope | The path we're allowed to operate within (least privilege) | No |
| `capabilities` | Allowed verbs: `read`, `write/version`, `rotate`, `revoke` | No |
| `auth` | Connection credentials (per-type, below) | **Yes** |
| `enabled` | Toggle without deleting | No |

**Common interface (all connectors implement):** `testConnection` · `read` · `writeNewVersion` · `verify` · `revokeOld`. Only `auth` + connection details vary per type.

### Per-type fields
| Type | Connection | Recommended auth | Sensitive fields |
|---|---|---|---|
| **HashiCorp Vault** | `address`, `kv_mount`, `kv_version`, `path_prefix`, TLS (`ca_cert`/`tls_skip_verify`) | **AppRole** (`role_id` + `secret_id`) | `secret_id` / token |
| **AWS SSM / Secrets Manager** | `region`, `path_prefix`, optional `kms_key_id` | **AssumeRole** (`role_arn` + `external_id`) | static keys (if used) |
| **Infisical** (v2) | `site_url`, `project_id`, `environment`, `secret_path` | **Machine Identity** (`client_id` + `client_secret`) | `client_secret` |

### Security & validation rules
- **Connector credentials are stored encrypted in our own Vault**, never plaintext in Postgres; write-only in the UI; never logged.
- **Prefer revocable/short-lived auth** (Vault AppRole, AWS AssumeRole + External ID) over static long-lived keys; static keys allowed but discouraged.
- Request **minimum scope** — a specific `path_prefix` + only the verbs needed. Read-only connectors are valid (inventory-only, cannot rotate).
- On save, run **`testConnection` + a least-privilege probe** and surface a per-capability green/amber result (no silent assumptions), mirroring the blast-radius confidence philosophy.
- Every connector operation is **audit-logged** (connector, op, actor).
