"""Bloom adapter for TapDB modern action execution."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from daylily_tapdb.actions import ActionDispatcher
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.tapdb_adapter import action_instance, action_instance_lineage, generic_instance


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


def _normalize_action_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result

    payload: dict[str, Any] = {
        "status": "success",
        "message": "Action completed",
    }

    if isinstance(result, str):
        message = result.strip()
        if message:
            payload["message"] = message
        return payload

    result_euid = getattr(result, "euid", None)
    if result_euid is not None:
        payload["result_euid"] = str(result_euid)

    return payload


def _coerce_action_template_uid(action_template_uid: Any) -> Any:
    if not isinstance(action_template_uid, str):
        return action_template_uid

    candidate = action_template_uid.strip()
    if not candidate:
        return candidate
    if candidate.isdigit():
        return int(candidate)

    try:
        return uuid.UUID(candidate)
    except ValueError:
        return candidate


class BloomTapDBActionDispatcher(ActionDispatcher):
    """Executes Bloom object actions via TapDB dispatcher semantics."""

    def __init__(self, executor: Any):
        super().__init__()
        self.executor = executor

    def __getattr__(self, name: str):
        if not name.startswith("do_action_"):
            raise AttributeError(name)

        encoded_action_key = name[len("do_action_") :]
        action_slug = _normalize_action_slug(encoded_action_key)
        if not action_slug:
            raise AttributeError(name)

        handler_name = f"do_action_{action_slug}"
        target_handler = getattr(self.executor, handler_name, None)
        if not callable(target_handler):
            raise AttributeError(name)

        def _wrapped(instance: generic_instance, action_ds: dict[str, Any], captured_data: dict[str, Any]):
            payload = copy.deepcopy(action_ds or {})
            merged_captured = dict(payload.get("captured_data") or {})
            merged_captured.update(captured_data or {})
            payload["captured_data"] = merged_captured

            if handler_name == "do_action_set_object_status":
                result = target_handler(
                    instance.euid,
                    payload,
                    payload.get("action_group"),
                    payload.get("_raw_action_key", encoded_action_key),
                )
                return _normalize_action_result(result)

            result = target_handler(instance.euid, payload)
            return _normalize_action_result(result)

        return _wrapped

    def _update_action_tracking(
        self,
        instance: generic_instance,
        action_group: str,
        action_key: str,
        result: dict[str, Any],
    ) -> None:
        action_groups = (instance.json_addl or {}).get("action_groups", {})
        if not isinstance(action_groups, dict):
            return
        group_data = action_groups.get(action_group)
        if not isinstance(group_data, dict):
            return
        actions = group_data.get("actions", {})
        if not isinstance(actions, dict):
            return

        entry = actions.get(action_key)
        if entry is None and action_key.startswith("/"):
            entry = actions.get(action_key.lstrip("/"))
        if entry is None:
            with_trailing = f"{action_key.rstrip('/')}/"
            entry = actions.get(with_trailing)
        if not isinstance(entry, dict):
            return

        exec_count = int(entry.get("action_executed", "0"))
        entry["action_executed"] = str(exec_count + 1)
        entry.setdefault("executed_datetime", []).append(datetime.now(UTC).isoformat())
        flag_modified(instance, "json_addl")

    def _create_action_record(
        self,
        session: Session,
        instance: generic_instance,
        action_group: str,
        action_key: str,
        action_ds: dict[str, Any],
        captured_data: dict[str, Any],
        result: dict[str, Any],
        user: str | None,
    ) -> None:
        action_template_uid = action_ds.get("action_template_uid")
        if not action_template_uid:
            raise ValueError("action_ds is missing required 'action_template_uid'")
        action_template_uid = _coerce_action_template_uid(action_template_uid)

        action_subtype = _normalize_action_slug(action_key) or "unknown_action"
        executed_at = datetime.now(UTC).isoformat()
        action_record = action_instance(
            name=f"{action_subtype}@{instance.euid}",
            polymorphic_discriminator="action_instance",
            category="action",
            type="action",
            subtype=action_subtype,
            version="1.0",
            template_uid=action_template_uid,
            json_addl={
                "action_group": action_group,
                "action_key": action_key,
                "action_definition": action_ds,
                "captured_data": captured_data,
                "result": result,
                "executed_by": user,
                "executed_at": executed_at,
            },
            bstatus="completed",
        )
        session.add(action_record)
        session.flush()

        lineage = action_instance_lineage(
            name=f"{action_record.euid}->{instance.euid}",
            parent_type="action:action",
            child_type=(
                f"{instance.category}:{instance.type}:{instance.subtype}:{instance.version}"
            ),
            relationship_type="executed_on",
            parent_instance_uid=action_record.uid,
            child_instance_uid=instance.uid,
            category="action",
            type="action",
            subtype="executed_on",
            version="1.0",
            polymorphic_discriminator="action_instance_lineage",
            bstatus="active",
            json_addl={"properties": {"executed_at": executed_at}},
        )
        session.add(lineage)
        session.flush()
