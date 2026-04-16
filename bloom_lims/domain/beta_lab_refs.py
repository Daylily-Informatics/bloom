"""Internal Atlas reference helpers for beta lab domain services."""

from __future__ import annotations

from typing import Any

from bloom_lims.db import get_child_lineages, get_parent_lineages
from bloom_lims.template_identity import instance_semantic_category


class _BetaLabReferenceMixin:
    def _resolve_fulfillment_item_context(
        self,
        instance,
        *,
        target_fulfillment_item_euid: str | None = None,
    ) -> dict[str, str]:
        matches = {
            ref["atlas_test_fulfillment_item_euid"]: ref
            for ref in self._reachable_fulfillment_item_refs(instance)
        }
        target = str(target_fulfillment_item_euid or "").strip()
        if target:
            if target in matches:
                return matches[target]
            raise ValueError(
                "No Atlas test fulfillment item could be resolved from "
                f"Bloom lineage for {instance.euid}: {target}"
            )
        if len(matches) == 1:
            return next(iter(matches.values()))
        if len(matches) > 1:
            raise ValueError(
                "Multiple Atlas test fulfillment items are reachable from "
                f"{instance.euid}; choose one explicitly before sequencing"
            )
        raise ValueError(
            "No Atlas test fulfillment item could be resolved from "
            f"Bloom lineage for {instance.euid}"
        )

    def _reachable_fulfillment_item_refs(self, instance) -> list[dict[str, str]]:
        visited: set[int] = set()
        to_visit = [instance]
        refs: dict[str, dict[str, str]] = {}
        while to_visit:
            current = to_visit.pop(0)
            current_uid = getattr(current, "uid", None)
            if current_uid in visited:
                continue
            visited.add(current_uid)
            for ref in self._fulfillment_item_refs_for_instance(current):
                refs[ref["atlas_test_fulfillment_item_euid"]] = ref
            for lineage in get_child_lineages(current):
                if lineage.is_deleted:
                    continue
                parent = lineage.parent_instance
                if parent is None or parent.is_deleted:
                    continue
                to_visit.append(parent)
        return list(refs.values())

    def _fulfillment_item_refs_for_instance(self, instance) -> list[dict[str, str]]:
        refs: dict[str, dict[str, str]] = {}
        for payload in self._atlas_reference_payloads_for_instance(instance):
            ref_type = str(payload.get("reference_type") or "").strip()
            if ref_type != self.PROCESS_ITEM_REFERENCE_TYPE:
                continue
            fulfillment_item_euid = str(
                payload.get("atlas_test_fulfillment_item_euid") or ""
            ).strip()
            atlas_test_euid = str(payload.get("atlas_test_euid") or "").strip()
            atlas_tenant_id = str(payload.get("atlas_tenant_id") or "").strip()
            atlas_trf_euid = str(payload.get("atlas_trf_euid") or "").strip()
            if not (
                fulfillment_item_euid
                and atlas_test_euid
                and atlas_tenant_id
                and atlas_trf_euid
            ):
                continue
            refs[fulfillment_item_euid] = {
                "atlas_tenant_id": atlas_tenant_id,
                "atlas_trf_euid": atlas_trf_euid,
                "atlas_test_euid": atlas_test_euid,
                "atlas_test_fulfillment_item_euid": fulfillment_item_euid,
            }
        return list(refs.values())

    def _atlas_reference_payloads_for_instance(self, instance) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for lineage in get_parent_lineages(instance):
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.EXTERNAL_REFERENCE_RELATIONSHIP
            ):
                continue
            external_ref = lineage.child_instance
            if external_ref is None or external_ref.is_deleted:
                continue
            if (
                instance_semantic_category(external_ref) != "generic"
                or external_ref.type != "generic"
                or external_ref.subtype != "external_object_link"
            ):
                continue
            payload = self._props(external_ref)
            if str(payload.get("provider") or "").strip() != "atlas":
                continue
            payloads.append(payload)
        return payloads

    def _patient_ref_for_instance(self, instance) -> dict[str, str] | None:
        for payload in self._atlas_reference_payloads_for_instance(instance):
            ref_type = str(payload.get("reference_type") or "").strip()
            if ref_type != self.PATIENT_REFERENCE_TYPE:
                continue
            atlas_patient_euid = str(payload.get("atlas_patient_euid") or "").strip()
            if not atlas_patient_euid:
                atlas_patient_euid = str(payload.get("reference_value") or "").strip()
            atlas_tenant_id = str(payload.get("atlas_tenant_id") or "").strip()
            if not (atlas_patient_euid and atlas_tenant_id):
                continue
            return {
                "atlas_tenant_id": atlas_tenant_id,
                "atlas_patient_euid": atlas_patient_euid,
            }
        return None

    def _collection_event_ref_for_instance(self, instance) -> dict[str, Any] | None:
        for payload in self._atlas_reference_payloads_for_instance(instance):
            ref_type = str(payload.get("reference_type") or "").strip()
            if ref_type != self.COLLECTION_EVENT_REFERENCE_TYPE:
                continue
            collection_event_euid = str(
                payload.get("atlas_collection_event_euid")
                or payload.get("reference_value")
                or ""
            ).strip()
            atlas_tenant_id = str(payload.get("atlas_tenant_id") or "").strip()
            if not (collection_event_euid and atlas_tenant_id):
                continue
            snapshot = payload.get("collection_event_snapshot")
            return {
                "atlas_tenant_id": atlas_tenant_id,
                "atlas_collection_event_euid": collection_event_euid,
                "collection_event_snapshot": (
                    snapshot if isinstance(snapshot, dict) else {}
                ),
            }
        return None

    @staticmethod
    def _has_collection_event_context(atlas_context: dict[str, Any]) -> bool:
        collection_event_euid = str(
            atlas_context.get("atlas_collection_event_euid") or ""
        ).strip()
        if collection_event_euid:
            return True
        snapshot = atlas_context.get("collection_event_snapshot")
        return bool(
            isinstance(snapshot, dict)
            and str(snapshot.get("collection_event_euid") or "").strip()
        )

    def _replace_fulfillment_item_references(
        self, instance, *, atlas_context: dict[str, Any]
    ) -> None:
        self._delete_reference_type(
            instance,
            reference_type=self.PROCESS_ITEM_REFERENCE_TYPE,
        )

        atlas_tenant_id = str(atlas_context.get("atlas_tenant_id") or "").strip()
        atlas_trf_euid = str(atlas_context.get("atlas_trf_euid") or "").strip()
        fulfillment_items = list(atlas_context.get("fulfillment_items") or [])

        for fulfillment_item in fulfillment_items:
            atlas_test_euid = str(
                fulfillment_item.get("atlas_test_euid") or ""
            ).strip()
            atlas_test_fulfillment_item_euid = str(
                fulfillment_item.get("atlas_test_fulfillment_item_euid") or ""
            ).strip()
            if not (
                atlas_tenant_id
                and atlas_trf_euid
                and atlas_test_euid
                and atlas_test_fulfillment_item_euid
            ):
                continue
            ref_obj = self.bobj.create_instance_by_code(
                self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
                {
                    "json_addl": {
                        "properties": {
                            "provider": "atlas",
                            "reference_type": self.PROCESS_ITEM_REFERENCE_TYPE,
                            "reference_value": atlas_test_fulfillment_item_euid,
                            "foreign_reference": atlas_test_fulfillment_item_euid,
                            "atlas_tenant_id": atlas_tenant_id,
                            "atlas_trf_euid": atlas_trf_euid,
                            "atlas_test_euid": atlas_test_euid,
                            "atlas_test_fulfillment_item_euid": atlas_test_fulfillment_item_euid,
                            "validation": {},
                        }
                    }
                },
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                instance.euid,
                ref_obj.euid,
                relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
            )

    def _replace_container_entity_references(
        self,
        instance,
        *,
        atlas_context: dict[str, Any],
    ) -> None:
        atlas_tenant_id = str(atlas_context.get("atlas_tenant_id") or "").strip()
        atlas_trf_euid = str(atlas_context.get("atlas_trf_euid") or "").strip()
        atlas_test_euid = str(atlas_context.get("atlas_test_euid") or "").strip()
        atlas_test_euids: list[str] = []
        seen_tests: set[str] = set()
        if atlas_test_euid:
            seen_tests.add(atlas_test_euid)
            atlas_test_euids.append(atlas_test_euid)
        for value in list(atlas_context.get("atlas_test_euids") or []):
            clean_value = str(value or "").strip()
            if not clean_value or clean_value in seen_tests:
                continue
            seen_tests.add(clean_value)
            atlas_test_euids.append(clean_value)
        fulfillment_items = list(atlas_context.get("fulfillment_items") or [])
        for fulfillment_item in fulfillment_items:
            candidate = str(fulfillment_item.get("atlas_test_euid") or "").strip()
            if not candidate or candidate in seen_tests:
                continue
            seen_tests.add(candidate)
            atlas_test_euids.append(candidate)
        if not atlas_test_euid and atlas_test_euids:
            atlas_test_euid = atlas_test_euids[0]
        reference_fields = (
            (self.TRF_REFERENCE_TYPE, "atlas_trf_euid"),
            (self.TESTKIT_REFERENCE_TYPE, "atlas_testkit_euid"),
            (self.SHIPMENT_REFERENCE_TYPE, "atlas_shipment_euid"),
            (self.ORGANIZATION_SITE_REFERENCE_TYPE, "atlas_organization_site_euid"),
        )
        self._delete_reference_type(instance, reference_type=self.TEST_REFERENCE_TYPE)
        if atlas_tenant_id:
            for reference_value in atlas_test_euids:
                properties = {
                    "provider": "atlas",
                    "reference_type": self.TEST_REFERENCE_TYPE,
                    "reference_value": reference_value,
                    "foreign_reference": reference_value,
                    "atlas_tenant_id": atlas_tenant_id,
                    "atlas_test_euid": reference_value,
                    "validation": {},
                }
                if atlas_trf_euid:
                    properties["atlas_trf_euid"] = atlas_trf_euid
                ref_obj = self.bobj.create_instance_by_code(
                    self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
                    {"json_addl": {"properties": properties}},
                )
                self.bobj.create_generic_instance_lineage_by_euids(
                    instance.euid,
                    ref_obj.euid,
                    relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
                )
        for reference_type, field_name in reference_fields:
            self._delete_reference_type(instance, reference_type=reference_type)
            if not atlas_tenant_id:
                continue
            reference_value = str(atlas_context.get(field_name) or "").strip()
            if not reference_value:
                continue
            properties = {
                "provider": "atlas",
                "reference_type": reference_type,
                "reference_value": reference_value,
                "foreign_reference": reference_value,
                "atlas_tenant_id": atlas_tenant_id,
                "validation": {},
            }
            if atlas_trf_euid:
                properties["atlas_trf_euid"] = atlas_trf_euid
            properties[field_name] = reference_value
            ref_obj = self.bobj.create_instance_by_code(
                self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
                {"json_addl": {"properties": properties}},
            )
            self.bobj.create_generic_instance_lineage_by_euids(
                instance.euid,
                ref_obj.euid,
                relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
            )

    def _replace_collection_event_reference(
        self, instance, *, atlas_context: dict[str, Any]
    ) -> None:
        self._delete_reference_type(
            instance,
            reference_type=self.COLLECTION_EVENT_REFERENCE_TYPE,
        )
        atlas_tenant_id = str(atlas_context.get("atlas_tenant_id") or "").strip()
        collection_event_euid = str(
            atlas_context.get("atlas_collection_event_euid") or ""
        ).strip()
        if not collection_event_euid:
            snapshot = atlas_context.get("collection_event_snapshot")
            if isinstance(snapshot, dict):
                collection_event_euid = str(
                    snapshot.get("collection_event_euid") or ""
                ).strip()
        if not (atlas_tenant_id and collection_event_euid):
            return
        snapshot_payload = atlas_context.get("collection_event_snapshot")
        if not isinstance(snapshot_payload, dict):
            snapshot_payload = {}
        ref_obj = self.bobj.create_instance_by_code(
            self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
            {
                "json_addl": {
                    "properties": {
                        "provider": "atlas",
                        "reference_type": self.COLLECTION_EVENT_REFERENCE_TYPE,
                        "reference_value": collection_event_euid,
                        "foreign_reference": collection_event_euid,
                        "atlas_tenant_id": atlas_tenant_id,
                        "atlas_collection_event_euid": collection_event_euid,
                        "atlas_trf_euid": str(
                            atlas_context.get("atlas_trf_euid") or ""
                        ).strip(),
                        "collection_event_snapshot": snapshot_payload,
                        "validation": {},
                    }
                }
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            instance.euid,
            ref_obj.euid,
            relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
        )

    def _replace_patient_reference(self, instance, *, atlas_context: dict[str, Any]) -> None:
        self._delete_reference_type(
            instance,
            reference_type=self.PATIENT_REFERENCE_TYPE,
        )
        atlas_tenant_id = str(atlas_context.get("atlas_tenant_id") or "").strip()
        atlas_patient_euid = str(atlas_context.get("atlas_patient_euid") or "").strip()
        atlas_trf_euid = str(atlas_context.get("atlas_trf_euid") or "").strip()
        if not (atlas_tenant_id and atlas_patient_euid):
            return
        ref_obj = self.bobj.create_instance_by_code(
            self.EXTERNAL_REFERENCE_TEMPLATE_CODE,
            {
                "json_addl": {
                    "properties": {
                        "provider": "atlas",
                        "reference_type": self.PATIENT_REFERENCE_TYPE,
                        "reference_value": atlas_patient_euid,
                        "foreign_reference": atlas_patient_euid,
                        "atlas_tenant_id": atlas_tenant_id,
                        "atlas_patient_euid": atlas_patient_euid,
                        "atlas_trf_euid": atlas_trf_euid,
                        "validation": {},
                    }
                }
            },
        )
        self.bobj.create_generic_instance_lineage_by_euids(
            instance.euid,
            ref_obj.euid,
            relationship_type=self.EXTERNAL_REFERENCE_RELATIONSHIP,
        )

    def _delete_reference_type(self, instance, *, reference_type: str) -> None:
        existing_refs = []
        for lineage in get_parent_lineages(instance):
            if (
                lineage.is_deleted
                or lineage.relationship_type != self.EXTERNAL_REFERENCE_RELATIONSHIP
            ):
                continue
            child = lineage.child_instance
            if child is None:
                continue
            existing_refs.append((lineage, child))

        for lineage, child in existing_refs:
            payload = self._props(child)
            if (
                str(payload.get("reference_type") or "").strip()
                != str(reference_type).strip()
            ):
                continue
            lineage.is_deleted = True
            child.is_deleted = True

    def _atlas_context_for_instance(self, instance) -> dict[str, Any]:
        fulfillment_items = self._reachable_fulfillment_item_refs(instance)
        patient_ref = self._patient_ref_for_instance(instance)
        collection_event_ref = self._collection_event_ref_for_instance(instance)
        atlas_trf_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.TRF_REFERENCE_TYPE,
            value_field="atlas_trf_euid",
        )
        atlas_test_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.TEST_REFERENCE_TYPE,
            value_field="atlas_test_euid",
        )
        direct_test_euids = self._reachable_reference_values(
            instance,
            reference_type=self.TEST_REFERENCE_TYPE,
            value_field="atlas_test_euid",
        )
        atlas_testkit_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.TESTKIT_REFERENCE_TYPE,
            value_field="atlas_testkit_euid",
        )
        atlas_shipment_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.SHIPMENT_REFERENCE_TYPE,
            value_field="atlas_shipment_euid",
        )
        atlas_organization_site_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.ORGANIZATION_SITE_REFERENCE_TYPE,
            value_field="atlas_organization_site_euid",
        )
        atlas_test_euids: list[str] = []
        seen_test_euids: set[str] = set()
        for direct_test_euid in direct_test_euids:
            if direct_test_euid in seen_test_euids:
                continue
            seen_test_euids.add(direct_test_euid)
            atlas_test_euids.append(direct_test_euid)
        if atlas_test_euid and atlas_test_euid not in seen_test_euids:
            seen_test_euids.add(atlas_test_euid)
            atlas_test_euids.append(atlas_test_euid)
        for item in sorted(
            fulfillment_items,
            key=lambda item: item["atlas_test_fulfillment_item_euid"],
        ):
            candidate = str(item["atlas_test_euid"] or "").strip()
            if not candidate or candidate in seen_test_euids:
                continue
            seen_test_euids.add(candidate)
            atlas_test_euids.append(candidate)
        fallback_tenant_id = self._first_reachable_reference_value(
            instance,
            reference_type=self.TRF_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or self._first_reachable_reference_value(
            instance,
            reference_type=self.TEST_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or self._first_reachable_reference_value(
            instance,
            reference_type=self.TESTKIT_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or self._first_reachable_reference_value(
            instance,
            reference_type=self.SHIPMENT_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or self._first_reachable_reference_value(
            instance,
            reference_type=self.ORGANIZATION_SITE_REFERENCE_TYPE,
            value_field="atlas_tenant_id",
        ) or (
            patient_ref["atlas_tenant_id"] if patient_ref is not None else ""
        ) or (
            collection_event_ref["atlas_tenant_id"]
            if collection_event_ref is not None
            else ""
        )
        if not fulfillment_items:
            return {
                "atlas_tenant_id": fallback_tenant_id,
                "atlas_trf_euid": atlas_trf_euid,
                "atlas_test_euid": atlas_test_euid,
                "atlas_test_euids": atlas_test_euids,
                "atlas_testkit_euid": atlas_testkit_euid,
                "atlas_shipment_euid": atlas_shipment_euid,
                "atlas_organization_site_euid": atlas_organization_site_euid,
                "atlas_collection_event_euid": (
                    collection_event_ref["atlas_collection_event_euid"]
                    if collection_event_ref is not None
                    else ""
                ),
                "collection_event_snapshot": (
                    collection_event_ref["collection_event_snapshot"]
                    if collection_event_ref is not None
                    else {}
                ),
                "atlas_patient_euid": (
                    patient_ref["atlas_patient_euid"] if patient_ref is not None else ""
                ),
                "fulfillment_items": [],
            }
        first = fulfillment_items[0]
        return {
            "atlas_tenant_id": first["atlas_tenant_id"],
            "atlas_trf_euid": first["atlas_trf_euid"] or atlas_trf_euid,
            "atlas_test_euid": atlas_test_euid or first["atlas_test_euid"],
            "atlas_test_euids": atlas_test_euids,
            "atlas_testkit_euid": atlas_testkit_euid,
            "atlas_shipment_euid": atlas_shipment_euid,
            "atlas_organization_site_euid": atlas_organization_site_euid,
            "atlas_collection_event_euid": (
                collection_event_ref["atlas_collection_event_euid"]
                if collection_event_ref is not None
                else ""
            ),
            "collection_event_snapshot": (
                collection_event_ref["collection_event_snapshot"]
                if collection_event_ref is not None
                else {}
            ),
            "atlas_patient_euid": (
                patient_ref["atlas_patient_euid"] if patient_ref is not None else ""
            ),
            "fulfillment_items": [
                {
                    "atlas_test_euid": item["atlas_test_euid"],
                    "atlas_test_fulfillment_item_euid": item[
                        "atlas_test_fulfillment_item_euid"
                    ],
                }
                for item in sorted(
                    fulfillment_items,
                    key=lambda item: item["atlas_test_fulfillment_item_euid"],
                )
            ],
        }

    def _first_reachable_reference_value(
        self,
        instance,
        *,
        reference_type: str,
        value_field: str,
    ) -> str:
        visited: set[int] = set()
        to_visit = [instance]
        while to_visit:
            current = to_visit.pop(0)
            current_uid = getattr(current, "uid", None)
            if current_uid in visited:
                continue
            visited.add(current_uid)
            for payload in self._atlas_reference_payloads_for_instance(current):
                current_ref_type = str(payload.get("reference_type") or "").strip()
                if current_ref_type != str(reference_type).strip():
                    continue
                value = str(payload.get(value_field) or "").strip()
                if not value:
                    value = str(payload.get("reference_value") or "").strip()
                if value:
                    return value
            for lineage in get_child_lineages(current):
                if lineage.is_deleted:
                    continue
                parent = lineage.parent_instance
                if parent is None or parent.is_deleted:
                    continue
                to_visit.append(parent)
        return ""

    def _reachable_reference_values(
        self,
        instance,
        *,
        reference_type: str,
        value_field: str,
    ) -> list[str]:
        visited: set[int] = set()
        to_visit = [instance]
        values: list[str] = []
        seen: set[str] = set()
        while to_visit:
            current = to_visit.pop(0)
            current_uid = getattr(current, "uid", None)
            if current_uid in visited:
                continue
            visited.add(current_uid)
            for payload in self._atlas_reference_payloads_for_instance(current):
                current_ref_type = str(payload.get("reference_type") or "").strip()
                if current_ref_type != str(reference_type).strip():
                    continue
                value = str(payload.get(value_field) or "").strip()
                if not value:
                    value = str(payload.get("reference_value") or "").strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                values.append(value)
            for lineage in get_child_lineages(current):
                if lineage.is_deleted:
                    continue
                parent = lineage.parent_instance
                if parent is None or parent.is_deleted:
                    continue
                to_visit.append(parent)
        return values
