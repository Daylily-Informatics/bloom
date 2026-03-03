"""User API token self-service endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from bloom_lims.api.v1.dependencies import APIUser, require_api_auth
from bloom_lims.auth.services.user_api_tokens import TokenCreateInput, UserAPITokenService
from bloom_lims.db import BLOOMdb3

router = APIRouter(prefix="/user-tokens", tags=["User API Tokens"])


class TokenCreateRequest(BaseModel):
    token_name: str = Field(..., min_length=3, max_length=120)
    scope: str = Field(default="internal_ro")
    expires_in_days: int = Field(default=2, ge=1, le=3650)
    note: str | None = None


def _parse_user_uuid(user: APIUser) -> uuid.UUID:
    try:
        return uuid.UUID(str(user.user_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Authenticated user_id is not a UUID") from exc


def _token_row_to_dict(
    token,
    revision,
    *,
    usage_count: int,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    is_expired = revision.expires_at < now
    return {
        "token_id": str(token.id),
        "user_id": str(token.user_id),
        "token_name": token.token_name,
        "token_prefix": token.token_prefix,
        "scope": token.scope,
        "status": revision.status,
        "expires_at": revision.expires_at.isoformat(),
        "last_used_at": revision.last_used_at.isoformat() if revision.last_used_at else None,
        "revoked_at": revision.revoked_at.isoformat() if revision.revoked_at else None,
        "revocation_reason": revision.revocation_reason,
        "created_at": token.created_at.isoformat() if token.created_at else None,
        "usage_count": usage_count,
        "is_expired": is_expired,
    }


@router.get("")
async def list_user_tokens(user: APIUser = Depends(require_api_auth)):
    user_uuid = _parse_user_uuid(user)
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = UserAPITokenService(bdb.session)
        rows = service.list_user_tokens(user_id=user_uuid)
        items = [
            _token_row_to_dict(
                token,
                revision,
                usage_count=service.repo.count_usage(token_id=token.id),
            )
            for token, revision in rows
        ]
        return {"items": items, "total": len(items)}
    finally:
        bdb.close()


@router.post("")
async def create_user_token(
    payload: TokenCreateRequest,
    user: APIUser = Depends(require_api_auth),
):
    user_uuid = _parse_user_uuid(user)
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = UserAPITokenService(bdb.session)
        service.groups.ensure_system_groups()
        created = service.create_token(
            owner_user_id=user_uuid,
            actor_user_id=user_uuid,
            actor_roles=user.roles,
            actor_groups=user.groups,
            payload=TokenCreateInput(
                token_name=payload.token_name,
                scope=payload.scope,
                expires_in_days=payload.expires_in_days,
                note=payload.note,
            ),
        )
        return {
            "token": _token_row_to_dict(
                created.token,
                created.revision,
                usage_count=0,
            ),
            "plaintext_token": created.plaintext_token,
            "message": "Store this token now; it will not be shown again.",
        }
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    finally:
        bdb.close()


@router.delete("/{token_id}")
async def revoke_user_token(
    token_id: str,
    user: APIUser = Depends(require_api_auth),
):
    user_uuid = _parse_user_uuid(user)
    try:
        token_uuid = uuid.UUID(token_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid token_id") from exc

    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = UserAPITokenService(bdb.session)
        revoked = service.revoke_token(
            token_id=token_uuid,
            actor_user_id=user_uuid,
            actor_roles=user.roles,
        )
        if revoked is None:
            raise HTTPException(status_code=404, detail="Token not found")
        token, revision = revoked
        return {
            "token": _token_row_to_dict(
                token,
                revision,
                usage_count=service.repo.count_usage(token_id=token.id),
            ),
            "message": "Token revoked",
        }
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    finally:
        bdb.close()


@router.get("/{token_id}/usage")
async def get_user_token_usage(
    token_id: str,
    limit: int = Query(100, ge=1, le=1000),
    user: APIUser = Depends(require_api_auth),
):
    user_uuid = _parse_user_uuid(user)
    try:
        token_uuid = uuid.UUID(token_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid token_id") from exc

    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = UserAPITokenService(bdb.session)
        usage_rows = service.usage_for_token(
            token_id=token_uuid,
            actor_user_id=user_uuid,
            actor_roles=user.roles,
            limit=limit,
        )
        return {
            "items": [
                {
                    "id": str(row.id),
                    "token_id": str(row.token_id),
                    "endpoint": row.endpoint,
                    "http_method": row.http_method,
                    "response_status": row.response_status,
                    "ip_address": row.ip_address,
                    "user_agent": row.user_agent,
                    "request_metadata": row.request_metadata,
                    "request_timestamp": row.request_timestamp.isoformat() if row.request_timestamp else None,
                }
                for row in usage_rows
            ],
            "total": len(usage_rows),
        }
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    finally:
        bdb.close()
