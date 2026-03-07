"""Admin auth/group/token management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from bloom_lims.api.v1.dependencies import APIUser, require_admin
from bloom_lims.auth.services.groups import GroupService
from bloom_lims.auth.services.user_api_tokens import UserAPITokenService
from bloom_lims.db import BLOOMdb3

router = APIRouter(prefix="/admin", tags=["Admin Auth"])


class GroupMemberAddRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


def _require_id(value: str | None, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    return normalized


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
    actor_user_id = _require_id(user.user_id, field_name="authenticated user_id")
    member_user_id = _require_id(payload.user_id, field_name="user_id")
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = GroupService(bdb.session)
        member = service.add_user_to_group(
            group_code=group_code,
            user_id=member_user_id,
            added_by=actor_user_id,
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
    actor_user_id = _require_id(user.user_id, field_name="authenticated user_id")
    normalized_member_user_id = _require_id(member_user_id, field_name="member_user_id")
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = GroupService(bdb.session)
        removed = service.remove_user_from_group(
            group_code=group_code,
            user_id=normalized_member_user_id,
            removed_by=actor_user_id,
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
    actor_user_id = _require_id(user.user_id, field_name="authenticated user_id")
    normalized_token_id = _require_id(token_id, field_name="token_id")
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = UserAPITokenService(bdb.session)
        revoked = service.revoke_token(
            token_id=normalized_token_id,
            actor_user_id=actor_user_id,
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
    normalized_token_id = _require_id(token_id, field_name="token_id")
    bdb = BLOOMdb3(app_username=user.email)
    try:
        service = UserAPITokenService(bdb.session)
        usage_rows = service.repo.get_usage_logs(token_id=normalized_token_id, limit=limit)
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

