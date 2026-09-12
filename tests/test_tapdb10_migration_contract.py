from __future__ import annotations

import importlib.util
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


conversion = _load_script("bloom_tapdb10_conversion.py")
sequence_transition = _load_script("bloom_sequence_transition_receipt.py")
sequence_floors = _load_script("bloom_sequence_floor_prepare.py")
xrf_templates = _load_script("bloom_tapdb10_xrf_templates.py")


def test_sequence_floor_cli_input_contains_only_floors() -> None:
    records = [{"name": "allocator", "value": 12, "source": "frozen-source"}]

    document = sequence_floors._cli_floor_document(records)

    assert document == {"floors": records}


def test_xrf_template_validation_preserves_every_original_fingerprint() -> None:
    before = {
        "all_template_count": 239,
        "all_template_fingerprints": {"1": "original-a", "2": "original-b"},
        "existing": [],
        "expected_inserted": 2,
    }
    after = {
        "all_template_count": 241,
        "all_template_fingerprints": {
            "1": "original-a",
            "2": "changed-original-b",
            "3": "new-xrf-a",
            "4": "new-xrf-b",
        },
        "existing": [{"subtype": "opaque"}, {"subtype": "tapdb_object"}],
    }

    with pytest.raises(ValueError, match="changed existing templates"):
        xrf_templates._validate_after(before, after)


def test_xrf_template_state_fingerprints_every_loaded_template(bdb) -> None:
    _, definitions = xrf_templates._definitions()

    state = xrf_templates._state(bdb.session, definitions)

    assert len(state["all_template_fingerprints"]) == state["all_template_count"]
    assert all(
        len(value) == 64 for value in state["all_template_fingerprints"].values()
    )


def test_xrf_template_coordinates_follow_released_package() -> None:
    _, definitions = xrf_templates._definitions()

    assert {
        (item["category"], item["type"], item["subtype"], item["version"])
        for item in definitions
    } == {
        ("reference", "external_identifier", "opaque", "1.0"),
        ("reference", "external_identifier", "tapdb_object", "2.0"),
    }


def test_xrf_template_validation_accepts_only_additive_version() -> None:
    before = {
        "all_template_count": 239,
        "all_template_fingerprints": {
            "7": "historical-tapdb-object-v1",
            "8": "unrelated-template",
        },
        "existing": [],
        "expected_inserted": 2,
    }
    after = {
        "all_template_count": 241,
        "all_template_fingerprints": {
            **before["all_template_fingerprints"],
            "240": "new-opaque-v1",
            "241": "new-tapdb-object-v2",
        },
        "existing": [
            {"subtype": "opaque", "version": "1.0"},
            {"subtype": "tapdb_object", "version": "2.0"},
        ],
    }

    xrf_templates._validate_after(before, after)


def test_metadata_conversion_adds_only_envelope_and_archives_graph() -> None:
    original = {
        "label": "retained",
        "properties": {
            "external_payload": {
                "tapdb_graph": [
                    {"system": "atlas", "root_euid": "persisted-reference"}
                ],
                "retained": {"value": 1},
            }
        },
    }

    converted, graph, graph_present = conversion._converted_payload(
        original, archive_key="bloom_tapdb10_archive"
    )

    assert original["properties"]["external_payload"]["tapdb_graph"] == graph
    assert "tapdb_graph" not in converted["properties"]["external_payload"]
    assert converted["properties"]["external_payload"]["retained"] == {"value": 1}
    assert converted["bloom_tapdb10_archive"] == {
        "properties.external_payload.tapdb_graph": graph
    }
    assert graph_present is True


def test_graph_partition_archives_only_lineage_matches_with_positions() -> None:
    matched = {
        "system": "atlas",
        "root_euid": "persisted-reference",
        "relationship_type": "prepared_for_atlas_test",
        "source_field": "atlas_test",
    }
    unresolved = {
        "system": "atlas",
        "root_euid": "unresolved-reference",
        "relationship_type": "received_from_atlas_trf",
        "source_field": "atlas_trf",
    }

    archived, retained = conversion._partition_graph_entries(
        [unresolved, matched],
        {
            (
                "persisted-reference",
                "prepared_for_atlas_test",
                "",
                "atlas_test",
            )
        },
    )

    assert archived == [{"position": 1, "entry": matched}]
    assert retained == [unresolved]


def test_metadata_conversion_repairs_only_missing_properties() -> None:
    converted, graph, graph_present = conversion._converted_payload(
        {"label": "retained"}, archive_key="bloom_tapdb10_archive"
    )

    assert converted == {"label": "retained", "properties": {}}
    assert graph == []
    assert graph_present is False


def test_conversion_plan_comparison_ignores_only_native_receipt_time() -> None:
    planned = {
        "conversion": {
            "metadata_changes": [
                {
                    "uid": 7,
                    "native_receipt": {
                        "recorded_at": "2026-09-11T12:00:00+00:00",
                        "actor": "migration",
                        "changes": {"json_addl": {"new": {"properties": {}}}},
                    },
                }
            ]
        }
    }
    current = deepcopy(planned)
    current["conversion"]["metadata_changes"][0]["native_receipt"][
        "recorded_at"
    ] = "2026-09-11T12:01:00+00:00"

    assert conversion._plan_equality_projection(
        current
    ) == conversion._plan_equality_projection(planned)

    current["conversion"]["metadata_changes"][0]["native_receipt"]["actor"] = (
        "changed-actor"
    )
    assert conversion._plan_equality_projection(
        current
    ) != conversion._plan_equality_projection(planned)


def test_metadata_conversion_rejects_malformed_or_replayed_values() -> None:
    with pytest.raises(ValueError, match="properties must be an object"):
        conversion._converted_payload(
            {"properties": []}, archive_key="bloom_tapdb10_archive"
        )
    with pytest.raises(ValueError, match="already exists"):
        conversion._converted_payload(
            {"properties": {}, "bloom_tapdb10_archive": {}},
            archive_key="bloom_tapdb10_archive",
        )


def test_legacy_atlas_target_retains_tenant_in_canonical_namespace() -> None:
    target = conversion._external_target(
        {
            "provider": "atlas",
            "reference_type": "Atlas Patient",
            "reference_value": "opaque-patient-reference",
            "atlas_tenant_id": "11111111-1111-4111-8111-111111111111",
        }
    )

    assert target.namespace == "atlas.11111111-1111-4111-8111-111111111111"
    assert target.kind == "atlas_patient"
    assert target.value == "opaque-patient-reference"
    assert target.scope == "public_global"


def test_legacy_bgx_preservation_retains_duplicate_and_deleted_evidence() -> None:
    source = SimpleNamespace(uid=7, euid="persisted-source")
    records = [
        {
            "ref": SimpleNamespace(uid=11, euid="persisted-ref-a", is_deleted=False),
            "lineage": SimpleNamespace(
                uid=21, euid="persisted-lineage-a", is_deleted=False
            ),
            "lineages": [
                SimpleNamespace(
                    uid=21,
                    euid="persisted-lineage-a",
                    is_deleted=False,
                    parent_instance_uid=7,
                    parent_instance=source,
                )
            ],
            "source": source,
            "disposition": "canonical_atlas",
            "fingerprint": "a" * 64,
        },
        {
            "ref": SimpleNamespace(uid=12, euid="persisted-ref-b", is_deleted=True),
            "lineage": SimpleNamespace(
                uid=22, euid="persisted-lineage-b", is_deleted=True
            ),
            "lineages": [
                SimpleNamespace(
                    uid=22,
                    euid="persisted-lineage-b",
                    is_deleted=True,
                    parent_instance_uid=7,
                    parent_instance=source,
                )
            ],
            "source": source,
            "disposition": "canonical_atlas",
            "fingerprint": "b" * 64,
        },
    ]

    receipt = conversion._legacy_preservation(records)

    assert [item["ref_uid"] for item in receipt] == [11, 12]
    assert [item["ref_euid"] for item in receipt] == [
        "persisted-ref-a",
        "persisted-ref-b",
    ]
    assert [item["ref_deleted"] for item in receipt] == [False, True]
    assert [item["lineages"][0]["deleted"] for item in receipt] == [False, True]


def test_converted_fulfillment_reference_round_trips_full_native_context(bdb) -> None:
    from daylily_tapdb.external_references import ExternalReferenceService

    from bloom_lims.atlas_references import (
        ASSERTION_AUTHORITY,
        list_reference_payloads,
        replace_references,
    )
    from bloom_lims.domain import BloomObj

    source = BloomObj(bdb).create_instance_by_code(
        "material/specimen/blood-whole/1.0",
        {"json_addl": {"properties": {"name": "migration-reader-proof"}}},
    )
    tenant = "tenant-migration-reader-proof"
    fulfillment = "fulfillment-migration-reader-proof"
    properties = {
        "provider": "atlas",
        "reference_type": "atlas_test_fulfillment_item",
        "reference_value": fulfillment,
        "foreign_reference": fulfillment,
        "atlas_tenant_id": tenant,
        "atlas_trf_euid": "trf-migration-reader-proof",
        "atlas_test_euid": "test-migration-reader-proof",
        "atlas_order_euid": "order-migration-reader-proof",
        "atlas_order_test_euid": "order-test-migration-reader-proof",
        "atlas_test_fulfillment_item_euid": fulfillment,
        "validation": {"state": "reviewed"},
    }
    target = conversion._external_target(properties)
    plan = {
        "conversion": {
            "metadata_changes": [],
            "canonical_assertions": [
                {
                    "source_uid": source.uid,
                    "source_euid": source.euid,
                    "relationship_type": "references_atlas_atlas_test_fulfillment_item",
                    "target": {
                        "namespace": target.namespace,
                        "kind": target.kind,
                        "value": target.value,
                        "scope": target.scope,
                    },
                    "active": True,
                    "properties": properties,
                    "legacy_records": [
                        {
                            "ref_uid": 1,
                            "ref_euid": "legacy-reference-proof",
                            "ref_deleted": False,
                            "lineage_uid": 2,
                            "lineage_euid": "legacy-lineage-proof",
                            "lineage_deleted": False,
                            "fingerprint": "f" * 64,
                        }
                    ],
                    "asserted_at": datetime.now(UTC).isoformat(),
                    "deactivated_at": datetime.now(UTC).isoformat(),
                }
            ],
        }
    }

    conversion._apply(bdb.session, plan, actor="migration-reader-proof")
    bdb.session.commit()
    payload = list_reference_payloads(bdb.session, source)[0]
    before_replay = ExternalReferenceService(bdb.session).list_for_source(
        source, assertion_authority=ASSERTION_AUTHORITY, limit=100
    )["items"][0]
    replace_references(bdb.session, source, [properties])
    bdb.session.commit()
    after_replay = ExternalReferenceService(bdb.session).list_for_source(
        source, assertion_authority=ASSERTION_AUTHORITY, limit=100
    )["items"][0]

    assert payload == properties
    assert after_replay["assertion_provenance"] == before_replay["assertion_provenance"]
    assert after_replay["asserted_at"] == before_replay["asserted_at"]


def test_completed_transition_verifies_against_prior_floors_only() -> None:
    prior = [{"name": "allocator", "value": 40, "source": "source_next"}]
    plan = {
        "sha256": "plan-sha",
        "floors": prior,
        "advances": [{"name": "allocator", "next_value": 48}],
    }
    result = {
        "phase": "committed",
        "plan_sha256": "plan-sha",
        "verification": {
            "ok": True,
            "violations": [],
            "floors": prior,
            "inventory_sha256": "inventory-sha",
        },
        "inventory": {"sha256": "inventory-sha"},
        "floors": [
            *prior,
            {
                "name": "allocator",
                "value": 48,
                "source": "sequence_advance_intent",
            },
        ],
    }

    verified_prior, future = sequence_transition._validated_floor_sets(plan, result)

    assert verified_prior == prior
    assert future[-1]["value"] == 48
    with pytest.raises(ValueError, match="prior plan floors"):
        sequence_transition._validated_floor_sets(
            plan,
            {
                **result,
                "verification": {**result["verification"], "floors": result["floors"]},
            },
        )
