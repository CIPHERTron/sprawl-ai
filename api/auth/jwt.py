"""
JWT decode + claims extraction.

Tokens are issued by Auth.js on the web service (M8). This module only
verifies and decodes them — it never issues tokens.

Expected JWT payload shape:
    {
      "sub":          "user-uuid",
      "workspace_id": "workspace-uuid",
      "role":         "owner" | "approver" | "viewer",
      "github_id":    12345,
      "name":         "Alice",
      "exp":          1234567890,
      "iat":          1234567890
    }
"""
from __future__ import annotations

from dataclasses import dataclass

from jose import JWTError, jwt

from api.config import settings


class TokenError(Exception):
    """Raised when JWT decode/validation fails."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    sub: str           # user UUID
    workspace_id: str
    role: str
    github_id: int | None
    name: str | None


def decode_token(token: str) -> TokenClaims:
    """
    Decode and verify a JWT. Raises TokenError on any failure so callers can
    convert it to a 401 without leaking internals.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise TokenError(str(exc)) from exc

    sub = payload.get("sub")
    workspace_id = payload.get("workspace_id")
    if not sub or not workspace_id:
        raise TokenError("Missing required claims: sub, workspace_id")

    return TokenClaims(
        sub=sub,
        workspace_id=workspace_id,
        role=payload.get("role", "viewer"),
        github_id=payload.get("github_id"),
        name=payload.get("name"),
    )
