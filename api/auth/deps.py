"""
FastAPI dependency functions for authentication and workspace resolution.

Usage:
    @router.get("/secrets")
    async def list_secrets(
        workspace_id: str,
        claims: TokenClaims = Depends(require_auth),
        db: AsyncSession = Depends(get_db),
    ): ...

    # Demo or public endpoints that allow unauthenticated access:
    @router.get("/demo/session/{id}")
    async def get_demo(claims: TokenClaims | None = Depends(optional_auth)): ...
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.auth.jwt import TokenClaims, TokenError, decode_token

_bearer = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TokenClaims:
    """Dependency that enforces a valid JWT. Returns claims or raises 401."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def optional_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TokenClaims | None:
    """Dependency that decodes a JWT if present, returns None otherwise."""
    if credentials is None:
        return None
    try:
        return decode_token(credentials.credentials)
    except TokenError:
        return None


def require_role(*roles: str):
    """
    Factory that returns a dependency enforcing one of the given roles.

    Usage:
        Depends(require_role("owner", "approver"))
    """
    async def _check(claims: TokenClaims = Depends(require_auth)) -> TokenClaims:
        if claims.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient_role",
            )
        return claims

    return _check
