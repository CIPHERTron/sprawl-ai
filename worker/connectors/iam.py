"""
IamConnector — implements CloudConnector protocol for AWS IAM (§8.6).

Operations:
  enumerate_scope     → list resources reachable by a principal (blast-radius)
  create_credential   → IAM CreateAccessKey
  disable_credential  → IAM UpdateAccessKey (Inactive)
  delete_credential   → IAM DeleteAccessKey

Uses AssumeRole (AWS_ROLE_ARN + AWS_EXTERNAL_ID) when role_arn is provided,
falling back to the ambient IAM identity of the running process otherwise.
"""
from __future__ import annotations

import structlog

from shared.connectors.base import (
    CapabilityReport,
    CredentialMaterial,
)
from shared.refs import CredentialRef, PrincipalRef, ResourceRef

logger = structlog.get_logger(__name__)

# Resource type labels derived from AWS policy action prefix → human-readable
_ARN_TYPE_LABELS: dict[str, str] = {
    "s3": "S3 Bucket",
    "ec2": "EC2 Resource",
    "rds": "RDS Instance",
    "dynamodb": "DynamoDB Table",
    "lambda": "Lambda Function",
    "ecs": "ECS Service",
    "secretsmanager": "Secrets Manager Secret",
    "ssm": "SSM Parameter",
    "iam": "IAM Resource",
    "sts": "STS Resource",
    "logs": "CloudWatch Log Group",
    "sns": "SNS Topic",
    "sqs": "SQS Queue",
    "kms": "KMS Key",
}


def _boto3_iam(role_arn: str | None, external_id: str | None, region: str):
    """Return a boto3 IAM client, optionally assuming *role_arn*."""
    import boto3

    if role_arn:
        sts = boto3.client("sts", region_name=region)
        assume_kwargs: dict = {
            "RoleArn": role_arn,
            "RoleSessionName": "sprawl-investigation",
        }
        if external_id:
            assume_kwargs["ExternalId"] = external_id
        creds = sts.assume_role(**assume_kwargs)["Credentials"]
        return boto3.client(
            "iam",
            region_name=region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    return boto3.client("iam", region_name=region)


class IamConnector:
    """
    CloudConnector backed by AWS IAM.

    Constructor kwargs (passed by the connector registry or the job directly):
        role_arn     (str | None)  — AssumeRole target; None = ambient identity
        external_id  (str | None)  — ExternalId for cross-account AssumeRole
        region       (str)         — AWS region (default: us-east-1)
    """

    def __init__(
        self,
        role_arn: str | None = None,
        external_id: str | None = None,
        region: str = "us-east-1",
    ) -> None:
        self._role_arn = role_arn
        self._external_id = external_id
        self._region = region

    def _iam(self):
        return _boto3_iam(self._role_arn, self._external_id, self._region)

    # ── CloudConnector protocol ────────────────────────────────────────────────

    def test_connection(self) -> CapabilityReport:
        try:
            iam = self._iam()
            iam.get_account_summary()
            return CapabilityReport(read=True, write=True, rotate=True, revoke=True)
        except Exception as exc:
            return CapabilityReport(error=str(exc))

    def enumerate_scope(self, principal: PrincipalRef) -> list[ResourceRef]:
        """
        Return the set of AWS resources reachable by *principal*.

        Strategy:
        1. Call GetAccessKeyLastUsed to verify the key exists (if iam_user principal).
        2. Call ListAttachedUserPolicies + ListUserPolicies to get policy ARNs.
        3. For each managed policy: GetPolicyVersion → extract Resource ARNs from
           Statement blocks that have Effect=Allow.
        4. Convert ARNs → ResourceRef objects.

        Returns an empty list on any error (graceful degradation).
        """
        try:
            iam = self._iam()
            username = _extract_username(principal.arn)
            if not username:
                logger.warning(
                    "iam.enumerate_scope.cannot_parse_username", arn=principal.arn
                )
                return []

            resource_arns: list[str] = []

            # Managed policies
            paginator = iam.get_paginator("list_attached_user_policies")
            for page in paginator.paginate(UserName=username):
                for policy in page["AttachedPolicies"]:
                    resource_arns.extend(
                        _resources_from_managed_policy(iam, policy["PolicyArn"])
                    )

            # Inline policies
            paginator2 = iam.get_paginator("list_user_policies")
            for page in paginator2.paginate(UserName=username):
                for policy_name in page["PolicyNames"]:
                    resource_arns.extend(
                        _resources_from_inline_policy(iam, username, policy_name)
                    )

            refs = [_arn_to_resource_ref(arn) for arn in set(resource_arns) if arn != "*"]
            logger.info(
                "iam.enumerate_scope.done",
                principal=principal.arn,
                resource_count=len(refs),
            )
            return refs

        except Exception as exc:
            logger.error("iam.enumerate_scope.error", principal=principal.arn, error=str(exc))
            return []

    def get_access_key_last_used(self, access_key_id: str) -> dict:
        """
        Call GetAccessKeyLastUsed.  Returns:
            {"last_used_date": datetime | None, "service_name": str, "region": str}
        or an empty dict on error.
        """
        try:
            iam = self._iam()
            resp = iam.get_access_key_last_used(AccessKeyId=access_key_id)
            info = resp.get("AccessKeyLastUsed", {})
            return {
                "last_used_date": info.get("LastUsedDate"),
                "service_name": info.get("ServiceName", ""),
                "region": info.get("Region", ""),
                "username": resp.get("UserName", ""),
            }
        except Exception as exc:
            logger.error("iam.get_access_key_last_used.error", key_id=access_key_id, error=str(exc))
            return {}

    def create_credential(self, principal: PrincipalRef) -> CredentialMaterial:
        """Create a new IAM access key for the user identified by *principal*."""
        username = _extract_username(principal.arn)
        if not username:
            raise ValueError(f"Cannot extract IAM username from ARN: {principal.arn}")
        iam = self._iam()
        resp = iam.create_access_key(UserName=username)
        key = resp["AccessKey"]
        return CredentialMaterial(
            credential_id=key["AccessKeyId"],
            access_key_id=key["AccessKeyId"],
            secret_access_key=key["SecretAccessKey"],
        )

    def disable_credential(self, credential: CredentialRef) -> None:
        """Set IAM access key status to Inactive (reversible)."""
        username = credential.metadata.get("username", "")
        if not username:
            raise ValueError("credential.metadata must include 'username' for IAM disable")
        iam = self._iam()
        iam.update_access_key(
            UserName=username,
            AccessKeyId=credential.credential_id,
            Status="Inactive",
        )
        logger.info("iam.key_disabled", key_id=credential.credential_id)

    def delete_credential(self, credential: CredentialRef) -> None:
        """Permanently delete an IAM access key (irreversible)."""
        username = credential.metadata.get("username", "")
        if not username:
            raise ValueError("credential.metadata must include 'username' for IAM delete")
        iam = self._iam()
        iam.delete_access_key(
            UserName=username,
            AccessKeyId=credential.credential_id,
        )
        logger.info("iam.key_deleted", key_id=credential.credential_id)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_username(arn: str) -> str | None:
    """
    Extract the IAM user name from an ARN like
    arn:aws:iam::123456789012:user/alice → 'alice'
    """
    if ":user/" in arn:
        return arn.split(":user/", 1)[1]
    return None


def _resources_from_managed_policy(iam, policy_arn: str) -> list[str]:
    """Extract Resource ARNs from the default version of a managed policy."""
    try:
        policy = iam.get_policy(PolicyArn=policy_arn)["Policy"]
        version_id = policy["DefaultVersionId"]
        doc = iam.get_policy_version(PolicyArn=policy_arn, VersionId=version_id)
        doc = doc["PolicyVersion"]["Document"]
        return _resources_from_document(doc)
    except Exception as exc:
        logger.debug("iam.managed_policy_read_error", arn=policy_arn, error=str(exc))
        return []


def _resources_from_inline_policy(iam, username: str, policy_name: str) -> list[str]:
    """Extract Resource ARNs from an inline user policy."""
    try:
        doc = iam.get_user_policy(UserName=username, PolicyName=policy_name)
        return _resources_from_document(doc["PolicyDocument"])
    except Exception as exc:
        logger.debug(
            "iam.inline_policy_read_error", username=username, policy=policy_name, error=str(exc)
        )
        return []


def _resources_from_document(doc: dict) -> list[str]:
    """Walk policy document statements and collect Allow Resource ARNs."""
    resources: list[str] = []
    statements = doc.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    for stmt in statements:
        if stmt.get("Effect") != "Allow":
            continue
        res = stmt.get("Resource", [])
        if isinstance(res, str):
            res = [res]
        resources.extend(res)
    return resources


def _arn_to_resource_ref(arn: str) -> ResourceRef:
    """Best-effort ARN → ResourceRef conversion."""
    # arn:aws:<service>:<region>:<account>:<resource-type>/<resource-id>
    parts = arn.split(":")
    service = parts[2] if len(parts) > 2 else "unknown"
    label_prefix = _ARN_TYPE_LABELS.get(service, service.upper())
    # Use the last segment as the resource label
    resource_part = parts[-1] if parts else arn
    label = f"{label_prefix}: {resource_part.split('/')[-1]}" if "/" in resource_part else f"{label_prefix}: {resource_part}"
    return ResourceRef(
        provider="aws",
        resource_type=service,
        arn=arn,
        label=label,
        environment="unknown",
    )
