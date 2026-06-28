"""
Investigator node — makes real connector calls to collect enriched context.

Operations (each is gracefully skipped if creds are absent):
  1. GitHub: fetch file snippets from finding locations
  2. Vault:  verify_store (confirm secret is present in store)
  3. IAM:    GetAccessKeyLastUsed (confirm key is still active)

Writes enriched fields back to state["context"].
"""
from __future__ import annotations

import asyncio
import functools

import structlog

from worker.agents.guardrails import guardrail
from worker.agents.state import InvestigationState, SecretContext
from worker.connectors.github import GitHubConnector
from worker.connectors.iam import IamConnector
from worker.connectors.vault import VaultStoreConnector

logger = structlog.get_logger(__name__)


@guardrail(timeout_s=60, node_name="investigator")
async def investigator_node(state: InvestigationState) -> InvestigationState:
    """
    Enriches state["context"] with data from connectors.
    Never raises — each sub-call is wrapped in try/except.
    """
    context: SecretContext | None = state.get("context")
    if context is None:
        return state  # type: ignore[return-value]

    # Run all three connector operations concurrently
    github_task = asyncio.create_task(_fetch_github_context(context))
    vault_task   = asyncio.create_task(_check_vault(context))
    iam_task     = asyncio.create_task(_check_iam(context))

    github_snippets, store_present, iam_info = await asyncio.gather(
        github_task, vault_task, iam_task, return_exceptions=True
    )

    # Apply results (ignore exceptions — they were logged in each sub-function)
    if isinstance(github_snippets, list):
        for loc, snippet in github_snippets:
            loc.file_snippet = snippet

    if isinstance(store_present, bool):
        context.store_present = store_present

    if isinstance(iam_info, dict):
        context.last_used_date = str(iam_info.get("last_used_date") or "")
        context.last_used_service = iam_info.get("service_name", "")

    logger.info(
        "investigator.done",
        secret_id=str(context.secret_id),
        store_present=context.store_present,
        last_used=context.last_used_date,
        locations_with_snippet=sum(1 for loc in context.locations if loc.file_snippet),
    )

    events = list(state.get("events") or [])
    events.append({"type": "node.complete", "node": "investigator"})

    return {**state, "context": context, "events": events}  # type: ignore[return-value]


# ── Sub-operations ─────────────────────────────────────────────────────────────

async def _fetch_github_context(context: SecretContext) -> list:
    """Fetch file snippets for finding locations.  Returns list of (loc, snippet)."""
    if not context.github_token and not context.locations:
        return []
    results = []
    gh = GitHubConnector(token=context.github_token)
    try:
        loop = asyncio.get_event_loop()
        for loc in context.locations[:5]:  # cap at 5 to avoid rate limits
            try:
                snippet = await loop.run_in_executor(
                    None,
                    functools.partial(
                        gh.get_file_content,
                        repo=loc.repo,
                        path=loc.file_path,
                        ref=loc.commit_sha,
                    ),
                )
                results.append((loc, snippet))
            except Exception as exc:
                logger.debug("investigator.github_snippet_error", path=loc.file_path, error=str(exc))
    finally:
        gh.close()
    return results


async def _check_vault(context: SecretContext) -> bool:
    """Return True if secret exists and is readable in Vault."""
    if not context.store_path:
        return False
    try:
        loop = asyncio.get_event_loop()
        connector = VaultStoreConnector(
            addr=context.vault_addr,
            role_id=context.vault_role_id,
            secret_id=context.vault_secret_id,
        )
        from shared.refs import StoreRef
        ref = StoreRef(connector_type="vault", connector_id="", path=context.store_path)
        result = await loop.run_in_executor(None, connector.verify_store, ref)
        return result.success
    except Exception as exc:
        logger.debug("investigator.vault_check_error", path=context.store_path, error=str(exc))
        return False


async def _check_iam(context: SecretContext) -> dict:
    """Call GetAccessKeyLastUsed for the principal's access key (if available)."""
    if not context.principal_arn:
        return {}
    # Extract access key ID from principal ARN or metadata
    # The principal ARN is arn:aws:iam::acct:user/username — not a key ID.
    # The actual access key ID (AKIA...) must come from the secret value which
    # we never read directly (C1 constraint).  Here we check IAM user's keys list.
    try:
        loop = asyncio.get_event_loop()
        iam = IamConnector(
            role_arn=context.aws_role_arn,
            external_id=context.aws_external_id,
        )
        from worker.connectors.iam import _extract_username
        username = _extract_username(context.principal_arn)
        if not username:
            return {}

        def _list_and_check():
            client = iam._iam()
            resp = client.list_access_keys(UserName=username)
            keys = resp.get("AccessKeyMetadata", [])
            if not keys:
                return {}
            # Return info for the first active key
            active = [k for k in keys if k.get("Status") == "Active"]
            key = active[0] if active else keys[0]
            key_id = key["AccessKeyId"]
            return iam.get_access_key_last_used(key_id)

        return await loop.run_in_executor(None, _list_and_check)
    except Exception as exc:
        logger.debug("investigator.iam_check_error", principal=context.principal_arn, error=str(exc))
        return {}
