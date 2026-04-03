"""Internal storage and lookup helpers for beta lab domain services."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.db import get_child_lineages, get_parent_lineages


class _BetaLabStoreMixin:
    def _resolve_or_create_plate(
        self,
        *,
        plate_euid: str | None,
        plate_template_code: str,
        plate_name: str | None,
    ):
        if plate_euid:
            plate = self._require_instance(plate_euid)
            if plate.category != "container":
                raise ValueError(f"EUID is not a container plate: {plate_euid}")
            return plate

        template = self._require_template(plate_template_code)
        created = self.bobj.create_instances(template.euid)
        plate = created[0][0]
        props = self._props(plate)
        resolved_name = plate_name or props.get("name") or plate.name
        if resolved_name:
            plate.name = str(resolved_name)
            props["name"] = str(resolved_name)
            self._write_props(plate, props)
        return plate

    def _resolve_or_create_container(
        self,
        *,
        container_euid: str | None,
        container_template_code: str,
        specimen_name: str,
    ):
        if container_euid:
            container = self._require_instance(container_euid)
            if container.category != "container":
                raise ValueError(f"EUID is not a container: {container_euid}")
            return container

        container = self.bobj.create_instance_by_code(
            container_template_code,
            {"json_addl": {"properties": {"name": f"{specimen_name} container"}}},
        )
        if container is None:
            raise ValueError("Failed to create container for specimen")
        return container

    def _ensure_container_link(self, container_euid: str, specimen_euid: str) -> None:
        container = self._require_instance(container_euid)
        specimen = self._require_instance(specimen_euid)
        for lineage in get_parent_lineages(container):
            if lineage.is_deleted:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            if child.uid == specimen.uid and lineage.relationship_type == "contains":
                return
        self.bobj.create_generic_instance_lineage_by_euids(
            container_euid,
            specimen_euid,
            relationship_type="contains",
        )

    def _require_plate_well(self, plate, well_name: str):
        expected = str(well_name or "").strip().upper()
        for lineage in get_parent_lineages(plate):
            if lineage.is_deleted:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted or child.category != "container":
                continue
            address = (
                child.json_addl.get("cont_address")
                if isinstance(child.json_addl, dict)
                else {}
            )
            candidate = str((address or {}).get("name") or "").strip().upper()
            if not candidate:
                candidate = str(self._props(child).get("name") or "").strip().upper()
            if candidate == expected:
                return child
        raise ValueError(f"Well not found on plate {plate.euid}: {well_name}")

    def _find_operation_record(self, *, beta_kind: str, idempotency_key: str):
        return self._find_data_record_by_property(
            beta_kind=beta_kind,
            property_key="idempotency_key",
            expected=idempotency_key,
        )

    def _find_data_record(self, *, beta_kind: str, idempotency_key: str):
        return self._find_data_record_by_property(
            beta_kind=beta_kind,
            property_key="idempotency_key",
            expected=idempotency_key,
        )

    def _find_library_prep_output_record(self, *, idempotency_key: str):
        return self._find_instance_by_template_property(
            category="data",
            type_name="wetlab",
            subtype="library_prep_output",
            property_key="idempotency_key",
            expected=idempotency_key,
        )

    def _find_instance_by_template_property(
        self,
        *,
        category: str,
        type_name: str,
        subtype: str,
        property_key: str,
        expected: str,
    ):
        return (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == category,
                self.bdb.Base.classes.generic_instance.type == type_name,
                self.bdb.Base.classes.generic_instance.subtype == subtype,
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    property_key,
                )
                == str(expected).strip(),
            )
            .first()
        )

    def _find_content_record(self, *, beta_kind: str, idempotency_key: str):
        return (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "content",
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "beta_kind",
                )
                == beta_kind,
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "idempotency_key",
                )
                == str(idempotency_key).strip(),
            )
            .first()
        )

    def _find_container_record(self, *, beta_kind: str, idempotency_key: str):
        return (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "container",
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "beta_kind",
                )
                == beta_kind,
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "idempotency_key",
                )
                == str(idempotency_key).strip(),
            )
            .first()
        )

    def _find_data_record_by_property(
        self,
        *,
        beta_kind: str,
        property_key: str,
        expected: str,
    ):
        return (
            self.bdb.session.query(self.bdb.Base.classes.generic_instance)
            .filter(
                self.bdb.Base.classes.generic_instance.category == "generic",
                self.bdb.Base.classes.generic_instance.type == "generic",
                self.bdb.Base.classes.generic_instance.subtype == "generic",
                self.bdb.Base.classes.generic_instance.is_deleted.is_(False),
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    "beta_kind",
                )
                == beta_kind,
                func.jsonb_extract_path_text(
                    self.bdb.Base.classes.generic_instance.json_addl["properties"],
                    property_key,
                )
                == str(expected).strip(),
            )
            .first()
        )

    def _create_data_record(
        self,
        *,
        beta_kind: str,
        name: str,
        properties: dict[str, Any],
    ):
        payload = {"beta_kind": beta_kind, **(properties or {})}
        record = self.bobj.create_instance_by_code(
            self.GENERIC_DATA_TEMPLATE_CODE,
            {"json_addl": {"properties": payload}},
        )
        props = self._props(record)
        record.name = name
        props["name"] = name
        self._write_props(record, props)
        return record

    def _linked_container_euid(self, instance) -> str | None:
        for lineage in get_child_lineages(instance):
            if lineage.is_deleted:
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted or parent.category != "container":
                continue
            return parent.euid
        return None

    def _record_action(
        self,
        *,
        target_instance,
        action_key: str,
        captured_data: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        self.action_recorder.record(
            target_instance=target_instance,
            action_key=action_key,
            captured_data=captured_data,
            result=result,
            executed_by=self.bdb.app_username,
        )

    def _first_parent(self, instance, relationship_type: str):
        for lineage in get_child_lineages(instance):
            if lineage.is_deleted or lineage.relationship_type != relationship_type:
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted:
                continue
            return parent
        return None

    def _pool_euid_for_run(self, run) -> str | None:
        pool = self._first_parent(run, "beta_sequencing_run")
        return pool.euid if pool is not None else None

    def _well_name(self, well) -> str:
        if well is None:
            return ""
        address = well.json_addl.get("cont_address") if isinstance(well.json_addl, dict) else {}
        name = str((address or {}).get("name") or "").strip()
        if name:
            return name
        return str(self._props(well).get("name") or "").strip()

    def _member_euids_for_pool(self, pool) -> list[str]:
        member_euids: list[str] = []
        for lineage in get_child_lineages(pool):
            if lineage.is_deleted or lineage.relationship_type != "beta_pool_member":
                continue
            parent = lineage.parent_instance
            if parent is None or parent.is_deleted:
                continue
            member_euids.append(parent.euid)
        return sorted(member_euids)

    def _count_children(self, instance, relationship_type: str) -> int:
        count = 0
        for lineage in get_parent_lineages(instance):
            if lineage.is_deleted or lineage.relationship_type != relationship_type:
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            count += 1
        return count

    def _require_template(self, template_code: str):
        clean = str(template_code or "").strip().strip("/")
        parts = clean.split("/")
        if len(parts) != 4:
            raise ValueError(
                f"Template code must be category/type/subtype/version: {template_code}"
            )
        templates = self.bobj.query_template_by_component_v2(*parts)
        if not templates:
            raise ValueError(f"Template not found: {template_code}")
        return templates[0]

    def _require_instance(self, euid: str):
        instance = self._safe_get_by_euid(euid)
        if instance is None or instance.is_deleted:
            raise ValueError(f"Bloom object not found: {euid}")
        return instance

    def _safe_get_by_euid(self, euid: str):
        try:
            return self.bobj.get_by_euid(euid)
        except Exception as exc:
            msg = str(exc).lower()
            if "not found" in msg or "no template found" in msg:
                return None
            raise

    def _props(self, instance) -> dict[str, Any]:
        payload = instance.json_addl or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        props = payload.get("properties")
        if not isinstance(props, dict):
            props = {}
            payload["properties"] = props
            instance.json_addl = payload
        return props

    def _write_props(self, instance, props: dict[str, Any]) -> None:
        payload = instance.json_addl or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["properties"] = props
        instance.json_addl = payload
        flag_modified(instance, "json_addl")

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat()
