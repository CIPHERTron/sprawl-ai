"""
Distributed rotation lock — prevents two workers running the same rotation concurrently.

Key pattern: `lock:rotation:{secret_id}` in Redis.
  - Acquired with SET NX PX (atomic, TTL-guarded against dead workers).
  - Value = rotation_id so stale locks can be detected.
  - Used as an async context manager in run_rotation_step.

Safety: the lock is NOT a substitute for the DB-level `one_active_rotation`
partial unique index — it is an additional guard to prevent concurrent job
execution for the same secret while the DB constraint handles initial
uniqueness.
"""
from __future__ import annotations

import structlog
from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url

from worker.config import worker_settings

logger = structlog.get_logger(__name__)

LOCK_TTL_MS = 5 * 60 * 1000  # 5 minutes (matches arq job_timeout)
LOCK_PREFIX  = "lock:rotation:"


class LockNotAcquiredError(Exception):
    """Raised when the rotation lock could not be acquired."""


class RotationLock:
    """
    Async Redis lock for a single rotation run.

    Usage (context manager):
        async with RotationLock(secret_id, rotation_id) as lock:
            await advance_rotation(...)

    Usage (manual):
        lock = RotationLock(secret_id, rotation_id)
        acquired = await lock.acquire()
        if not acquired:
            raise LockNotAcquiredError(...)
        try:
            ...
        finally:
            await lock.release()
    """

    def __init__(self, secret_id: str, rotation_id: str) -> None:
        self._secret_id  = secret_id
        self._rotation_id = rotation_id
        self._key = f"{LOCK_PREFIX}{secret_id}"
        self._client: Redis | None = None

    # ── Core operations ────────────────────────────────────────────────────────

    async def acquire(self) -> bool:
        """
        Try to acquire the lock.  Returns True on success, False if already held.
        Uses SET NX with a TTL so dead workers don't block permanently.
        """
        client = await self._get_client()
        acquired = await client.set(
            self._key,
            self._rotation_id,
            nx=True,
            px=LOCK_TTL_MS,
        )
        if acquired:
            logger.debug("rotation_lock.acquired", secret_id=self._secret_id, rotation_id=self._rotation_id)
        else:
            held_by = await client.get(self._key)
            logger.debug(
                "rotation_lock.already_held",
                secret_id=self._secret_id,
                held_by=held_by,
            )
        return bool(acquired)

    async def release(self) -> None:
        """Release the lock only if we still hold it (compare-and-delete)."""
        client = await self._get_client()
        # Lua CAS-delete: only delete if the value matches our rotation_id
        script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
        """
        result = await client.eval(script, 1, self._key, self._rotation_id)
        if result:
            logger.debug("rotation_lock.released", secret_id=self._secret_id)
        else:
            logger.warning(
                "rotation_lock.release_skipped_not_owner",
                secret_id=self._secret_id,
                rotation_id=self._rotation_id,
            )
        await client.aclose()
        self._client = None

    async def extend(self) -> None:
        """Reset the TTL on an already-held lock (call periodically for long steps)."""
        client = await self._get_client()
        await client.pexpire(self._key, LOCK_TTL_MS)

    # ── Context manager ────────────────────────────────────────────────────────

    async def __aenter__(self) -> "RotationLock":
        acquired = await self.acquire()
        if not acquired:
            raise LockNotAcquiredError(
                f"Rotation lock for secret {self._secret_id} is held by another job"
            )
        return self

    async def __aexit__(self, *_) -> None:
        await self.release()

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _get_client(self) -> Redis:
        if self._client is None:
            self._client = redis_from_url(worker_settings.redis_url, decode_responses=True)
        return self._client
