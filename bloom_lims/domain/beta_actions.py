"""Modern TapDB action recording for Bloom beta operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from daylily_tapdb.sequences import ensure_instance_prefix_sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from bloom_lims.tapdb_adapter import (
    action_instance,
    action_instance_lineage,
    generic_template,
)

BETA_ACTION_GROUP = "beta_lab"
BETA_ACTION_TEMPLATE_PREFIX = "BXA"

_ACTION_TEMPLATE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "register_accepted_material": {
        "name": "Register Accepted Material",
        "description": "Creates accepted Bloom beta material and links Atlas fulfillment-item references.",
    },
    "create_empty_tube": {
        "name": "Create Empty Tube",
        "description": "Creates a Bloom beta tube/container with Atlas linkage references.",
    },
    "update_tube": {
        "name": "Update Tube",
        "description": "Updates a Bloom beta tube/container status and Atlas linkage references.",
    },
    "update_specimen": {
        "name": "Update Specimen",
        "description": "Updates Bloom beta specimen Atlas collection-event reference metadata.",
    },
    "move_material_to_queue": {
        "name": "Move Material To Queue",
        "description": "Moves Bloom beta material into a canonical beta queue.",
    },
    "claim_material_in_queue": {
        "name": "Claim Material In Queue",
        "description": "Creates a work claim for queued beta material.",
    },
    "release_claim": {
        "name": "Release Claim",
        "description": "Releases a work claim for queued beta material.",
    },
    "reserve_material": {
        "name": "Reserve Material",
        "description": "Creates a reservation lock on beta material.",
    },
    "release_reservation": {
        "name": "Release Reservation",
        "description": "Releases a reservation lock on beta material.",
    },
    "consume_material": {
        "name": "Consume Material",
        "description": "Records beta material consumption to prevent stage reuse.",
    },
    "create_extraction": {
        "name": "Create Extraction",
        "description": "Creates a Bloom beta extraction output from queued material.",
    },
    "record_post_extract_qc": {
        "name": "Record Post Extract QC",
        "description": "Records post-extraction QC and optional queue progression.",
    },
    "create_library_prep": {
        "name": "Create Library Prep",
        "description": "Creates a Bloom beta library-prep output from an extraction output.",
    },
    "create_pool": {
        "name": "Create Pool",
        "description": "Creates a Bloom beta sequencing pool from library-prep outputs.",
    },
    "create_run": {
        "name": "Create Run",
        "description": "Creates a Bloom beta sequencing run and sequenced assignments.",
    },
}


def _parse_template_code(template_code: str) -> tuple[str, str, str, str]:
    parts = [part for part in str(template_code or "").strip("/").split("/") if part]
    if len(parts) != 4:
        raise ValueError(f"Invalid template code: {template_code!r}")
    return parts[0], parts[1], parts[2], parts[3]


class BloomBetaActionRecorder:
    """Persists first-class TapDB action records for Bloom beta mutations."""

    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        target_instance,
        action_key: str,
        captured_data: dict[str, Any],
        result: dict[str, Any],
        executed_by: str | None,
    ) -> action_instance:
        if action_key not in _ACTION_TEMPLATE_DEFINITIONS:
            raise ValueError(f"Unsupported beta action key: {action_key}")

        template = self._ensure_action_template(action_key)
        now = datetime.now(UTC).isoformat()
        action_definition = {
            "action_group": BETA_ACTION_GROUP,
            "action_key": action_key,
            "name": _ACTION_TEMPLATE_DEFINITIONS[action_key]["name"],
            "description": _ACTION_TEMPLATE_DEFINITIONS[action_key]["description"],
        }
        action_record = action_instance(
            name=f"{action_key}@{target_instance.euid}",
            polymorphic_discriminator="action_instance",
            category="action",
            type=BETA_ACTION_GROUP,
            subtype=action_key,
            version="1.0",
            template_uid=template.uid,
            json_addl={
                "action_group": BETA_ACTION_GROUP,
                "action_key": action_key,
                "action_definition": action_definition,
                "captured_data": captured_data,
                "result": result,
                "executed_by": executed_by,
                "executed_at": now,
            },
            bstatus="completed",
        )
        self.session.add(action_record)
        self.session.flush()

        lineage = action_instance_lineage(
            name=f"{action_record.euid}->{target_instance.euid}",
            parent_type="action:beta_lab",
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
        ensure_instance_prefix_sequence(self.session, BETA_ACTION_TEMPLATE_PREFIX)
        template_code = f"action/{BETA_ACTION_GROUP}/{action_key}/1.0/"
        category, type_name, subtype, version = _parse_template_code(template_code)
        stmt = (
            select(generic_template)
            .where(
                generic_template.category == category,
                generic_template.type == type_name,
                generic_template.subtype == subtype,
                generic_template.version == version,
            )
            .limit(1)
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            if existing.is_deleted:
                existing.is_deleted = False
            if existing.instance_prefix != BETA_ACTION_TEMPLATE_PREFIX:
                existing.instance_prefix = BETA_ACTION_TEMPLATE_PREFIX
            return existing

        template = generic_template(
            name=_ACTION_TEMPLATE_DEFINITIONS[action_key]["name"],
            polymorphic_discriminator="action_template",
            category=category,
            type=type_name,
            subtype=subtype,
            version=version,
            instance_prefix=BETA_ACTION_TEMPLATE_PREFIX,
            instance_polymorphic_identity="action_instance",
            json_addl={
                "managed_by": "bloom",
                "domain": "beta_lab",
                "action_definition": {
                    "action_group": BETA_ACTION_GROUP,
                    "action_key": action_key,
                    "name": _ACTION_TEMPLATE_DEFINITIONS[action_key]["name"],
                    "description": _ACTION_TEMPLATE_DEFINITIONS[action_key]["description"],
                },
            },
            bstatus="active",
            is_singleton=False,
            is_deleted=False,
        )
        self.session.add(template)
        self.session.flush()
        return template
