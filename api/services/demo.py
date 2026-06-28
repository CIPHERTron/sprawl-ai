"""
Demo session service — creates a sandboxed demo workspace, seeds it with
canned Slice 0 data, and issues a short-lived demo JWT.

Canned story (AWS IAM key leaked in GitHub):
  Secret  → AWS IAM access key for "ci-deploy" IAM user (health: exposed, critical)
  Finding → leaked in acme/frontend commit deadbeef at .env.example:3
  Graph   → secret → IAM principal → S3 bucket → prod environment
  Severity→ score 87, critical, broad S3 access in prod
  Investigation → complete, 2 known consumers
  Rotation → pending_approval with a 4-step plan (provision→distribute→verify→revoke)

The demo workspace is isolated:
  - kind = 'demo', expires_at = now + TTL
  - All rows carry workspace_id of the demo workspace (no real connector refs)
  - Connector refs in plan/steps are sandbox stubs only

Security: no real credentials are stored anywhere in demo data.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit.log import audit
from api.config import settings
from api.db.models.graph import GraphEdge, GraphNode, Severity
from api.db.models.investigation import Investigation
from api.db.models.rotation import Rotation, RotationStep
from api.db.models.secret import Finding, Secret
from api.db.models.workspace import Workspace
from shared.models.enums import (
    Confidence,
    EdgeKind,
    Environment,
    ExposureStatus,
    FindingState,
    InvestigationStatus,
    NodeKind,
    RotationStatus,
    SecretHealth,
    SeverityBucket,
    StepKind,
    StepStatus,
    WorkspaceKind,
)

logger = structlog.get_logger(__name__)

# Fixed demo sub — no real User row needed (JWT claims carry identity for demo)
DEMO_USER_SUB = "00000000-0000-0000-0000-000000000001"
DEMO_ACTOR = "demo-agent"

# Deterministic fingerprint for the canned AWS key identity
_DEMO_FINGERPRINT = hashlib.sha256(b"demo:aws_iam_key:ci-deploy").hexdigest()
_DEMO_MATCH_HASH = hashlib.sha256(b"demo:match:AKIAIOSFODNN7EXAMPLE").hexdigest()


@dataclass(frozen=True)
class DemoSessionResult:
    session_id: str
    workspace_id: str
    token: str
    expires_at: datetime


async def create_demo_session(db: AsyncSession) -> DemoSessionResult:
    """
    Create a demo workspace, seed all canned data, and return a signed JWT.
    The entire operation runs in a single transaction.
    """
    async with db.begin():
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.demo_session_ttl_seconds
        )
        session_id = str(uuid.uuid4())

        # ── Workspace ─────────────────────────────────────────────────────
        ws = Workspace(
            name="Sprawl AI — Live Demo",
            kind=WorkspaceKind.DEMO,
            demo_session_id=session_id,
            expires_at=expires_at,
        )
        db.add(ws)
        await db.flush()
        wid = ws.id  # UUID

        # ── Secret identity ───────────────────────────────────────────────
        secret = Secret(
            workspace_id=wid,
            fingerprint=_DEMO_FINGERPRINT,
            type="aws_iam_key",
            provider="aws",
            principal_ref={"kind": "iam_user", "arn": "arn:aws:iam::123456789012:user/ci-deploy"},
            store_ref={"kind": "vault", "path": "aws/creds/ci-deploy"},
            health=SecretHealth.EXPOSED,
            environment=Environment.PROD,
            exposure_status=ExposureStatus.PUBLIC_LEAK,
            severity_score=87,
            severity_bucket=SeverityBucket.CRITICAL,
            rotatable=True,
        )
        db.add(secret)
        await db.flush()
        sid = secret.id

        # ── Finding ───────────────────────────────────────────────────────
        finding = Finding(
            workspace_id=wid,
            secret_id=sid,
            detector="gitleaks",
            rule_id="aws-access-key-id",
            commit_sha="deadbeef1234567890abcdef1234567890abcdef",
            file_path=".env.example",
            line=3,
            match_hash=_DEMO_MATCH_HASH,
            state=FindingState.CONFIRMED,
        )
        db.add(finding)

        # ── Graph nodes ───────────────────────────────────────────────────
        n_secret = GraphNode(
            workspace_id=wid, secret_id=sid,
            kind=NodeKind.SECRET,
            label="AWS IAM Key (ci-deploy)",
            environment=Environment.PROD,
            attrs={"fingerprint": _DEMO_FINGERPRINT[:16] + "…"},
        )
        n_principal = GraphNode(
            workspace_id=wid, secret_id=sid,
            kind=NodeKind.PRINCIPAL,
            label="IAM User: ci-deploy",
            environment=Environment.PROD,
            attrs={"arn": "arn:aws:iam::123456789012:user/ci-deploy", "policies": ["s3-prod-full"]},
        )
        n_resource = GraphNode(
            workspace_id=wid, secret_id=sid,
            kind=NodeKind.RESOURCE,
            label="s3://acme-prod-assets",
            environment=Environment.PROD,
            attrs={"type": "s3_bucket", "region": "us-east-1", "public": False},
        )
        n_env = GraphNode(
            workspace_id=wid, secret_id=sid,
            kind=NodeKind.ENVIRONMENT,
            label="Production",
            environment=Environment.PROD,
            attrs={"criticality": "high"},
        )
        db.add_all([n_secret, n_principal, n_resource, n_env])
        await db.flush()

        # ── Graph edges ───────────────────────────────────────────────────
        db.add_all([
            GraphEdge(
                workspace_id=wid, secret_id=sid,
                src_node_id=n_secret.id, dst_node_id=n_principal.id,
                kind=EdgeKind.IS_PRINCIPAL, confidence=Confidence.HIGH,
            ),
            GraphEdge(
                workspace_id=wid, secret_id=sid,
                src_node_id=n_principal.id, dst_node_id=n_resource.id,
                kind=EdgeKind.GRANTS_ACCESS_TO, confidence=Confidence.HIGH,
                attrs={"permissions": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]},
            ),
            GraphEdge(
                workspace_id=wid, secret_id=sid,
                src_node_id=n_resource.id, dst_node_id=n_env.id,
                kind=EdgeKind.USED_BY, confidence=Confidence.MEDIUM,
            ),
        ])

        # ── Severity ──────────────────────────────────────────────────────
        db.add(Severity(
            workspace_id=wid, secret_id=sid,
            score=87,
            factors={
                "environment": "prod",
                "exposure": "public_leak",
                "scope": "broad_write_access",
                "age_days": 312,
            },
            explanation=(
                "This AWS IAM access key grants broad write access to the production S3 bucket "
                "acme-prod-assets. It was leaked publicly in a GitHub commit 312 days ago and "
                "is still active. Immediate rotation is strongly recommended."
            ),
        ))

        # ── Investigation ─────────────────────────────────────────────────
        investigation = Investigation(
            workspace_id=wid, secret_id=sid,
            status=InvestigationStatus.COMPLETE,
            trace_id="demo-trace-00000000",
            coverage={"known_consumers": 2, "unknown_consumers": 0, "confidence": "high"},
            finished_at=datetime.now(timezone.utc),
        )
        db.add(investigation)

        # ── Rotation (pending_approval with full plan) ─────────────────────
        plan_expires = datetime.now(timezone.utc) + timedelta(hours=24)
        rotation = Rotation(
            workspace_id=wid, secret_id=sid,
            status=RotationStatus.PENDING_APPROVAL,
            plan={
                "summary": "Rotate AWS IAM access key for ci-deploy; update 2 consumers then revoke old key.",
                "steps": [
                    {"idx": 0, "kind": "provision", "description": "Generate new AWS IAM access key for ci-deploy"},
                    {"idx": 1, "kind": "distribute", "description": "Update GitHub Actions secret AWS_ACCESS_KEY_ID in acme/frontend", "requires_confirmation": True},
                    {"idx": 2, "kind": "verify", "description": "Trigger verify-credentials workflow and assert 0 failures"},
                    {"idx": 3, "kind": "revoke", "description": "Deactivate old AWS IAM access key AKIA…EXAMPLE", "requires_confirmation": True},
                ],
                "coverage": {"known_consumers": 2, "unknown_consumers": 0},
                "created_by": DEMO_ACTOR,
                "model": "demo (no LLM call)",
            },
            plan_error=None,
            coverage={"known_consumers": 2, "unknown_consumers": 0},
            plan_expires_at=plan_expires,
        )
        db.add(rotation)
        await db.flush()

        # Rotation steps (all pending — waiting for approval)
        steps = [
            RotationStep(
                workspace_id=wid, rotation_id=rotation.id, idx=0,
                kind=StepKind.PROVISION,
                target={"type": "aws_iam", "account": "123456789012", "username": "ci-deploy"},
                compensation={"action": "delete_new_key"},
                requires_confirmation=False,
                status=StepStatus.PENDING,
            ),
            RotationStep(
                workspace_id=wid, rotation_id=rotation.id, idx=1,
                kind=StepKind.DISTRIBUTE,
                target={"type": "github_actions", "repo": "acme/frontend", "secret": "AWS_ACCESS_KEY_ID"},
                compensation={"action": "restore_old_secret_value"},
                requires_confirmation=True,
                status=StepStatus.PENDING,
            ),
            RotationStep(
                workspace_id=wid, rotation_id=rotation.id, idx=2,
                kind=StepKind.VERIFY,
                target={"type": "github_actions", "repo": "acme/frontend", "workflow": "verify-creds.yml"},
                compensation=None,
                requires_confirmation=False,
                status=StepStatus.PENDING,
            ),
            RotationStep(
                workspace_id=wid, rotation_id=rotation.id, idx=3,
                kind=StepKind.REVOKE,
                target={"type": "aws_iam", "account": "123456789012", "key_id": "AKIAIOSFODNN7EXAMPLE"},
                compensation={"action": "reactivate_old_key"},
                requires_confirmation=True,
                status=StepStatus.PENDING,
            ),
        ]
        db.add_all(steps)

        # ── Seed audit entries ────────────────────────────────────────────
        # Use direct inserts (not the audit() helper) to avoid advisory-lock
        # overhead during seeding — we're already in a single transaction.
        _audit_entries = [
            ("detection.finding_confirmed", "finding", str(finding.id),
             None, {"state": "confirmed"}),
            ("investigation.started", "investigation", str(investigation.id),
             None, {"status": "running"}),
            ("investigation.complete", "investigation", str(investigation.id),
             {"status": "running"}, {"status": "complete", "coverage": investigation.coverage}),
            ("severity.computed", "secret", str(sid),
             None, {"score": 87, "bucket": "critical"}),
            ("rotation.proposed", "rotation", str(rotation.id),
             None, {"status": "proposed"}),
            ("rotation.plan_ready", "rotation", str(rotation.id),
             {"status": "proposed"}, {"status": "pending_approval"}),
        ]
        from api.db.models.audit import AuditLog
        import hashlib as _hl, json as _json
        prev = "0" * 64
        for action, ttype, tid, before, after in _audit_entries:
            payload = {"workspace_id": str(wid), "actor": DEMO_ACTOR, "action": action,
                       "target_type": ttype, "target_id": tid,
                       "before": before, "after": after, "correlation_id": session_id,
                       "created_at": datetime.now(timezone.utc).isoformat()}
            new_hash = _hl.sha256(
                (prev + _json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)).encode()
            ).hexdigest()
            entry = AuditLog(
                workspace_id=str(wid), actor=DEMO_ACTOR, action=action,
                target_type=ttype, target_id=tid, before=before, after=after,
                correlation_id=session_id, prev_hash=prev, hash=new_hash,
            )
            db.add(entry)
            await db.flush()
            prev = new_hash

        logger.info("demo.seeded", workspace_id=str(wid), session_id=session_id)

    # ── Issue demo JWT ────────────────────────────────────────────────────
    token = _issue_demo_token(str(wid), expires_at)

    return DemoSessionResult(
        session_id=session_id,
        workspace_id=str(wid),
        token=token,
        expires_at=expires_at,
    )


async def get_demo_session(db: AsyncSession, session_id: str) -> dict | None:
    """Return session info if the demo workspace is still alive, else None."""
    from sqlalchemy import select
    from api.db.models.workspace import Workspace

    result = await db.execute(
        select(Workspace.id, Workspace.expires_at)
        .where(Workspace.demo_session_id == session_id)
        .where(Workspace.kind == WorkspaceKind.DEMO)
    )
    row = result.first()
    if row is None:
        return None

    ws_id, expires_at = row
    alive = expires_at > datetime.now(timezone.utc)
    return {
        "session_id": session_id,
        "workspace_id": str(ws_id),
        "alive": alive,
        "expires_at": expires_at.isoformat(),
    }


async def simulate_failure(db: AsyncSession, session_id: str) -> dict | None:
    """
    Simulate a rotation failure + rollback on the demo workspace's rotation.

    Transitions: pending_approval → provisioning → distributing → verifying
                 → revoking (FAIL) → rolling_back → rolled_back

    Done synchronously (no real connector calls) to demonstrate the full
    state machine. M6 will show this with live SSE step-by-step.
    """
    from sqlalchemy import select, update
    from api.db.models.rotation import Rotation, RotationStep
    from api.db.models.workspace import Workspace
    from api.services.redis import publish

    # Captured inside the transaction for use after commit (SSE)
    _wid: str | None = None
    _rotation_id: str | None = None

    # Single transaction — workspace lookup must be INSIDE to avoid auto-begin
    # conflicting with the explicit begin() call (InvalidRequestError).
    async with db.begin():
        # ── Find the demo workspace ───────────────────────────────────────
        ws_result = await db.execute(
            select(Workspace.id)
            .where(Workspace.demo_session_id == session_id)
            .where(Workspace.kind == WorkspaceKind.DEMO)
        )
        ws_row = ws_result.first()
        if ws_row is None:
            return None
        wid = ws_row[0]
        _wid = str(wid)

        # ── Find the rotation ─────────────────────────────────────────────
        rot_result = await db.execute(
            select(Rotation)
            .where(Rotation.workspace_id == wid)
            .where(Rotation.status == RotationStatus.PENDING_APPROVAL)
        )
        rotation = rot_result.scalar_one_or_none()
        if rotation is None:
            return {"error": "no_pending_rotation", "workspace_id": _wid}
        _rotation_id = str(rotation.id)

        # ── Advance steps: 0-2 done, 3 failed (revoke step) ──────────────
        await db.execute(
            update(RotationStep)
            .where(RotationStep.rotation_id == rotation.id)
            .where(RotationStep.idx.in_([0, 1, 2]))
            .values(status=StepStatus.DONE, executed_at=datetime.now(timezone.utc))
        )
        await db.execute(
            update(RotationStep)
            .where(RotationStep.rotation_id == rotation.id)
            .where(RotationStep.idx == 3)
            .values(
                status=StepStatus.FAILED,
                executed_at=datetime.now(timezone.utc),
                error="Simulated: AWS IAM DeleteAccessKey returned AccessDenied",
            )
        )
        # Compensation: distribute (1) and provision (0) are undone
        await db.execute(
            update(RotationStep)
            .where(RotationStep.rotation_id == rotation.id)
            .where(RotationStep.idx.in_([0, 1]))
            .values(status=StepStatus.COMPENSATED)
        )

        # ── Transition rotation to rolled_back ────────────────────────────
        await db.execute(
            update(Rotation)
            .where(Rotation.id == rotation.id)
            .values(status=RotationStatus.ROLLED_BACK, updated_at=datetime.now(timezone.utc))
        )

        # ── Audit trail ───────────────────────────────────────────────────
        for action, after in [
            ("rotation.approved",              {"status": "provisioning"}),
            ("rotation.step.provision.done",   {"step": 0, "kind": "provision"}),
            ("rotation.step.distribute.done",  {"step": 1, "kind": "distribute"}),
            ("rotation.step.verify.done",      {"step": 2, "kind": "verify"}),
            ("rotation.step.revoke.failed",    {"step": 3, "error": "AccessDenied"}),
            ("rotation.rolling_back",          {"status": "rolling_back"}),
            ("rotation.rolled_back",           {"status": "rolled_back", "note": "old key still valid"}),
        ]:
            await audit(
                db, _wid, DEMO_ACTOR, action,
                target_type="rotation", target_id=_rotation_id,
                after=after, correlation_id=session_id,
            )

    # ── Publish SSE events after commit (fire-and-forget) ─────────────────
    try:
        for event_type, payload in [
            ("rotation.rolling_back", {"rotation_id": _rotation_id}),
            ("rotation.rolled_back",  {"rotation_id": _rotation_id, "note": "old key still valid"}),
        ]:
            await publish(_wid, event_type, payload)
    except Exception:
        pass

    return {
        "workspace_id": _wid,
        "rotation_id": _rotation_id,
        "final_status": "rolled_back",
        "message": "Simulated revoke failure — rollback succeeded, old key is still valid.",
    }


def _issue_demo_token(workspace_id: str, expires_at: datetime) -> str:
    payload = {
        "sub": DEMO_USER_SUB,
        "workspace_id": workspace_id,
        "role": "owner",
        "name": "Demo User",
        "is_demo": True,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
