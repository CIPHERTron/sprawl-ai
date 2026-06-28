"""
Deterministic severity scoring engine (§8.8).

Formula:
    raw = w_scope * scope_factor(graph)
        + w_env  * env_factor(environment)
        + w_exp  * exposure_factor(exposure_status, secret_type)

    score = round(raw * 100)   # normalised 0..100
    bucket = "critical" | "high" | "medium" | "low"  (§8.8 thresholds)

All inputs are plain Python values — no DB / network calls inside this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── Weight constants ──────────────────────────────────────────────────────────

W_SCOPE = 0.40
W_ENV   = 0.25
W_EXP   = 0.35

# ── Bucket thresholds (inclusive lower bound) ──────────────────────────────────

BUCKET_THRESHOLDS = [
    (80, "critical"),
    (60, "high"),
    (35, "medium"),
    (0,  "low"),
]


# ── Factor tables ─────────────────────────────────────────────────────────────

_ENV_FACTORS: dict[str, float] = {
    # DB enum values: prod | staging | dev | unknown
    "prod":    1.0,
    "staging": 0.6,
    "dev":     0.3,
    "unknown": 0.5,
    # Aliases (from free-text inputs not yet normalised)
    "production":  1.0,
    "development": 0.3,
    "test":        0.2,
}

_EXPOSURE_FACTORS: dict[str, float] = {
    # DB enum values: unknown | live_inferred | public_leak | inactive
    "public_leak":   1.0,
    "live_inferred": 0.7,
    "inactive":      0.1,
    "unknown":       0.5,
    # Aliases for programmatic use
    "confirmed":  0.8,
    "suspected":  0.5,
}

# Higher-privilege secret types get a bump in exposure factor
_SECRET_TYPE_BUMP: dict[str, float] = {
    "aws_access_key":  0.15,
    "iam_access_key":  0.15,
    "database_url":    0.10,
    "database":        0.10,
    "api_key":         0.05,
    "oauth_token":     0.05,
    "github_token":    0.10,
    "private_key":     0.15,
}


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class SeverityFactors:
    """Intermediate factors (useful for LLM explanation and audit trail)."""
    scope_factor:    float = 0.0
    env_factor:      float = 0.0
    exposure_factor: float = 0.0
    resource_count:  int   = 0
    has_high_priv:   bool  = False
    environment:     str   = "unknown"
    exposure_status: str   = "unknown"
    secret_type:     str   = "unknown"


@dataclass
class SeverityResult:
    score:       int           = 0
    bucket:      str           = "low"
    factors:     SeverityFactors = field(default_factory=SeverityFactors)
    explanation: str | None    = None


# ── Engine ────────────────────────────────────────────────────────────────────

class SeverityEngine:
    """
    Stateless scorer.  All methods are pure functions of their arguments.
    """

    def score(
        self,
        *,
        resource_count: int,
        high_privilege_resources: int,
        environment: str,
        exposure_status: str,
        secret_type: str,
    ) -> SeverityResult:
        """
        Compute the deterministic severity score.

        Args:
            resource_count: Number of AWS resources reachable by the principal.
            high_privilege_resources: Resources in high-value services (IAM, RDS, S3).
            environment: Secret's deployment environment label.
            exposure_status: How the secret was found / confirmed.
            secret_type: Canonical secret type string.

        Returns:
            SeverityResult with score (0-100), bucket, and factor breakdown.
        """
        sf = self._scope_factor(resource_count, high_privilege_resources)
        ef = _ENV_FACTORS.get(environment.lower(), 0.5)
        xf = self._exposure_factor(exposure_status, secret_type)

        raw = W_SCOPE * sf + W_ENV * ef + W_EXP * xf
        score = min(100, round(raw * 100))
        bucket = _to_bucket(score)

        factors = SeverityFactors(
            scope_factor=sf,
            env_factor=ef,
            exposure_factor=xf,
            resource_count=resource_count,
            has_high_priv=high_privilege_resources > 0,
            environment=environment,
            exposure_status=exposure_status,
            secret_type=secret_type,
        )
        return SeverityResult(score=score, bucket=bucket, factors=factors)

    # ── Factor helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _scope_factor(resource_count: int, high_priv: int) -> float:
        """
        Map resource counts to a 0..1 scope factor.
        Diminishing returns — log2-based so 1 resource ≠ 0 but 100 resources ≠ 1.
        High-privilege resources are weighted 2× in the count.
        """
        import math
        effective = resource_count + high_priv  # high-priv counted twice
        if effective == 0:
            return 0.0
        # log2(effective + 1) → caps naturally around log2(100+1) ≈ 6.6
        raw = math.log2(effective + 1) / 7.0
        return min(1.0, raw)

    @staticmethod
    def _exposure_factor(exposure_status: str, secret_type: str) -> float:
        base = _EXPOSURE_FACTORS.get(exposure_status.lower(), 0.5)
        bump = _SECRET_TYPE_BUMP.get(secret_type.lower(), 0.0)
        return min(1.0, base + bump)


def _to_bucket(score: int) -> str:
    for threshold, bucket in BUCKET_THRESHOLDS:
        if score >= threshold:
            return bucket
    return "low"
