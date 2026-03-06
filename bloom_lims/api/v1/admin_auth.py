"""Admin auth/group/token management endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from bloom_lims.api.v1.dependencies import APIUser, require_admin
from bloom_lims.auth.rbac import Role
from bloom_lims.auth.services.groups import GroupService
from bloom_lims.auth.services.tool_api_users import (
    ToolAPIUserCreateInput,
    ToolAPIUserService,
    ToolAPIUserTokenGrantInput,
)
from bloom_lims.auth.services.user_api_tokens import UserAPITokenService
from bloom_lims.config import get_settings
from bloom_lims.db import BLOOMdb3

router = APIRouter(prefix="/admin", tags=["Admin Auth"])


class GroupMemberAddRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


class ToolInitialTokenRequest(BaseModel):
    token_name: str | None = Field(default=None, min_length=3, max_length=120)
    scope: str | None = None
    expires_in_days: int | None = Field(default=None, ge=1)
    note: str | None = None
    atlas_callback_uri: str | None = None
    atlas_tenant_uuid: str | None = None


class ToolAPIUserCreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=200)
    external_system_key: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    role: str = Role.INTERNAL_READ_WRITE.value
    issue_initial_token: bool = True
    initial_token: ToolInitialTokenRequest | None = None
    metadata: dict | None = None


class ToolAPIUserGrantTokenRequest(BaseModel):
    token_name: str = Field(..., min_length=3, max_length=120)
    scope: str = Field(..., min_length=1, max_length=40)
    expires_in_days: int | None = Field(default=None, ge=1)
    note: str | None = None
    atlas_callback_uri: str | None = None
    atlas_tenant_uuid: str | None = None


def _parse_uuid(value: str, *, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}") from exc


def _token_to_dict(token, revision) -> dict:
    now = datetime.now(UTC)
    return {
        "token_id": str(token.id),
        "user_id": str(token.user_id),
        "token_name": token.token_name,
        "token_prefix": token.token_prefix,
        "scope": token.scope,
        "atlas_callback_uri": token.atlas_callback_uri,
        "atlas_tenant_uuid": token.atlas_tenant_uuid,
        "status": revision.status,
        "expires_at": revision.expires_at.isoformat(),
        "last_used_at": revision.last_used_at.isoformat() if revision.last_used_at else None,
        "revoked_at": revision.revoked_at.isoformat() if revision.revoked_at else None,
        "created_at": token.created_at.isoformat() if token.created_at else None,
        "is_expired": revision.expires_at < now,
    }


@router.get("/groups")
async def list_groups(user: APIUser = Depends(require_admin)):
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = GroupService(bdb.session)
        groups = service.list_groups(include_inactive=True)
        return {
            "items": [
                {
                    "id": str(group.id),
                    "group_code": group.group_code,
                    "name": group.name,
                    "description": group.description,
                    "is_system_group": group.is_system_group,
                    "is_active": group.is_active,
                    "revision_no": group.revision_no,
                    "created_at": group.created_at.isoformat() if group.created_at else None,
                }
                for group in groups
            ],
            "total": len(groups),
        }
    finally:
        bdb.close()


@router.get("/groups/{group_code}/members")
async def list_group_members(group_code: str, user: APIUser = Depends(require_admin)):
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = GroupService(bdb.session)
        members = service.list_group_members(group_code=group_code)
        return {
            "items": [
                {
                    "id": str(member.id),
                    "group_id": str(member.group_id),
                    "group_code": member.group_code,
                    "user_id": str(member.user_id),
                    "is_active": member.is_active,
                    "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                    "added_by": str(member.added_by) if member.added_by else None,
                    "deactivated_at": member.deactivated_at.isoformat() if member.deactivated_at else None,
                    "deactivated_by": str(member.deactivated_by) if member.deactivated_by else None,
                }
                for member in members
            ],
            "total": len(members),
        }
    finally:
        bdb.close()


@router.post("/groups/{group_code}/members")
async def add_group_member(
    group_code: str,
    payload: GroupMemberAddRequest,
    user: APIUser = Depends(require_admin),
):
    actor_uuid = _parse_uuid(user.user_id, field_name="authenticated user_id")
    member_uuid = _parse_uuid(payload.user_id, field_name="user_id")
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = GroupService(bdb.session)
        member = service.add_user_to_group(
            group_code=group_code,
            user_id=member_uuid,
            added_by=actor_uuid,
        )
        return {
            "id": str(member.id),
            "group_id": str(member.group_id),
            "group_code": member.group_code,
            "user_id": str(member.user_id),
            "is_active": member.is_active,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        bdb.close()


@router.delete("/groups/{group_code}/members/{member_user_id}")
async def remove_group_member(
    group_code: str,
    member_user_id: str,
    user: APIUser = Depends(require_admin),
):
    actor_uuid = _parse_uuid(user.user_id, field_name="authenticated user_id")
    member_uuid = _parse_uuid(member_user_id, field_name="member_user_id")
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = GroupService(bdb.session)
        removed = service.remove_user_from_group(
            group_code=group_code,
            user_id=member_uuid,
            removed_by=actor_uuid,
        )
        if removed is None:
            raise HTTPException(status_code=404, detail="Group membership not found")
        return {
            "id": str(removed.id),
            "group_id": str(removed.group_id),
            "group_code": removed.group_code,
            "user_id": str(removed.user_id),
            "is_active": removed.is_active,
        }
    finally:
        bdb.close()


@router.get("/user-tokens")
async def list_admin_user_tokens(user: APIUser = Depends(require_admin)):
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = UserAPITokenService(bdb.session)
        rows = service.list_all_tokens()
        return {
            "items": [
                {
                    "token_id": str(token.id),
                    "user_id": str(token.user_id),
                    "token_name": token.token_name,
                    "token_prefix": token.token_prefix,
                    "scope": token.scope,
                    "atlas_callback_uri": token.atlas_callback_uri,
                    "atlas_tenant_uuid": token.atlas_tenant_uuid,
                    "status": revision.status,
                    "expires_at": revision.expires_at.isoformat(),
                    "last_used_at": revision.last_used_at.isoformat() if revision.last_used_at else None,
                    "revoked_at": revision.revoked_at.isoformat() if revision.revoked_at else None,
                    "created_at": token.created_at.isoformat() if token.created_at else None,
                    "usage_count": service.repo.count_usage(token_id=token.id),
                }
                for token, revision in rows
            ],
            "total": len(rows),
        }
    finally:
        bdb.close()


@router.delete("/user-tokens/{token_id}")
async def revoke_admin_user_token(
    token_id: str,
    user: APIUser = Depends(require_admin),
):
    actor_uuid = _parse_uuid(user.user_id, field_name="authenticated user_id")
    token_uuid = _parse_uuid(token_id, field_name="token_id")
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = UserAPITokenService(bdb.session)
        revoked = service.revoke_token(
            token_id=token_uuid,
            actor_user_id=actor_uuid,
            actor_roles=user.roles,
        )
        if revoked is None:
            raise HTTPException(status_code=404, detail="Token not found")
        token, revision = revoked
        return {
            "token_id": str(token.id),
            "user_id": str(token.user_id),
            "token_name": token.token_name,
            "status": revision.status,
            "revoked_at": revision.revoked_at.isoformat() if revision.revoked_at else None,
        }
    finally:
        bdb.close()


@router.get("/user-tokens/{token_id}/usage")
async def get_admin_token_usage(
    token_id: str,
    limit: int = Query(100, ge=1, le=2000),
    user: APIUser = Depends(require_admin),
):
    token_uuid = _parse_uuid(token_id, field_name="token_id")
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = UserAPITokenService(bdb.session)
        usage_rows = service.repo.get_usage_logs(token_id=token_uuid, limit=limit)
        return {
            "items": [
                {
                    "id": str(row.id),
                    "token_id": str(row.token_id),
                    "user_id": str(row.user_id),
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
    finally:
        bdb.close()


@router.get("/tool-api-users")
async def list_tool_api_users(user: APIUser = Depends(require_admin)):
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = ToolAPIUserService(bdb.session)
        summaries = service.list_tool_users_with_token_summary(include_inactive=True)
        return {
            "items": [
                {
                    "user_id": str(summary.tool_user.id),
                    "euid": summary.tool_user.euid,
                    "display_name": summary.tool_user.display_name,
                    "external_system_key": summary.tool_user.external_system_key,
                    "description": summary.tool_user.description,
                    "role": summary.tool_user.role,
                    "is_active": summary.tool_user.is_active,
                    "created_at": summary.tool_user.created_at.isoformat()
                    if summary.tool_user.created_at
                    else None,
                    "token_count": summary.token_count,
                    "active_token_count": summary.active_token_count,
                    "last_token_issued_at": summary.last_token_issued_at.isoformat()
                    if summary.last_token_issued_at
                    else None,
                }
                for summary in summaries
            ],
            "total": len(summaries),
        }
    finally:
        bdb.close()


@router.post("/tool-api-users")
async def create_tool_api_user(
    payload: ToolAPIUserCreateRequest,
    user: APIUser = Depends(require_admin),
):
    actor_uuid = _parse_uuid(user.user_id, field_name="authenticated user_id")
    settings = get_settings()
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = ToolAPIUserService(bdb.session)
        created = service.create_tool_user(
            actor_user_id=actor_uuid,
            actor_roles=user.roles,
            actor_groups=user.groups,
            payload=ToolAPIUserCreateInput(
                display_name=payload.display_name,
                external_system_key=payload.external_system_key,
                description=payload.description,
                role=payload.role,
                metadata=payload.metadata if isinstance(payload.metadata, dict) else None,
                issue_initial_token=payload.issue_initial_token,
                initial_token_name=payload.initial_token.token_name if payload.initial_token else None,
                initial_token_scope=payload.initial_token.scope if payload.initial_token else None,
                initial_token_expires_in_days=(
                    payload.initial_token.expires_in_days if payload.initial_token else None
                ),
                initial_token_note=payload.initial_token.note if payload.initial_token else None,
                initial_token_atlas_callback_uri=(
                    payload.initial_token.atlas_callback_uri if payload.initial_token else None
                ),
                initial_token_atlas_tenant_uuid=(
                    payload.initial_token.atlas_tenant_uuid if payload.initial_token else None
                ),
            ),
            default_token_days=settings.auth.tool_api_default_token_days,
            max_token_days=settings.auth.tool_api_max_token_days,
        )
        response = {
            "tool_user": {
                "user_id": str(created.tool_user.id),
                "euid": created.tool_user.euid,
                "display_name": created.tool_user.display_name,
                "external_system_key": created.tool_user.external_system_key,
                "description": created.tool_user.description,
                "role": created.tool_user.role,
                "is_active": created.tool_user.is_active,
                "created_at": created.tool_user.created_at.isoformat()
                if created.tool_user.created_at
                else None,
            }
        }
        if created.token_result is not None:
            response["token"] = _token_to_dict(created.token_result.token, created.token_result.revision)
            response["plaintext_token"] = created.token_result.plaintext_token
            response["message"] = "Store this token now; it will not be shown again."
        return response
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        if "external_system_key" in detail.lower() and "already exists" in detail.lower():
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    finally:
        bdb.close()


@router.post("/tool-api-users/{tool_user_id}/tokens")
async def grant_tool_api_user_token(
    tool_user_id: str,
    payload: ToolAPIUserGrantTokenRequest,
    user: APIUser = Depends(require_admin),
):
    actor_uuid = _parse_uuid(user.user_id, field_name="authenticated user_id")
    tool_user_uuid = _parse_uuid(tool_user_id, field_name="tool_user_id")
    settings = get_settings()
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = ToolAPIUserService(bdb.session)
        created = service.grant_token(
            tool_user_id=tool_user_uuid,
            actor_user_id=actor_uuid,
            actor_roles=user.roles,
            actor_groups=user.groups,
            payload=ToolAPIUserTokenGrantInput(
                token_name=payload.token_name,
                scope=payload.scope,
                expires_in_days=payload.expires_in_days,
                note=payload.note,
                atlas_callback_uri=payload.atlas_callback_uri,
                atlas_tenant_uuid=payload.atlas_tenant_uuid,
            ),
            default_token_days=settings.auth.tool_api_default_token_days,
            max_token_days=settings.auth.tool_api_max_token_days,
        )
        return {
            "token": _token_to_dict(created.token, created.revision),
            "plaintext_token": created.plaintext_token,
            "message": "Store this token now; it will not be shown again.",
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        bdb.close()
