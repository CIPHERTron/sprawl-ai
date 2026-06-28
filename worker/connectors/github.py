"""
GitHubConnector — thin httpx client for reading file context from GitHub repos.

Used by the investigator node to fetch file content at the commit SHA recorded
in a Finding, so the agent can understand what code is using the secret.

Authentication: GitHub personal access token (GITHUB_TOKEN env var).
If no token is configured, all methods return empty/None gracefully.
"""
from __future__ import annotations

import base64

import httpx
import structlog

logger = structlog.get_logger(__name__)

_GITHUB_API = "https://api.github.com"


class GitHubConnector:
    """
    Read-only GitHub API client for investigation context.

    Args:
        token: GitHub personal access token.  Pass None to run in degraded mode
               (all calls return empty results without raising).
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token
        headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=_GITHUB_API,
            headers=headers,
            timeout=10.0,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_file_content(
        self,
        repo: str,
        path: str,
        ref: str | None = None,
    ) -> str | None:
        """
        Fetch the decoded text content of *path* in *repo* at optional *ref*
        (branch, tag, or commit SHA).

        Returns:
            File content as UTF-8 string, or None if unavailable / no token.
        """
        if not self._token:
            logger.debug("github.no_token — skipping file fetch", repo=repo, path=path)
            return None

        try:
            params: dict = {}
            if ref:
                params["ref"] = ref
            resp = self._client.get(f"/repos/{repo}/contents/{path}", params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return data.get("content", "")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.debug("github.file_not_found", repo=repo, path=path, ref=ref)
            else:
                logger.warning(
                    "github.file_fetch_error",
                    repo=repo,
                    path=path,
                    status=exc.response.status_code,
                )
            return None
        except Exception as exc:
            logger.warning("github.file_fetch_exception", repo=repo, path=path, error=str(exc))
            return None

    def get_commit_info(self, repo: str, sha: str) -> dict:
        """
        Return a summary dict for *sha* in *repo*.
        Returns {} on any error.
        """
        if not self._token:
            return {}
        try:
            resp = self._client.get(f"/repos/{repo}/commits/{sha}")
            resp.raise_for_status()
            data = resp.json()
            commit = data.get("commit", {})
            return {
                "sha": sha,
                "message": commit.get("message", "")[:200],
                "author": commit.get("author", {}).get("name", ""),
                "date": commit.get("author", {}).get("date", ""),
            }
        except Exception as exc:
            logger.debug("github.commit_info_error", repo=repo, sha=sha, error=str(exc))
            return {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
