"""Internal Atlas reference helpers for beta lab domain services."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from bloom_lims.atlas_references import (
    list_reference_payloads,
    replace_reference_types,
)
from bloom_lims.domain.v0_graph import attach_bloom_v0_edge, object_evidence
from bloom_lims.tapdb_adapter import get_child_lineages


class _BetaLabReferenceMixin:
    def _atlas_tenant_contexts(self, instance) -> set[str]:
        """Explicit registration scope and typed owner references must agree.

        This scalar scopes independent registrations. It identifies no Atlas
        business object and never creates or substitutes an object relationship.
        """
        values = set()
        pending, visited = [instance], set()
        while pending:
            current = pending.pop()
            if current.uid in visited:
                continue
            visited.add(current.uid)
            direct = self._props(current).get("atlas_registration_tenant_id")
            if direct:
                values.add(str(UUID(str(direct))))
            for reference in self._atlas_reference_payloads_for_instance(current):
                tenant = reference.get("atlas_tenant_id")
                if tenant:
                    values.add(str(UUID(str(tenant))))
            for lineage in get_child_lineages(current):
                if lineage.is_deleted or lineage.relationship_type not in self._FULFILLMENT_CONTEXT_PARENT_RELATIONSHIPS:
                    continue
                parent = lineage.parent_instance
                if parent is not None and not parent.is_deleted:
                    pending.append(parent)
        if len(values) > 1:
            raise ValueError("Bloom Atlas registration and reference tenant contexts disagree")
        return values

    def _bind_atlas_registration_tenant(self, instance, atlas_context: dict[str, Any]) -> None:
        tenant = str(UUID(str(atlas_context.get("atlas_tenant_id") or "")))
        current = self._atlas_tenant_contexts(instance)
        if current and current != {tenant}:
            raise ValueError("Bloom Atlas registration and supplied tenant contexts disagree")
        self._write_props(instance, {**self._props(instance), "atlas_registration_tenant_id": tenant})

    _FULFILLMENT_CONTEXT_PARENT_RELATIONSHIPS = frozenset(
        {
            "contains",
            "beta_assignment_source",
            "beta_assignment_library_material",
            "beta_extraction_output",
            "beta_extraction_run_input",
            "beta_extraction_run_output",
            "beta_library_material_output",
            "beta_library_prep_output",
            "beta_pool_member",
            "beta_sequenced_library_assignment",
            "beta_sequencing_run",
            "HOLDS_MATERIAL",
            "RUN_CONSUMED",
            "RUN_PRODUCED",
            "DERIVED_FROM",
        }
    )

    def _attach_v0_edge_to_lineage(
        self,
        lineage,
        *,
        edge_type: str,
        source_euid: str,
        target_euid: str,
        source_role: str,
        target_role: str,
        evidence_refs: list[dict[str, Any]],
        correlation_id: str,
        causation_id: str,
        source_system: str = "bloom",
        target_system: str = "bloom",
    ):
        return attach_bloom_v0_edge(
            lineage,
            edge_type=edge_type,
            source_euid=source_euid,
            target_euid=target_euid,
            source_role=source_role,
            target_role=target_role,
            source_system=source_system,
            target_system=target_system,
            evidence_refs=evidence_refs,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

    def _attach_bloom_v0_lineage(
        self,
        parent_euid: str,
        child_euid: str,
        *,
        relationship_type: str,
        edge_type: str,
        source_euid: str,
        target_euid: str,
        source_role: str,
        target_role: str,
        source_system: str = "bloom",
        target_system: str = "bloom",
        extra_evidence_refs: list[dict[str, Any]] | None = None,
    ):
        lineage = self.bobj.create_generic_instance_lineage_by_euids(
            parent_euid,
            child_euid,
            relationship_type=relationship_type,
        )
        evidence_refs = [
            object_evidence(parent_euid, role="tapdb_lineage_parent"),
            object_evidence(child_euid, role="tapdb_lineage_child"),
            *(extra_evidence_refs or []),
        ]
        return self._attach_v0_edge_to_lineage(
            lineage,
            edge_type=edge_type,
            source_euid=source_euid,
            target_euid=target_euid,
            source_role=source_role,
            target_role=target_role,
            source_system=source_system,
            target_system=target_system,
            evidence_refs=evidence_refs,
            correlation_id=f"{relationship_type}:{parent_euid}:{child_euid}",
            causation_id=f"bloom:{relationship_type}:{parent_euid}:{child_euid}",
        )

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
                if (
                    lineage.relationship_type
                    not in self._FULFILLMENT_CONTEXT_PARENT_RELATIONSHIPS
                ):
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
                payload.get("atlas_test_fulfillment_item_euid")
                or payload.get("atlas_fulfillment_slot_euid")
                or ""
            ).strip()
            atlas_test_euid = str(
                payload.get("atlas_test_euid")
                or payload.get("atlas_order_test_euid")
                or ""
            ).strip()
            atlas_tenant_id = str(payload.get("atlas_tenant_id") or "").strip()
            atlas_trf_euid = str(
                payload.get("atlas_trf_euid") or payload.get("atlas_order_euid") or ""
            ).strip()
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
                "atlas_order_euid": str(
                    payload.get("atlas_order_euid") or atlas_trf_euid
                ).strip(),
                "atlas_order_test_euid": str(
                    payload.get("atlas_order_test_euid") or atlas_test_euid
                ).strip(),
                "atlas_fulfillment_slot_euid": str(
                    payload.get("atlas_fulfillment_slot_euid") or fulfillment_item_euid
                ).strip(),
            }
        return list(refs.values())

    def _atlas_reference_payloads_for_instance(self, instance) -> list[dict[str, Any]]:
        return list_reference_payloads(self.bdb.session, instance)

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
        atlas_tenant_id = str(atlas_context.get("atlas_tenant_id") or "").strip()
        atlas_trf_euid = str(atlas_context.get("atlas_trf_euid") or "").strip()
        atlas_order_euid = str(
            atlas_context.get("atlas_order_euid")
            or atlas_context.get("order_euid")
            or ""
        ).strip()
        fulfillment_items = list(atlas_context.get("fulfillment_items") or [])
        for slot in list(atlas_context.get("fulfillment_slots") or []):
            slot_euid = str(slot.get("atlas_fulfillment_slot_euid") or "").strip()
            test_euid = str(slot.get("atlas_order_test_euid") or "").strip()
            if slot_euid and test_euid:
                fulfillment_items.append(
                    {
                        "atlas_test_euid": test_euid,
                        "atlas_order_test_euid": test_euid,
                        "atlas_test_fulfillment_item_euid": slot_euid,
                        "atlas_fulfillment_slot_euid": slot_euid,
                    }
                )
        direct_item = str(
            atlas_context.get("atlas_test_fulfillment_item_euid") or ""
        ).strip()
        direct_test = str(atlas_context.get("atlas_test_euid") or "").strip()
        if direct_item and direct_test and not fulfillment_items:
            fulfillment_items.append(
                {
                    "atlas_test_euid": direct_test,
                    "atlas_test_fulfillment_item_euid": direct_item,
                }
            )
        desired: list[dict[str, Any]] = []
        for item in fulfillment_items:
            atlas_test_euid = str(item.get("atlas_test_euid") or "").strip()
            order_test_euid = str(
                item.get("atlas_order_test_euid") or atlas_test_euid
            ).strip()
            fulfillment_euid = str(
                item.get("atlas_test_fulfillment_item_euid")
                or item.get("atlas_fulfillment_slot_euid")
                or ""
            ).strip()
            slot_euid = str(
                item.get("atlas_fulfillment_slot_euid") or fulfillment_euid
            ).strip()
            if not (
                atlas_tenant_id
                and (atlas_trf_euid or atlas_order_euid)
                and (atlas_test_euid or order_test_euid)
                and fulfillment_euid
            ):
                continue
            desired.append(
                {
                    "provider": "atlas",
                    "reference_type": self.PROCESS_ITEM_REFERENCE_TYPE,
                    "reference_value": fulfillment_euid,
                    "foreign_reference": fulfillment_euid,
                    "atlas_tenant_id": atlas_tenant_id,
                    "atlas_trf_euid": atlas_trf_euid,
                    "atlas_order_euid": atlas_order_euid,
                    "atlas_test_euid": atlas_test_euid,
                    "atlas_order_test_euid": order_test_euid,
                    "atlas_test_fulfillment_item_euid": fulfillment_euid,
                    "atlas_fulfillment_slot_euid": slot_euid,
                }
            )
        replace_reference_types(
            self.bdb.session,
            instance,
            desired,
            managed_reference_types=[self.PROCESS_ITEM_REFERENCE_TYPE],
        )

    def _replace_container_entity_references(
        self, instance, *, atlas_context: dict[str, Any]
    ) -> None:
        tenant = str(atlas_context.get("atlas_tenant_id") or "").strip()
        order_euid = str(
            atlas_context.get("atlas_order_euid")
            or atlas_context.get("order_euid")
            or ""
        ).strip()
        trf_euid = str(atlas_context.get("atlas_trf_euid") or "").strip()

        def _unique(primary: str, values: Any) -> list[str]:
            result: list[str] = []
            for value in [primary, *list(values or [])]:
                clean = str(value or "").strip()
                if clean and clean not in result:
                    result.append(clean)
            return result

        order_tests = _unique(
            str(
                atlas_context.get("atlas_order_test_euid")
                or atlas_context.get("order_test_euid")
                or ""
            ).strip(),
            atlas_context.get("atlas_order_test_euids"),
        )
        tests = _unique(
            str(atlas_context.get("atlas_test_euid") or "").strip(),
            atlas_context.get("atlas_test_euids"),
        )
        for item in list(atlas_context.get("fulfillment_items") or []):
            order_tests = _unique(
                "",
                [
                    *order_tests,
                    item.get("atlas_order_test_euid") or item.get("order_test_euid"),
                ],
            )
            tests = _unique("", [*tests, item.get("atlas_test_euid")])

        desired: list[dict[str, Any]] = []

        def _add(reference_type: str, value: str, **extra: str) -> None:
            if not (tenant and value):
                return
            desired.append(
                {
                    "provider": "atlas",
                    "reference_type": reference_type,
                    "reference_value": value,
                    "foreign_reference": value,
                    "atlas_tenant_id": tenant,
                    **{key: item for key, item in extra.items() if item},
                }
            )

        _add(
            "order_euid", order_euid, order_euid=order_euid, atlas_order_euid=order_euid
        )
        for value in order_tests:
            _add(
                "order_test_euid",
                value,
                order_test_euid=value,
                atlas_order_test_euid=value,
                order_euid=order_euid,
                atlas_order_euid=order_euid,
            )
        for value in tests:
            _add(
                self.TEST_REFERENCE_TYPE,
                value,
                atlas_test_euid=value,
                atlas_trf_euid=trf_euid,
            )
        for reference_type, field in (
            (self.TRF_REFERENCE_TYPE, "atlas_trf_euid"),
            (self.TESTKIT_REFERENCE_TYPE, "atlas_testkit_euid"),
            (self.SHIPMENT_REFERENCE_TYPE, "atlas_shipment_euid"),
            (self.ORGANIZATION_SITE_REFERENCE_TYPE, "atlas_organization_site_euid"),
        ):
            value = str(atlas_context.get(field) or "").strip()
            _add(reference_type, value, **{field: value, "atlas_trf_euid": trf_euid})
        replace_reference_types(
            self.bdb.session,
            instance,
            desired,
            managed_reference_types=[
                "order_euid",
                "order_test_euid",
                self.TEST_REFERENCE_TYPE,
                self.TRF_REFERENCE_TYPE,
                self.TESTKIT_REFERENCE_TYPE,
                self.SHIPMENT_REFERENCE_TYPE,
                self.ORGANIZATION_SITE_REFERENCE_TYPE,
            ],
        )

    def _replace_collection_event_reference(
        self, instance, *, atlas_context: dict[str, Any]
    ) -> None:
        tenant = str(atlas_context.get("atlas_tenant_id") or "").strip()
        event_euid = str(atlas_context.get("atlas_collection_event_euid") or "").strip()
        snapshot = atlas_context.get("collection_event_snapshot")
        if not event_euid and isinstance(snapshot, dict):
            event_euid = str(snapshot.get("collection_event_euid") or "").strip()
        desired = []
        if tenant and event_euid:
            desired.append(
                {
                    "provider": "atlas",
                    "reference_type": self.COLLECTION_EVENT_REFERENCE_TYPE,
                    "reference_value": event_euid,
                    "foreign_reference": event_euid,
                    "atlas_tenant_id": tenant,
                    "atlas_collection_event_euid": event_euid,
                    "atlas_trf_euid": str(
                        atlas_context.get("atlas_trf_euid") or ""
                    ).strip(),
                    "collection_event_snapshot": snapshot
                    if isinstance(snapshot, dict)
                    else {},
                }
            )
        replace_reference_types(
            self.bdb.session,
            instance,
            desired,
            managed_reference_types=[self.COLLECTION_EVENT_REFERENCE_TYPE],
        )

    def _replace_patient_reference(
        self, instance, *, atlas_context: dict[str, Any]
    ) -> None:
        tenant = str(atlas_context.get("atlas_tenant_id") or "").strip()
        patient_euid = str(atlas_context.get("atlas_patient_euid") or "").strip()
        desired = []
        if tenant and patient_euid:
            desired.append(
                {
                    "provider": "atlas",
                    "reference_type": self.PATIENT_REFERENCE_TYPE,
                    "reference_value": patient_euid,
                    "foreign_reference": patient_euid,
                    "atlas_tenant_id": tenant,
                    "atlas_patient_euid": patient_euid,
                    "atlas_trf_euid": str(
                        atlas_context.get("atlas_trf_euid") or ""
                    ).strip(),
                }
            )
        replace_reference_types(
            self.bdb.session,
            instance,
            desired,
            managed_reference_types=[self.PATIENT_REFERENCE_TYPE],
        )

    def _delete_reference_type(self, instance, *, reference_type: str) -> None:
        replace_reference_types(
            self.bdb.session,
            instance,
            [],
            managed_reference_types=[reference_type],
        )

    def _atlas_context_for_instance(self, instance) -> dict[str, Any]:
        fulfillment_items = self._reachable_fulfillment_item_refs(instance)
        patient_ref = self._patient_ref_for_instance(instance)
        collection_event_ref = self._collection_event_ref_for_instance(instance)
        atlas_trf_euid = self._first_reachable_reference_value(
            instance,
            reference_type=self.TRF_REFERENCE_TYPE,
            value_field="atlas_trf_euid",
        )
        atlas_order_euid = self._first_reachable_reference_value(
            instance,
            reference_type="order_euid",
            value_field="order_euid",
        )
        atlas_order_test_euid = self._first_reachable_reference_value(
            instance,
            reference_type="order_test_euid",
            value_field="order_test_euid",
        )
        direct_order_test_euids = self._reachable_reference_values(
            instance,
            reference_type="order_test_euid",
            value_field="order_test_euid",
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
        atlas_order_test_euids: list[str] = []
        seen_order_test_euids: set[str] = set()
        for direct_order_test_euid in direct_order_test_euids:
            if direct_order_test_euid in seen_order_test_euids:
                continue
            seen_order_test_euids.add(direct_order_test_euid)
            atlas_order_test_euids.append(direct_order_test_euid)
        if atlas_order_test_euid and atlas_order_test_euid not in seen_order_test_euids:
            seen_order_test_euids.add(atlas_order_test_euid)
            atlas_order_test_euids.append(atlas_order_test_euid)
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
        tenant_contexts = self._atlas_tenant_contexts(instance)
        if not tenant_contexts:
            raise ValueError("Bloom Atlas context requires an explicit registration tenant or typed reference")
        atlas_tenant_id = next(iter(tenant_contexts))
        if not fulfillment_items:
            return {
                "atlas_tenant_id": atlas_tenant_id,
                "atlas_order_euid": atlas_order_euid,
                "atlas_order_test_euid": atlas_order_test_euid,
                "atlas_order_test_euids": atlas_order_test_euids,
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
                "fulfillment_slots": [],
            }
        first = fulfillment_items[0]
        fulfillment_slot_payloads = [
            {
                "atlas_order_test_euid": item["atlas_order_test_euid"],
                "atlas_fulfillment_slot_euid": item["atlas_fulfillment_slot_euid"],
            }
            for item in sorted(
                fulfillment_items,
                key=lambda item: item["atlas_test_fulfillment_item_euid"],
            )
            if item.get("atlas_order_test_euid")
            and item.get("atlas_fulfillment_slot_euid")
        ]
        return {
            "atlas_tenant_id": first["atlas_tenant_id"],
            "atlas_order_euid": atlas_order_euid,
            "atlas_order_test_euid": atlas_order_test_euid,
            "atlas_order_test_euids": atlas_order_test_euids,
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
            "fulfillment_slots": fulfillment_slot_payloads,
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
