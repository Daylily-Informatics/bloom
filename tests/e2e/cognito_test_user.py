from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError

from bloom_lims.config import get_settings


DEFAULT_EMAIL = "johnm+test@lsmc.com"
DEFAULT_PASSWORD = "CodexPlaywright1!"
DEFAULT_NAME = "John M Test"
SERVICE_GROUPS = ("platform-admin",)


@dataclass(frozen=True)
class E2ECredentials:
    email: str
    password: str
    user_pool_id: str
    region: str
    sub: str


def _cognito_client(region: str, *, profile: str = ""):
    session = boto3.Session(
        profile_name=(os.getenv("E2E_AWS_PROFILE") or profile or os.getenv("AWS_PROFILE") or None),
        region_name=region,
    )
    return session.client("cognito-idp", region_name=region)


def _attributes(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("Name") or "").strip(): str(item.get("Value") or "").strip()
        for item in payload.get("UserAttributes", []) or []
        if str(item.get("Name") or "").strip()
    }


def _get_user(client, *, pool_id: str, email: str) -> dict[str, Any]:
    return client.admin_get_user(UserPoolId=pool_id, Username=email)


def _ensure_group(client, *, pool_id: str, group_name: str) -> None:
    try:
        client.get_group(UserPoolId=pool_id, GroupName=group_name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        client.create_group(
            UserPoolId=pool_id,
            GroupName=group_name,
            Description=f"E2E auto-created group {group_name}",
        )


def _ensure_membership(client, *, pool_id: str, email: str, group_name: str) -> None:
    try:
        client.admin_add_user_to_group(
            UserPoolId=pool_id,
            Username=email,
            GroupName=group_name,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        _ensure_group(client, pool_id=pool_id, group_name=group_name)
        client.admin_add_user_to_group(
            UserPoolId=pool_id,
            Username=email,
            GroupName=group_name,
        )


def ensure_test_user() -> E2ECredentials:
    settings = get_settings()
    region = str(os.getenv("E2E_COGNITO_REGION") or settings.auth.cognito_region or "").strip()
    pool_id = str(os.getenv("E2E_COGNITO_USER_POOL_ID") or settings.auth.cognito_user_pool_id or "").strip()
    profile = str(settings.aws.profile or "").strip()
    if not region or not pool_id:
        raise RuntimeError("Bloom E2E tests require Cognito region and user pool ID.")

    email = os.getenv("E2E_USER_EMAIL", DEFAULT_EMAIL).strip().lower()
    password = os.getenv("E2E_USER_PASSWORD", DEFAULT_PASSWORD).strip() or DEFAULT_PASSWORD
    client = _cognito_client(region, profile=profile)

    try:
        user_payload = _get_user(client, pool_id=pool_id, email=email)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "UserNotFoundException":
            raise
        client.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            TemporaryPassword=password,
            MessageAction="SUPPRESS",
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": DEFAULT_NAME},
            ],
        )
        user_payload = _get_user(client, pool_id=pool_id, email=email)

    client.admin_update_user_attributes(
        UserPoolId=pool_id,
        Username=email,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": DEFAULT_NAME},
        ],
    )
    client.admin_set_user_password(
        UserPoolId=pool_id,
        Username=email,
        Password=password,
        Permanent=True,
    )

    for group_name in SERVICE_GROUPS:
        _ensure_membership(client, pool_id=pool_id, email=email, group_name=group_name)

    user_payload = _get_user(client, pool_id=pool_id, email=email)
    sub = _attributes(user_payload).get("sub", "")
    os.environ["E2E_USER_EMAIL"] = email
    os.environ["E2E_USER_PASSWORD"] = password
    return E2ECredentials(
        email=email,
        password=password,
        user_pool_id=pool_id,
        region=region,
        sub=sub,
    )
