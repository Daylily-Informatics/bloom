"""TapDB action recording for execution queue mutations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from daylily_tapdb import require_seeded_template
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bloom_lims.config import get_settings
from bloom_lims.domain.beta_actions import BETA_ACTION_TEMPLATE_PREFIX
from bloom_lims.tapdb_adapter import (
    action_instance,
    action_instance_lineage,
    generic_template,
)

EXECUTION_ACTION_GROUP = "execution_queue"
EXECUTION_ACTION_TEMPLATE_PREFIX = BETA_ACTION_TEMPLATE_PREFIX

_ACTION_TEMPLATE_DEFINITIONS: dict[str, dict[str, str]] = {
    "register_worker": {
        "name": "Register Worker",
        "description": "Registers or updates a persistent execution worker.",
    },
    "heartbeat_worker": {
        "name": "Heartbeat Worker",
        "description": "Updates worker heartbeat and liveness metadata.",
    },
    "claim_queue_item": {
        "name": "Claim Queue Item",
        "description": "Creates a lease and STARTED execution record for a queued subject.",
    },
    "renew_queue_lease": {
        "name": "Renew Queue Lease",
        "description": "Renews an active queue lease.",
    },
    "release_queue_lease": {
        "name": "Release Queue Lease",
        "description": "Releases an active queue lease without completion.",
    },
    "complete_queue_execution": {
        "name": "Complete Queue Execution",
        "description": "Completes queued execution and advances subject state.",
    },
    "fail_queue_execution": {
        "name": "Fail Queue Execution",
        "description": "Marks a queued execution attempt as retryable or terminal failure.",
    },
    "place_execution_hold": {
        "name": "Place Execution Hold",
        "description": "Places an explicit execution hold on a subject.",
    },
    "release_execution_hold": {
        "name": "Release Execution Hold",
        "description": "Releases an explicit execution hold.",
    },
    "requeue_subject": {
        "name": "Requeue Subject",
        "description": "Moves a subject into READY state for a queue/action pair.",
    },
    "cancel_subject_execution": {
        "name": "Cancel Subject Execution",
        "description": "Cancels execution for a subject.",
    },
    "expire_queue_lease": {
        "name": "Expire Queue Lease",
        "description": "Expires a stale queue lease for observability cleanup.",
    },
}


def _parse_template_code(template_code: str) -> tuple[str, str, str, str]:
    parts = [part for part in str(template_code or "").strip("/").split("/") if part]
    if len(parts) != 4:
        raise ValueError(f"Invalid template code: {template_code!r}")
    return parts[0], parts[1], parts[2], parts[3]


class ExecutionQueueActionRecorder:
    """Persists first-class action records for execution queue mutations."""

    def __init__(self, session: Session, *, domain_code: str | None = None):
        self.session = session
        self.domain_code = (
            str(domain_code or get_settings().tapdb.domain_code or "").strip().upper()
        )
        if not self.domain_code:
            raise ValueError("domain_code is required for Bloom template resolution")

    def find_replay(
        self,
        *,
        action_key: str,
        subject_euid: str | None,
        idempotency_key: str,
    ) -> action_instance | None:
        if action_key not in _ACTION_TEMPLATE_DEFINITIONS:
            raise ValueError(f"Unsupported execution action key: {action_key}")
        template = self._ensure_action_template(action_key)
        category = str(template.category or "").strip()
        if not category:
            raise ValueError(
                f"Seeded execution action template is missing a category: {action_key}"
            )
        clean_subject_euid = str(subject_euid or "").strip()
        clean_idempotency_key = str(idempotency_key or "").strip()
        if not clean_subject_euid or not clean_idempotency_key:
            return None

        stmt = (
            select(action_instance)
            .where(
                action_instance.category == category,
                action_instance.type == EXECUTION_ACTION_GROUP,
                action_instance.subtype == action_key,
                action_instance.is_deleted.is_(False),
                func.jsonb_extract_path_text(
                    action_instance.json_addl, "subject_lookup_euid"
                )
                == clean_subject_euid,
                func.jsonb_extract_path_text(
                    action_instance.json_addl, "idempotency_key"
                )
                == clean_idempotency_key,
            )
            .order_by(action_instance.created_dt.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def record(
        self,
        *,
        target_instance,
        action_key: str,
        captured_data: dict[str, Any],
        result: dict[str, Any],
        executed_by: str | None,
        subject_euid: str | None,
        worker_euid: str | None,
        lease_euid: str | None,
        idempotency_key: str | None,
        payload_hash: str | None,
    ) -> action_instance:
        if action_key not in _ACTION_TEMPLATE_DEFINITIONS:
            raise ValueError(f"Unsupported execution action key: {action_key}")

        template = self._ensure_action_template(action_key)
        category = str(template.category or "").strip()
        if not category:
            raise ValueError(
                f"Seeded execution action template is missing a category: {action_key}"
            )
        now = datetime.now(UTC).isoformat()
        action_definition = {
            "action_group": EXECUTION_ACTION_GROUP,
            "action_key": action_key,
            "name": _ACTION_TEMPLATE_DEFINITIONS[action_key]["name"],
            "description": _ACTION_TEMPLATE_DEFINITIONS[action_key]["description"],
        }
        action_record = action_instance(
            name=f"{action_key}@{target_instance.euid}",
            polymorphic_discriminator="action_instance",
            category=category,
            type=EXECUTION_ACTION_GROUP,
            subtype=action_key,
            version="1.0",
            template_uid=template.uid,
            json_addl={
                "action_group": EXECUTION_ACTION_GROUP,
                "action_key": action_key,
                "action_definition": action_definition,
                "captured_data": captured_data,
                "result": result,
                "executed_by": executed_by,
                "executed_at": now,
                "subject_lookup_euid": str(subject_euid or "").strip(),
                "worker_lookup_euid": str(worker_euid or "").strip(),
                "lease_lookup_euid": str(lease_euid or "").strip(),
                "idempotency_key": str(idempotency_key or "").strip(),
                "payload_hash": str(payload_hash or "").strip(),
                "target_euid": target_instance.euid,
            },
            bstatus="completed",
        )
        self.session.add(action_record)
        self.session.flush()

        lineage = action_instance_lineage(
            name=f"{action_record.euid}->{target_instance.euid}",
            parent_type="action:execution_queue",
            child_type=(
                f"{target_instance.category}:{target_instance.type}:"
                f"{target_instance.subtype}:{target_instance.version}"
            ),
            relationship_type="executed_on",
            parent_instance_uid=action_record.uid,
            child_instance_uid=target_instance.uid,
            category="action",
            type="action",
            subtype="executed_on",
            version="1.0",
            polymorphic_discriminator="action_instance_lineage",
            bstatus="active",
            json_addl={"properties": {"executed_at": now}},
        )
        self.session.add(lineage)
        self.session.flush()
        return action_record

    def _ensure_action_template(self, action_key: str) -> generic_template:
        template_code = f"{EXECUTION_ACTION_TEMPLATE_PREFIX}/{EXECUTION_ACTION_GROUP}/{action_key}/1.0/"
        return require_seeded_template(
            self.session,
            template_code,
            domain_code=self.domain_code,
            expected_prefix=EXECUTION_ACTION_TEMPLATE_PREFIX,
            app_name="Bloom",
        )
