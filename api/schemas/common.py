"""
Standard request/response envelope shapes used across all API endpoints.

Every response is either:
  {"ok": true,  "data": {...}}
  {"ok": false, "error": {"code": "...", "message": "...", "request_id": "..."}}
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    ok: bool = False
    error: ErrorDetail


class OkEnvelope(BaseModel, Generic[T]):
    ok: bool = True
    data: T


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class PageEnvelope(BaseModel, Generic[T]):
    ok: bool = True
    data: list[T]
    meta: PageMeta


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def page(data: list, total: int, limit: int, offset: int) -> dict:
    return {
        "ok": True,
        "data": data,
        "meta": {"total": total, "limit": limit, "offset": offset},
    }
