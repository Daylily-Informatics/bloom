"""TapDB-pattern GUI action execution service."""

from __future__ import annotations

import copy
import logging
import secrets
from dataclasses import dataclass
from typing import Any

from bloom_lims.core.exceptions import BloomValidationError
from bloom_lims.core.tapdb_action_dispatcher import BloomTapDBActionDispatcher
from bloom_lims.db import BLOOMdb3
from bloom_lims.domain.base import BloomObj

logger = logging.getLogger(__name__)


@dataclass
class ActionExecuteRequest:
    euid: str
    action_group: str
    action_key: str
    captured_data: dict[str, Any]


class ActionExecutionError(Exception):
    """Structured error for action execution endpoints."""

    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        error_fields: list[str] | None = None,
        error_id: str | None = None,
    ):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.error_fields = error_fields or []
        self.error_id = error_id

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "detail": self.detail,
            "error_fields": self.error_fields,
        }
        if self.error_id:
            payload["error_id"] = self.error_id
        return payload


def _normalize_action_slug(action_key: str) -> str:
    raw = str(action_key or "").strip().strip("/")
    if not raw:
        return ""
    parts = [p for p in raw.split("/") if p]
    if len(parts) >= 3:
        raw = parts[2]
    elif parts:
        raw = parts[-1]
    return raw.replace("-", "_")


def normalize_action_execute_payload(payload: dict[str, Any]) -> ActionExecuteRequest:
    """Normalize strict action execute payload into a shared execute contract."""
    if not isinstance(payload, dict):
        raise ActionExecutionError(status_code=400, detail="Request body must be a JSON object")

    euid = str(payload.get("euid") or "").strip()
    action_group = str(payload.get("action_group") or "").strip()
    action_key = str(payload.get("action_key") or "").strip()

    if not euid:
        raise ActionExecutionError(status_code=400, detail="Missing required field: euid", error_fields=["euid"])
    if not action_group:
        raise ActionExecutionError(
            status_code=400,
            detail="Missing required field: action_group",
            error_fields=["action_group"],
        )
    if not action_key:
        raise ActionExecutionError(
            status_code=400,
            detail="Missing required field: action_key",
            error_fields=["action_key"],
        )
    if not isinstance(payload.get("captured_data"), dict):
        raise ActionExecutionError(
            status_code=400,
            detail="Missing required field: captured_data",
            error_fields=["captured_data"],
        )

    return ActionExecuteRequest(
        euid=euid,
        action_group=action_group,
        action_key=action_key,
        captured_data=copy.deepcopy(payload.get("captured_data") or {}),
    )


def _safe_get_by_euid(obj: BloomObj, euid: str):
    try:
        return obj.get_by_euid(euid)
    except Exception as exc:
        msg = str(exc).lower()
        if "not found" in msg or "no template found" in msg:
            return None
        raise


def _extract_required_fields_from_ui_schema(action_ds: dict[str, Any]) -> list[str]:
    required_fields: list[str] = []
    ui_schema = action_ds.get("ui_schema")
    if not isinstance(ui_schema, dict):
        return required_fields

    fields = ui_schema.get("fields")
    if not isinstance(fields, list):
        return required_fields

    for field in fields:
        if not isinstance(field, dict):
            continue
        if not field.get("required"):
            continue
        name = str(field.get("name") or "").strip()
        if name:
            required_fields.append(name)
    return required_fields


def _missing_required_fields(captured_data: dict[str, Any], required_fields: list[str]) -> list[str]:
    missing: list[str] = []

    def is_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        return False

    for field in required_fields:
        if is_missing(captured_data.get(field)):
            missing.append(field)

    return missing


def _resolve_action_definition(
    instance: Any,
    action_group: str,
    action_key: str,
    *,
    allow_missing_template_uid: bool = False,
) -> tuple[dict[str, Any], str]:
    action_groups = (instance.json_addl or {}).get("action_groups", {})
    if not isinstance(action_groups, dict):
        raise ActionExecutionError(
            status_code=404,
            detail=f"No action groups found on object {instance.euid}",
        )

    group_data = action_groups.get(action_group)
    if not isinstance(group_data, dict):
        raise ActionExecutionError(
            status_code=404,
            detail=f"Action group not found: {action_group}",
        )

    actions = group_data.get("actions", {})
    normalized_key = action_key.strip("/")
    action_data = None
    matched_key = action_key

    candidate_keys = [
        action_key,
        normalized_key,
        f"/{normalized_key}",
        f"/{normalized_key}/",
        f"{normalized_key}/",
    ]
    for candidate in candidate_keys:
        entry = actions.get(candidate)
        if isinstance(entry, dict):
            action_data = entry
            matched_key = candidate
            break

    if not isinstance(action_data, dict):
        raise ActionExecutionError(
            status_code=404,
            detail=f"Action not found: {action_key}",
        )

    resolved = copy.deepcopy(action_data)
    if not isinstance(resolved.get("captured_data"), dict):
        resolved["captured_data"] = {}
    if not resolved.get("action_template_uid") and not allow_missing_template_uid:
        raise ActionExecutionError(
            status_code=409,
            detail=(
                f"Action {action_key} is missing TapDB template metadata "
                "(action_template_uid)."
            ),
        )
    return resolved, matched_key


def _upgrade_active_action_definition(
    *,
    instance: Any,
    action_group: str,
    matched_action_key: str,
    action_definition: dict[str, Any],
    query_obj: BloomObj,
) -> dict[str, Any]:
    if action_definition.get("action_template_uid"):
        return action_definition

    template_code = str(
        action_definition.get("action_template_code") or matched_action_key or ""
    ).strip("/")
    parts = [part for part in template_code.split("/") if part]
    if len(parts) != 4 or parts[0] != "action":
        raise ActionExecutionError(
            status_code=409,
            detail=(
                f"Action {matched_action_key} is missing TapDB template metadata "
                "and cannot be upgraded from a retired legacy definition."
            ),
        )

    template = query_obj.Base.classes.generic_template
    action_template = (
        query_obj.session.query(template)
        .filter(
            template.is_deleted == False,  # noqa: E712
            template.category == "action",
            template.type == parts[1],
            template.subtype == parts[2],
            template.version == parts[3],
        )
        .one_or_none()
    )
    if action_template is None:
        raise ActionExecutionError(
            status_code=409,
            detail=(
                f"Action {matched_action_key} is missing TapDB template metadata "
                "and no exact modern action template exists for upgrade."
            ),
        )

    action_groups = (instance.json_addl or {}).get("action_groups", {})
    if not isinstance(action_groups, dict):
        return action_definition
    group_data = action_groups.get(action_group)
    if not isinstance(group_data, dict):
        return action_definition
    actions = group_data.get("actions", {})
    if not isinstance(actions, dict):
        return action_definition

    entry = actions.get(matched_action_key)
    if not isinstance(entry, dict):
        return action_definition

    upgraded_definition = copy.deepcopy(action_definition)
    upgraded_definition["action_template_uid"] = str(action_template.uid)
    upgraded_definition["action_template_euid"] = action_template.euid
    upgraded_definition["action_template_code"] = "/".join(parts)

    entry["action_template_uid"] = str(action_template.uid)
    entry["action_template_euid"] = action_template.euid
    entry["action_template_code"] = "/".join(parts)
    query_obj.session.flush()
    return upgraded_definition


def _infer_required_fields(
    action_definition: dict[str, Any],
    action_key: str,
) -> list[str]:
    method_name = str(action_definition.get("method_name") or "").strip()
    if method_name.startswith("do_action_"):
        slug = method_name.removeprefix("do_action_")
    else:
        slug = _normalize_action_slug(action_key)
    slug = slug.replace("-", "_")

    inferred: dict[str, list[str]] = {
        "set_object_status": ["object_status"],
        "add_relationships": ["lineage_type_to_create", "relationship_type", "euids"],
    }
    return inferred.get(slug, [])


def _build_action_ds(
    action_definition: dict[str, Any],
    captured_data: dict[str, Any],
    *,
    actor_email: str,
    actor_user_id: str | None,
    user_preferences: dict[str, Any] | None,
) -> dict[str, Any]:
    action_ds = copy.deepcopy(action_definition)
    action_ds["captured_data"] = {
        **(action_definition.get("captured_data") or {}),
        **(captured_data or {}),
    }

    prefs = user_preferences or {}
    action_ds["curr_user"] = actor_email or "bloomui-user"
    action_ds["curr_user_id"] = actor_user_id
    action_ds["lab"] = prefs.get("print_lab", "BLOOM")
    action_ds["printer_name"] = prefs.get("printer_name", "")
    resolved_label_style = prefs.get("label_zpl_style", "") or prefs.get(
        "label_style", ""
    )
    action_ds["label_style"] = resolved_label_style
    action_ds["label_zpl_style"] = resolved_label_style
    action_ds["alt_a"] = prefs.get("alt_a", "")
    action_ds["alt_b"] = prefs.get("alt_b", "")
    action_ds["alt_c"] = prefs.get("alt_c", "")
    action_ds["alt_d"] = prefs.get("alt_d", "")
    action_ds["alt_e"] = prefs.get("alt_e", "")
    return action_ds


def _resolve_executor(instance: Any, bdb: BLOOMdb3):
    return BloomObj(bdb)


def _map_exception(exc: Exception) -> ActionExecutionError:
    if isinstance(exc, ActionExecutionError):
        return exc

    if isinstance(exc, BloomValidationError):
        field = exc.details.get("field") if isinstance(exc.details, dict) else None
        fields = [field] if field else []
        return ActionExecutionError(status_code=400, detail=exc.message, error_fields=fields)

    if isinstance(exc, KeyError):
        field = str(exc).strip("'\"")
        return ActionExecutionError(
            status_code=400,
            detail=f"Missing required field: {field}",
            error_fields=[field],
        )

    msg = str(exc).strip() or "Action execution failed"
    if "No instance refs were provided" in msg:
        return ActionExecutionError(status_code=400, detail=msg, error_fields=["instance_refs"])
    if msg.startswith("Missing required field"):
        suffix = msg.split(":", 1)[1].strip() if ":" in msg else ""
        return ActionExecutionError(
            status_code=400,
            detail=msg,
            error_fields=[suffix] if suffix else [],
        )
    if "validation" in msg.lower() or "invalid" in msg.lower():
        return ActionExecutionError(status_code=400, detail=msg)

    error_id = f"error_{secrets.token_hex(12)}"
    logger.exception("Unhandled action execution error id=%s: %s", error_id, msg)
    return ActionExecutionError(
        status_code=500,
        detail=f"Action execution failed (error_id={error_id})",
        error_id=error_id,
    )


def execute_action_for_instance(
    request_data: ActionExecuteRequest,
    *,
    app_username: str,
    actor_email: str,
    actor_user_id: str | None,
    user_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute an action against an instance and return normalized response payload."""
    bdb = BLOOMdb3(app_username=app_username or "api-user")
    try:
        query_obj = BloomObj(bdb)
        instance = _safe_get_by_euid(query_obj, request_data.euid)
        if instance is None:
            raise ActionExecutionError(
                status_code=404,
                detail=f"Object not found: {request_data.euid}",
            )

        action_definition, matched_action_key = _resolve_action_definition(
            instance,
            request_data.action_group,
            request_data.action_key,
            allow_missing_template_uid=True,
        )
        action_definition = _upgrade_active_action_definition(
            instance=instance,
            action_group=request_data.action_group,
            matched_action_key=matched_action_key,
            action_definition=action_definition,
            query_obj=query_obj,
        )

        required_fields = _extract_required_fields_from_ui_schema(action_definition)
        if not required_fields:
            required_fields = _infer_required_fields(action_definition, request_data.action_key)

        missing_fields = _missing_required_fields(request_data.captured_data, required_fields)
        if missing_fields:
            field_list = ", ".join(missing_fields)
            raise ActionExecutionError(
                status_code=400,
                detail=f"Missing required fields: {field_list}",
                error_fields=missing_fields,
            )

        action_ds = _build_action_ds(
            action_definition,
            request_data.captured_data,
            actor_email=actor_email,
            actor_user_id=actor_user_id,
            user_preferences=user_preferences,
        )
        action_ds["action_key"] = request_data.action_key
        action_ds["action_group"] = request_data.action_group
        action_ds["_raw_action_key"] = request_data.action_key

        executor = _resolve_executor(instance, bdb)
        executor.set_actor_context(user_id=actor_user_id, email=actor_email)
        dispatcher = BloomTapDBActionDispatcher(executor)
        result = dispatcher.execute_action(
            session=bdb.session,
            instance=instance,
            action_group=request_data.action_group,
            action_key=request_data.action_key,
            action_ds=action_ds,
            captured_data=request_data.captured_data,
            create_action_record=True,
            user=actor_email,
        )

        response_status = "success"
        message = f"{request_data.action_key} performed for EUID {request_data.euid}"
        if isinstance(result, dict):
            result_status = str(result.get("status") or "").strip().lower()
            if result_status in {"error", "failed", "failure"}:
                detail = str(result.get("message") or "Action execution failed")
                raise ActionExecutionError(status_code=400, detail=detail)
            if result_status:
                response_status = result_status
            if result.get("message"):
                message = str(result.get("message"))
        elif isinstance(result, str) and result.strip():
            message = result.strip()

        return {
            "status": response_status,
            "message": message,
            "euid": request_data.euid,
            "action_group": request_data.action_group,
            "action_key": request_data.action_key,
        }

    except Exception as exc:  # mapped below to preserve consistent error schema
        raise _map_exception(exc) from exc
    finally:
        try:
            bdb.close()
        except Exception:
            pass
