# Phase 1 — Product Definition

> This is the foundational document. Everything in later phases (PRD, tech spec, architecture, system design) builds on the decisions captured here.

---

## Decisions Locked

| # | Decision | Locked value |
|---|---|---|
| D1 | **Primary persona** | **Persona A — Platform / DevOps Engineer** is the MVP design target. |
| D2 | **North Star metric** | **# of secrets brought to and kept in a "healthy" state.** |
| D3 | **Vault stance** | **Not a vault.** We delegate storage to external secret managers via a **pluggable connector / secret-store model** (like Harness connectors). **AWS Secrets Manager is the depth-first MVP connector**; the architecture must keep the connector layer abstract so other managers can be added later. |
| D4 | **Go-to-market framing** | **All free** for now (no paywall split between scan and rotation). |
| D5 | **Health concept naming** | Keep the term **"healthy secret."** |

---

## 1.1 One-line definition

> **Sprawl AI is an agentic DevSecOps platform that finds your exposed secrets, shows you exactly what each one can blow up (blast radius), and safely rotates them with a human-approved, verify-before-revoke workflow.**

---

## 1.2 The problem (sharpened)

Secrets leak constantly, but the industry has over-invested in **detection** and under-invested in **consequence + remediation**. The result is "alert fatigue with no closure."

| Stage | Current tooling reality | The actual pain |
|---|---|---|
| **Detect** | Solved-ish (gitleaks, TruffleHog, GitGuardian) | Too many alerts, low signal, no prioritization |
| **Understand** | Mostly absent | "A Stripe key leaked" — *but where is it used? what can it touch? prod or staging?* Nobody answers this. |
| **Remediate** | Manual, terrifying, deferred | Rotating a live credential risks breaking prod, so teams **delay rotation for weeks** — the secret stays valid and exposed the whole time. |
| **Stay clean** | Nonexistent | No continuous posture: stale keys, over-privileged keys, drift between secret manager and code go unnoticed. |

**Core insight:** The expensive, scary, neglected work is *understanding blast radius* and *rotating safely*. That's where Sprawl AI lives. Detection is a commodity we reuse, not rebuild.

---

## 1.3 Target users & personas

We anchor on **3 personas**, with **Persona A as the primary design target** for MVP.

| | Persona A — **Platform / DevOps Engineer** (PRIMARY) | Persona B — **Security Engineer / AppSec** | Persona C — **Eng Lead / CISO** (buyer) |
|---|---|---|---|
| **Company size** | Seed → Series C startups (10–200 eng) | Same | Same |
| **Owns** | CI/CD, cloud infra, secret managers | Security posture, incident response | Risk, compliance, budget |
| **Their pain** | "I'm scared to rotate the prod DB password." | "I get 200 leak alerts, 5 matter, I can't tell which." | "Are we one leaked key away from a breach? Can I prove we're improving?" |
| **What they want from us** | Safe one-click rotation, no downtime | Prioritization by real blast radius | A trend line that goes down; audit trail |
| **Why they open it daily (DAU)** | Posture dashboard, scheduled rotations, drift alerts | Triage queue, severity ranking | Weekly posture report / risk score |

**Recommendation:** Build for **Persona A** first. They feel the rotation terror most acutely, they have hands on keyboard daily, and they're the ones who adopt bottoms-up. B and C are reachable through A.

---

## 1.4 Value proposition

**For** platform/security engineers at cloud-native startups
**who** drown in secret-leak alerts and fear rotating live credentials,
**Sprawl AI is** an agentic secret-posture platform
**that** maps each secret's real blast radius and safely rotates it with verify-before-revoke automation,
**unlike** scanners (gitleaks, GitGuardian) that stop at a list of alerts,
**we** close the loop — from *"a key leaked"* → *"here's everything it touches"* → *"rotated safely, prod never broke."*

---

## 1.5 The dual USP (the moat)

```
        ┌─────────────────────────────────────────────────┐
        │                  SPRAWL AI                       │
        │                                                  │
   USP 1│   Multi-agent AI backend (LangGraph)             │USP 2
   ─────┤   • autonomously investigates a secret           ├─────
 AGENTIC│   • maps reach across repos/CI/cloud/k8s         │VISUAL
 DEPTH  │   • assesses severity & blast radius             │CLARITY
        │   • plans + executes SAFE rotation               │
        │                      ↕                           │
        │   Rich visual frontend                           │
        │   • interactive blast-radius graph               │
        │   • animated, human-approved rotation flow       │
        └─────────────────────────────────────────────────┘
```

| USP | Why it's defensible | Why competitors don't have it |
|---|---|---|
| **1. Agentic investigation + safe rotation** | Multi-agent reasoning chains correlate signals across systems no single scanner sees; verify-before-revoke is a genuinely hard, valuable workflow. | Incumbents are pattern-matchers, not reasoners; rotation is risky so they punt it to the user. |
| **2. Blast-radius visualization** | Turns abstract risk into an "oh \*\*\*\*" moment that drives action and makes severity self-evident. | They ship CSV/dashboards of alerts, not consequence graphs. |

---

## 1.6 What Sprawl AI **IS** vs **IS NOT**

| ✅ Sprawl AI **IS** | ❌ Sprawl AI **IS NOT** (at least not MVP) |
|---|---|
| A consequence + remediation layer **on top of** detection | A new secret *scanner* (we reuse gitleaks/TruffleHog) |
| A blast-radius mapping & visualization engine | A generic CSPM / full cloud security suite |
| A safe, human-in-the-loop rotation orchestrator | A fully autonomous "rotate everything unattended" bot (that's v2) |
| Continuous secret **posture management** (inventory, age, over-privilege, drift) | A SIEM / log analytics platform |
| Deep on **GitHub + AWS (IAM + Secrets Manager)** | Broad/shallow across every cloud + SCM on day one |
| A **pluggable integrator** with external secret managers via connectors (AWS Secrets Manager first) | A secrets *vault* itself / a replacement for Vault/Secrets Manager |

**The discipline that makes this work:** go *deep* on one stack (GitHub + AWS) before going wide. Depth is what makes blast-radius mapping and safe rotation actually function; breadth dilutes both.

---

## 1.7 Success metrics

Split into **North Star**, **DAU drivers**, and **outcome** metrics — because DAU must come from *continuous posture management*, not reactive alerts.

### North Star
> **# of secrets brought to (and kept in) a "healthy" state** — i.e., known, scoped, non-stale, and safely rotatable.
This rewards the whole loop (detect → understand → rotate → maintain), not vanity scan counts.

### DAU / engagement drivers (the "why open it daily")
| Metric | Why it earns a daily open |
|---|---|
| Posture dashboard views / WAU→DAU ratio | The standing "are we OK?" check |
| Scheduled/proactive rotations executed | Recurring, calendar-driven reason to return |
| Drift alerts (code ↔ secret manager) resolved | Ongoing hygiene work |
| Blast-radius graph interactions per secret | The "centerpiece" gets used, not just admired |
| Over-privilege findings actioned | Continuous least-privilege work |

### Outcome metrics (proves the product works)
| Metric | Target signal |
|---|---|
| **Median time-to-rotate** (leak detected → safely rotated) | Drops from *weeks* → *minutes/hours* |
| **% rotations with zero production incidents** | ≥ 99% (verify-before-revoke working) |
| **Rollback rate** | Low and *clean* (auto-rollback never leaves a broken state) |
| **% of secrets with a complete blast-radius map** | Coverage of the core value |
| **Mean secret age / staleness trend** | Declines over time per org |

### Anti-metrics (we explicitly do NOT optimize for)
- Raw # of alerts generated (that's the incumbents' vanity trap).
- Detection recall on stacks outside GitHub+AWS (out of scope for MVP).

---

## 1.8 Strategic risks flagged early (so later phases address them)

| Risk | Why it matters | Where we'll handle it |
|---|---|---|
| **Trust to act on prod** — users must grant write access to rotate live secrets | Highest adoption barrier; one bad rotation kills trust forever | Phase 3 (HITL flow) + Phase 5 (verify-before-revoke + rollback) + Phase 7/8 (security model) |
| **Permissions footprint** — broad GitHub/AWS scopes scare buyers | Security buyers scrutinize this hard | Phase 5 (least-privilege integration design) |
| **Blast-radius completeness** — an *incomplete* map is dangerously misleading | "We said staging, it was prod" = catastrophic | Phase 3 (confidence/coverage UX) + Phase 5 (agent design) |
| **Agent reliability/cost** — LLM agents hallucinate / get expensive | Affects safety and unit economics | Phase 5 (LangGraph design, deterministic guardrails) |
| **"Vitamin vs painkiller"** — posture mgmt risks feeling like a vitamin | Affects DAU | Leaning on the painkiller (rotation terror) as the wedge, posture as retention |

