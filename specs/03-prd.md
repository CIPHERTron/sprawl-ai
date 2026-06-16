# Phase 3 — Product Spec (PRD)

> Detailed feature specs, user flows, screen states, edge cases, permissions, the
> human-in-the-loop rotation flow, and the blast-radius graph UX. Builds on
> [Phase 1](./01-product-definition.md) and [Phase 2](./02-capabilities-scope.md).
> Scope = **MVP**, with **Slice 0** (§2.3.1) called out as the first build target.

---

## Decisions carried into this PRD

| # | Value |
|---|---|
| D1 | Primary persona: **Platform / DevOps Engineer** |
| D3 | Pluggable connectors; **Vault CE (default) + SSM** as MVP free stores |
| D6 | **OSS + self-hostable** |
| D7 | **No-signup demo mode** in Slice 0 |
| D8–D10 | Vault default; AppRole/AssumeRole/Machine-Identity auth; connector creds stored in our own Vault |
| Safety rule | **Verify-before-revoke** with **automatic rollback** is non-negotiable |
| D11 *(locked in P3)* | Rotation uses **step-by-step approval** (per-consumer steps + a separate, explicit revoke confirmation), not a single bulk approve |
| D12 *(locked in P3)* | Incomplete/low-confidence coverage **blocks the revoke gate** and requires **explicit human confirmation** to proceed or abort |
| D13 *(locked in P3)* | Demo mode's **"Simulate verification failure" button is visible to public visitors** to showcase auto-rollback safety |
| Posture dashboard | **MVP, but not Slice 0** |

---

## 3.1 Scope of this PRD

This PRD specifies the **MVP** feature set. Where a feature is **not** in Slice 0, it's
marked `[MVP, not Slice 0]`. Slice 0 is the end-to-end demo cut we build first.

**Primary surfaces (MVP):**
1. Onboarding & connectors
2. Findings / triage queue
3. Secret inventory + posture dashboard `[MVP, not Slice 0]`
4. Secret detail + **blast-radius graph** (centerpiece)
5. **Rotation flow** (HITL, verify-before-revoke)
6. Audit log
7. **Demo mode**

---

## 3.2 Roles & permissions

RBAC enforcement is **v1**; in MVP a single team shares one workspace and the connecting
user is **Owner**. Roles are defined now so the model is forward-compatible.

| Action | Owner/Admin | Approver | Viewer | Demo visitor |
|---|---|---|---|---|
| View inventory / findings / graph | ✅ | ✅ | ✅ | ✅ (seeded data) |
| Add/edit connectors | ✅ | ❌ | ❌ | ❌ |
| Trigger investigation | ✅ | ✅ | ❌ | ✅ (simulated) |
| **Approve a rotation** | ✅ | ✅ | ❌ | ✅ (simulated, sandbox) |
| Execute rotation | ✅ | ✅ | ❌ | ✅ (simulated) |
| View audit log | ✅ | ✅ | ✅ | ✅ |
| Manage users/roles `[v1]` | ✅ | ❌ | ❌ | ❌ |

**Hard rule:** destructive actions (revoke old secret) are **never** auto-executed without
a human approval of the plan (MVP). Demo mode performs the same flow against sandbox
resources only.

---

## 3.3 Information architecture

```
┌─ Dashboard (posture)        ← org health summary, trend [not Slice 0]
├─ Findings (triage queue)    ← prioritized list of exposures
├─ Secrets (inventory)        ← canonical secrets + health status
│   └─ Secret detail
│        ├─ Blast-radius graph (centerpiece)
│        ├─ Severity explanation
│        ├─ Locations / occurrences
│        └─ Rotation (plan → approve → execute → result)
├─ Connectors                 ← GitHub, cloud, secret stores
├─ Audit log
└─ Settings (users/roles [v1], workspace)
```

---

## 3.4 Core user flows

### F1 — Onboarding & connect GitHub
**Goal:** from landing to first detected secret.

1. Sign in (GitHub OAuth) → workspace created (user = Owner).
2. **Install the GitHub App** → choose org/repos.
3. On install: enqueue **historical scan** (full-history) + subscribe to webhooks.
4. Findings begin to appear in the triage queue as scans complete.

**States:** `no_repos` (empty) · `scanning` (progress per repo) · `scan_complete` · `scan_error` (ret‑able).
**Edge cases:** App lacks repo access (prompt re-scope) · huge monorepo (stream + paginate, show progress) · rate-limited (backoff, surface ETA) · revoked install (mark connector degraded, stop scans).

### F2 — Configure a secret-store + cloud connector
Uses the connector config model from §2.8.

1. Choose type (Vault / SSM / AWS IAM).
2. Enter connection + auth (AppRole / AssumeRole+ExternalID).
3. **Test connection + least-privilege probe** → per-capability green/amber result.
4. Save (auth stored encrypted in our Vault, D10).

**States:** `untested` · `verified` · `degraded` (creds expired/insufficient) · `disabled`.
**Edge cases:** read-only creds (allow, mark `capabilities: read` → rotation disabled for that store) · probe fails on `write` only (allow inventory, block rotation, explain) · external ID mismatch (clear error).

### F3 — Finding lifecycle (detection → triage)
A **finding** = one occurrence (repo/commit/path/line). Multiple findings dedupe into one
canonical **secret** identity.

1. Detector (gitleaks) emits raw finding → normalize → dedupe → attach to/create a Secret.
2. Cheap heuristic severity assigned immediately.
3. For high-severity (or on user click), enqueue **agentic investigation** (F5/F7 inputs).

**Finding states:** `new` → `triaged` → (`confirmed` | `false_positive` | `ignored`).
**Edge cases:** secret deleted from code but **still live** (stays high severity — code removal ≠ revocation; this is a core teaching moment) · same secret in many repos (one Secret, many locations) · re-detected after ignore (re-surface with note).

### F4 — Inventory & posture dashboard `[MVP, not Slice 0]`
- **Inventory:** one row per Secret — type, provider, locations count, **health status**, severity, last activity.
- **Posture dashboard:** counts by health, severity distribution, trend over time, "needs attention" list.
- Filters: provider, environment, health, severity.

**Secret health status:** `unknown` · `healthy` · `at_risk` · `exposed`.
**Empty/loading/error** states for each widget.

### F5 — Blast-radius graph (centerpiece) — see §3.7 for full spec
1. Open a Secret → graph renders (secret at center).
2. Agentic **blast-radius build** expands nodes (repos, CI, store entries, cloud principals, resources, environments).
3. User explores: expand, focus, filter by env/confidence; click a node for details.

### F6 — Severity & triage queue
- Queue sorted by severity (consequence-based: scope × environment × exposure).
- Each row: secret, provider, severity, env (prod/staging), exposure status, quick action (Investigate / Rotate).
- Severity detail panel **explains the score** (agent-backed, D-driven).

### F7 — Human-in-the-loop rotation (CRITICAL) — see §3.6 for state machine
The signature flow. **Step-by-step approval**, verify-before-revoke, automatic rollback.

**Approval granularity (locked):** rotation is **step-by-step**, not a single bulk approve.
The user approves the plan, then advances each **stage** explicitly, with a distinct,
high-friction confirmation for the irreversible **revoke** step. Each per-consumer
distribution is its own confirmable step so the user is never surprised by what changes.

```
1. Plan         Agent generates an ordered plan:
                - new secret to provision (where: Vault/SSM)
                - consumers to update (k8s/ECS/Lambda env/CI) — each a discrete step,
                  with coverage/confidence
                - verification checks per consumer
                - revoke step for the OLD secret (gated, separate confirmation)
2. Review       User sees the full plan + a COVERAGE WARNING if any consumer is unknown
3. Approve plan Explicit approval to begin (actor + timestamp in audit)
4. Provision    Provision new secret  → user confirms result, advances
5. Distribute   For EACH consumer: apply → user confirms → next consumer
                (per-step approval; user can pause/abort between steps)
6. Verify       Verify EVERY consumer with the new secret
7. GATE         ⛔ Revoke step unlocks ONLY if every verification passed
8. Revoke       Separate, explicit "revoke old secret" confirmation (irreversible)
9. Done         Secret marked healthy; audit trail complete
   ⤷ Aborting at any step before revoke, or any failure → AUTO-ROLLBACK
     (remove new, restore prior state); old secret remains valid → no outage.
```

**Unknown-consumer policy (locked):** if coverage is incomplete or a critical edge is
low-confidence, the revoke gate is **blocked** and requires an **explicit human
confirmation** to either (a) proceed knowingly or (b) abort. We never silently proceed.

**Edge cases (expanded in §3.6 & §3.8):** unknown consumer · provisioning failure ·
partial distribution · old secret already invalid · rollback failure (critical) ·
approval timeout · concurrent rotation (lock).

### F8 — Demo mode (D7)
- Public, **no signup**. Loads a **seeded fake org** with a planted leaked AWS key.
- Visitor walks the full path: finding → graph → severity → step-by-step plan → approve →
  sandboxed rotation.
- **"Simulate verification failure" button is visible to visitors (D13):** lets anyone
  deliberately fail a rotation mid-way and watch the **automatic rollback** (new secret
  removed, old stays valid, no outage) — showcasing the verify-before-revoke safety that is
  our core differentiator.
- Clearly badged **DEMO / SANDBOX**; no real connectors; resettable.

### F9 — Audit log
- Immutable, append-only. One entry per meaningful event (detection, investigation,
  plan, approval, each rotation step, verify result, revoke, rollback).
- Each entry: actor, action, target (secret/connector), before/after state, timestamp, correlation id.
- Filter by secret, actor, action, time.

---

## 3.5 Secret & finding state model

```
FINDING:   new ──► triaged ──► confirmed
                       ├──► false_positive
                       └──► ignored  ──(re-detected)──► new

SECRET (health):  unknown ──► exposed ──►(rotation success)──► healthy
                     │            ▲
                     └──► at_risk ─┘   (stale / over-privileged [v1])
```

- **Exposed**: detected in code/CI/logs and (assumed) live.
- **At-risk**: not exposed but unhealthy (stale, over-privileged) — `[v1]`.
- **Healthy**: known, scoped, recently/safely rotated, no active exposure.
- Removing a secret from code does **not** move it to healthy — only verified rotation/revocation does.

---

## 3.6 Rotation state machine (the safety core)

```
                    ┌─────────────┐
                    │  proposed   │  (plan generated)
                    └──────┬──────┘
                           ▼
                  ┌──────────────────┐   reject    ┌───────────┐
                  │ pending_approval │────────────►│ rejected  │
                  └────────┬─────────┘             └───────────┘
                           │ approve
                           ▼
                  ┌──────────────────┐
                  │ provisioning_new │──fail──┐
                  └────────┬─────────┘        │
                           ▼                  │
                  ┌──────────────────┐        │
                  │   distributing   │──fail──┤
                  └────────┬─────────┘        │
                           ▼                  ▼
                  ┌──────────────────┐   ┌───────────────┐
                  │    verifying     │──►│ rolling_back  │
                  └────────┬─────────┘   └──────┬────────┘
              all pass ▼   │ any fail           │ success │ fail
            ┌──────────────┐                    ▼         ▼
            │  GATE ⛔ OK   │           ┌─────────────┐ ┌──────────────────┐
            └──────┬───────┘           │ rolled_back │ │ rollback_failed  │
                   ▼                   │ (old valid) │ │  (CRITICAL ALERT)│
          ┌─────────────────┐         └─────────────┘ └──────────────────┘
          │  revoking_old   │──fail──► (old still primary; alert, manual)
          └────────┬────────┘
                   ▼
            ┌─────────────┐
            │  completed  │  → secret = healthy
            └─────────────┘
```

**Invariants (must always hold):**
1. The **old secret is never revoked** until **every** verification check passes (the GATE).
2. Any failure **before** the gate triggers **automatic rollback**; the old secret stays primary → **no outage**.
3. `rollback_failed` is a **critical** state: page the user, freeze further automated action on this secret, full audit.
4. Only **one** active rotation per secret at a time (lock).
5. Every transition is **audit-logged** with actor + correlation id.
6. **Step-by-step approval:** `distributing` advances **one consumer per explicit user confirmation**; the user can pause/abort between steps. `revoking_old` requires a **separate, explicit confirmation** distinct from the initial plan approval.
7. **Incomplete coverage blocks the gate:** if any consumer is unknown/uncertain, the revoke step stays locked until the user explicitly confirms proceed-or-abort.

---

## 3.7 Blast-radius graph — UX spec (centerpiece)

### Node types
| Node | Example | Notes |
|---|---|---|
| **Secret** | the leaked credential | center, sized larger |
| **Location** | repo / commit / file:line | where it was found |
| **CI** | GitHub Actions workflow | `[v1]` for CI-secret detection |
| **Store entry** | Vault path / SSM param | where it's (or should be) stored |
| **Cloud principal** | IAM user/role | who the credential *is* |
| **Cloud resource** | S3 bucket, RDS, etc. | what it can reach |
| **Environment** | prod / staging | classification overlay |

### Edge types
`found_in` · `stored_in` · `is_principal` · `grants_access_to` · `used_by` · `can_access`

### Confidence (per edge) — mandatory, not optional
| Level | Meaning | Visual |
|---|---|---|
| **High** | Verified via API (e.g., IAM policy read) | solid line |
| **Medium** | Inferred (naming/usage correlation) | dashed line |
| **Low** | Heuristic guess | dotted + ⚠️ |

### Interactions
- Click node → **detail panel** (metadata, why it's here, confidence).
- **Expand** neighbors on demand (lazy — don't render thousands at once).
- **Focus mode** (isolate a node + its edges).
- **Filters:** environment (prod/staging), confidence threshold, node type.
- **Severity coloring**: prod-reachable nodes highlighted (red), staging (amber).
- **Legend** + confidence key always visible.

### States
`loading` (skeleton graph + "agent investigating…") · `partial` (still expanding, show progress) · `complete` · `empty` (no reachability found — say so explicitly) · `error` (retry).

**Coverage banner:** if the graph is incomplete or has low-confidence critical edges, show
a banner — *"Blast radius may be incomplete; N consumers unverified."* This same coverage
signal feeds the rotation plan's warning (F7).

---

## 3.8 Cross-cutting edge cases & failure handling

| Scenario | Behavior |
|---|---|
| Unknown/uncertain consumer at rotation time | **Do not** auto-revoke; surface coverage warning; require explicit human confirmation to proceed or abort |
| New-secret provisioning fails | Abort before any change; nothing distributed; secret unchanged |
| Partial distribution failure | Roll back distributed copies; old remains primary |
| Old secret already invalid/expired | Skip revoke; mark resolved with note |
| Rollback fails | `rollback_failed` critical: alert + freeze + manual runbook |
| Approval not given within TTL | Plan expires → `proposed` invalidated; re-plan required (stale infra) |
| Concurrent rotation on same secret | Reject second; one active rotation lock |
| Connector degraded mid-rotation | Pause, alert; never leave half-rotated silently |
| LLM/agent unavailable | Fall back to heuristic severity; rotation requires plan, so block with clear message |
| Demo mode | All of the above simulated against sandbox; "force failure" toggle demonstrates rollback |

---

## 3.9 Non-functional & UX principles (MVP)

- **Safety over speed:** never sacrifice the verify-before-revoke gate for latency.
- **Explainability:** every severity score and agent action has a human-readable "why."
- **Honest uncertainty:** show confidence/coverage; never imply completeness we don't have.
- **No dead ends:** every error state has a next action (retry / re-scope / contact).
- **Demo-first polish:** the Slice 0 happy path must look production-grade (it's the launch).
- **Self-host friendly:** no hard dependency on a paid SaaS to run the core loop (D6).

---

## 3.10 Slice 0 acceptance checklist

- [ ] Connect one GitHub repo; gitleaks finds a planted AWS key.
- [ ] Agent investigates → blast-radius graph renders with confidence + prod/staging.
- [ ] Severity shown with explanation.
- [ ] Rotation plan generated; coverage warning logic works.
- [ ] Approve → sandboxed verify-before-revoke executes; secret → healthy.
- [ ] Force-failure path → automatic rollback; old secret remains valid.
- [ ] Audit log captures the full run.
- [ ] **Demo mode** runs the entire path with no signup / no real account.
- [ ] 60–90s screen recording captured.
