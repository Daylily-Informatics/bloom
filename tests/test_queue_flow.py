"""End-to-end tests for Bloom's beta queue-driven lab flow."""

from __future__ import annotations

import os
import secrets
import sys

import pytest
from fastapi.testclient import TestClient

from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth
from bloom_lims.auth.rbac import ENABLE_ATLAS_API_GROUP, ENABLE_URSA_API_GROUP
from bloom_lims.bobjs import BloomObj
from bloom_lims.db import BLOOMdb3, get_parent_lineages

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_overrides(monkeypatch):
    monkeypatch.setenv("MERIDIAN_ENVIRONMENT", "production")
    monkeypatch.setenv("MERIDIAN_SANDBOX_PREFIX", "")
    yield
    app.dependency_overrides.clear()


def _external_rw_user() -> APIUser:
    token = secrets.token_hex(8)
    return APIUser(
        email="beta-queue@example.com",
        user_id=f"user-{token}",
        roles=["INTERNAL_READ_WRITE"],
        groups=[ENABLE_ATLAS_API_GROUP, ENABLE_URSA_API_GROUP],
        auth_source="token",
        is_service_account=True,
        token_scope="internal_rw",
        token_id=f"token-{token}",
    )


def _opaque(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def _assert_no_uuid_keys(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert "uuid" not in str(key).lower()
            _assert_no_uuid_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_uuid_keys(item)


def _atlas_context_payload() -> dict[str, object]:
    return {
        "atlas_tenant_id": _opaque("tenant"),
        "atlas_trf_euid": _opaque("trf"),
        "atlas_test_euid": _opaque("test-primary"),
        "atlas_test_euids": [_opaque("test-secondary")],
        "atlas_patient_euid": _opaque("patient"),
        "fulfillment_items": [
            {
                "atlas_test_euid": _opaque("test"),
                "atlas_test_fulfillment_item_euid": _opaque("proc"),
            }
        ],
    }


def _create_material_and_queue(
    client: TestClient, *, queue_name: str = "extraction_prod"
):
    atlas_context = _atlas_context_payload()
    material_idem = _opaque("idem-material")
    created = client.post(
        "/api/v1/external/atlas/beta/materials",
        headers={"Idempotency-Key": material_idem},
        json={
            "specimen_name": "beta-whole-blood",
            "properties": {"source": "pytest-beta-queue"},
            "atlas_context": atlas_context,
        },
    )
    assert created.status_code == 200, created.text
    material = created.json()
    queue_resp = client.post(
        f"/api/v1/external/atlas/beta/queues/{queue_name}/items/{material['container_euid']}",
        headers={"Idempotency-Key": _opaque("idem-queue")},
        json={"metadata": {"reason": "accepted-material"}},
    )
    assert queue_resp.status_code == 200, queue_resp.text
    return material, atlas_context


def _ensure_reference_instance(*, category: str, type_name: str | None = None) -> str:
    bdb = BLOOMdb3(app_username="pytest-beta-queue")
    try:
        GI = bdb.Base.classes.generic_instance
        query = bdb.session.query(GI).filter(
            GI.is_deleted.is_(False),
            GI.category == category,
        )
        if type_name is not None:
            query = query.filter(GI.type == type_name)
        existing = query.first()
        if existing is not None:
            return existing.euid

        GT = bdb.Base.classes.generic_template
        template_query = bdb.session.query(GT).filter(
            GT.is_deleted.is_(False),
            GT.category == category,
        )
        if type_name is not None:
            template_query = template_query.filter(GT.type == type_name)
        template = template_query.first()
        assert template is not None, f"missing template for {category=} {type_name=}"

        bobj = BloomObj(bdb)
        template_code = (
            f"{template.category}/{template.type}/{template.subtype}/{template.version}"
        )
        created = bobj.create_instance_by_code(
            template_code,
            {
                "json_addl": {
                    "properties": {"name": f"pytest-{category}-{secrets.token_hex(4)}"}
                }
            },
        )
        bdb.session.commit()
        return created.euid
    finally:
        bdb.close()


def test_beta_queue_flow_end_to_end():
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    atlas_context = {
        "atlas_tenant_id": _opaque("tenant"),
        "atlas_trf_euid": _opaque("trf"),
        "atlas_patient_euid": _opaque("patient"),
        "fulfillment_items": [
            {
                "atlas_test_euid": _opaque("test"),
                "atlas_test_fulfillment_item_euid": _opaque("proc"),
            }
        ],
    }
    material_idem = _opaque("idem-material")

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": material_idem},
            json={
                "specimen_name": "beta-whole-blood",
                "properties": {"source": "pytest-beta-queue"},
                "atlas_context": atlas_context,
            },
        )
        assert created.status_code == 200, created.text
        material = created.json()
        _assert_no_uuid_keys(material)
        assert material["created"] is True
        assert material["current_queue"] is None
        assert (
            material["atlas_context"]["atlas_trf_euid"]
            == atlas_context["atlas_trf_euid"]
        )
        assert (
            material["atlas_context"]["atlas_patient_euid"]
            == atlas_context["atlas_patient_euid"]
        )
        assert (
            material["atlas_context"]["fulfillment_items"][0][
                "atlas_test_fulfillment_item_euid"
            ]
            == atlas_context["fulfillment_items"][0]["atlas_test_fulfillment_item_euid"]
        )

        replay = client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": material_idem},
            json={
                "specimen_name": "beta-whole-blood",
                "properties": {"source": "pytest-beta-queue"},
                "atlas_context": atlas_context,
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["created"] is False

        specimen_euid = material["specimen_euid"]
        container_euid = material["container_euid"]

        queued = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{container_euid}",
            headers={"Idempotency-Key": _opaque("idem-queue")},
            json={"metadata": {"reason": "accepted-material"}},
        )
        assert queued.status_code == 200, queued.text
        queue_body = queued.json()
        _assert_no_uuid_keys(queue_body)
        assert queue_body["material_euid"] == container_euid
        assert queue_body["current_queue"] == "extraction_prod"

        extraction = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract")},
            json={
                "source_specimen_euid": specimen_euid,
                "plate_name": "beta-extract-plate",
                "well_name": "A1",
                "extraction_type": "cfdna",
                "output_name": "beta-cfdna-output",
                "atlas_test_fulfillment_item_euid": atlas_context["fulfillment_items"][
                    0
                ]["atlas_test_fulfillment_item_euid"],
                "metadata": {"operator": "pytest"},
            },
        )
        assert extraction.status_code == 200, extraction.text
        extraction_body = extraction.json()
        _assert_no_uuid_keys(extraction_body)
        assert extraction_body["current_queue"] == "post_extract_qc"
        assert (
            extraction_body["atlas_test_fulfillment_item_euid"]
            == atlas_context["fulfillment_items"][0]["atlas_test_fulfillment_item_euid"]
        )
        extraction_output_euid = extraction_body["extraction_output_euid"]

        qc = client.post(
            "/api/v1/external/atlas/beta/post-extract-qc",
            headers={"Idempotency-Key": _opaque("idem-qc")},
            json={
                "extraction_output_euid": extraction_output_euid,
                "passed": True,
                "next_queue": "ilmn_lib_prep",
                "metrics": {"yield_ng": 42.5},
            },
        )
        assert qc.status_code == 200, qc.text
        assert qc.json()["current_queue"] == "ilmn_lib_prep"

        library_prep = client.post(
            "/api/v1/external/atlas/beta/library-prep",
            headers={"Idempotency-Key": _opaque("idem-libprep")},
            json={
                "source_extraction_output_euid": extraction_output_euid,
                "platform": "ILMN",
                "output_name": "beta-ilmn-lib",
                "metadata": {"kit": "ilmn-beta"},
            },
        )
        assert library_prep.status_code == 200, library_prep.text
        library_body = library_prep.json()
        assert library_body["current_queue"] == "ilmn_seq_pool"
        assert (
            library_body["atlas_test_fulfillment_item_euid"]
            == atlas_context["fulfillment_items"][0]["atlas_test_fulfillment_item_euid"]
        )
        lib_output_euid = library_body["library_prep_output_euid"]
        library_material_euid = library_body["library_material_euid"]
        library_container_euid = library_body["library_container_euid"]
        library_plate_euid = library_body["library_plate_euid"]
        library_well_euid = library_body["library_well_euid"]
        assert library_material_euid.startswith("MX-")
        assert library_container_euid.startswith("CX-")
        assert library_plate_euid.startswith("CX-")
        assert library_well_euid.startswith("CWX-")

        pool = client.post(
            "/api/v1/external/atlas/beta/pools",
            headers={"Idempotency-Key": _opaque("idem-pool")},
            json={
                "member_euids": [library_material_euid],
                "platform": "ILMN",
                "pool_name": "beta-seq-pool",
                "metadata": {"pool_strategy": "singleplex"},
            },
        )
        assert pool.status_code == 200, pool.text
        pool_body = pool.json()
        assert pool_body["current_queue"] == "ilmn_start_seq_run"
        pool_euid = pool_body["pool_euid"]

        flowcell_id = "FLOWCELL-001"
        lane = "1"
        library_barcode = "IDX-ILMN-A1"
        run = client.post(
            "/api/v1/external/atlas/beta/runs",
            headers={"Idempotency-Key": _opaque("idem-run")},
            json={
                "pool_euid": pool_euid,
                "platform": "ILMN",
                "flowcell_id": flowcell_id,
                "run_name": "beta-ilmn-run",
                "status": "completed",
                "assignments": [
                    {
                        "lane": lane,
                        "library_barcode": library_barcode,
                        "library_prep_output_euid": lib_output_euid,
                    }
                ],
                "artifacts": [
                    {
                        "artifact_type": "fastq",
                        "bucket": "beta-runs",
                        "filename": "reads_R1.fastq.gz",
                        "lane": lane,
                        "library_barcode": library_barcode,
                        "metadata": {"read_pair": 1},
                    }
                ],
            },
        )
        assert run.status_code == 200, run.text
        run_body = run.json()
        _assert_no_uuid_keys(run_body)
        assert run_body["status"] == "completed"
        assert run_body["artifact_count"] == 1
        assert run_body["assignment_count"] == 1
        assert run_body["flowcell_id"] == flowcell_id
        assert run_body["run_folder"] == f"{run_body['run_euid']}/"

        resolved = client.get(
            f"/api/v1/external/atlas/beta/runs/{run_body['run_euid']}/resolve",
            params={
                "flowcell_id": flowcell_id,
                "lane": lane,
                "library_barcode": library_barcode,
            },
        )
        assert resolved.status_code == 200, resolved.text
        resolved_body = resolved.json()
        _assert_no_uuid_keys(resolved_body)
        assert resolved_body["atlas_tenant_id"] == atlas_context["atlas_tenant_id"]
        assert resolved_body["atlas_trf_euid"] == atlas_context["atlas_trf_euid"]
        assert (
            resolved_body["atlas_test_euid"]
            == atlas_context["fulfillment_items"][0]["atlas_test_euid"]
        )
        assert (
            resolved_body["atlas_test_fulfillment_item_euid"]
            == atlas_context["fulfillment_items"][0]["atlas_test_fulfillment_item_euid"]
        )


def test_queue_claim_success_and_conflict_blocked():
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    with TestClient(app) as client:
        material, _atlas_context = _create_material_and_queue(client)
        claim = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{material['container_euid']}/claim",
            headers={"Idempotency-Key": _opaque("idem-claim")},
            json={"metadata": {"operator": "pytest"}},
        )
        assert claim.status_code == 200, claim.text
        claim_body = claim.json()
        assert claim_body["status"] == "active"
        assert claim_body["material_euid"] == material["container_euid"]

        conflict = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{material['container_euid']}/claim",
            headers={"Idempotency-Key": _opaque("idem-claim-conflict")},
            json={"metadata": {}},
        )
        assert conflict.status_code == 400

        released = client.post(
            f"/api/v1/external/atlas/beta/claims/{claim_body['claim_euid']}/release",
            headers={"Idempotency-Key": _opaque("idem-release-claim")},
            json={"reason": "completed", "metadata": {}},
        )
        assert released.status_code == 200, released.text
        assert released.json()["status"] == "completed"


def test_reservation_blocks_claim_and_stage_until_release():
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    with TestClient(app) as client:
        material, atlas_context = _create_material_and_queue(client)

        reserve_container = client.post(
            f"/api/v1/external/atlas/beta/materials/{material['container_euid']}/reservations",
            headers={"Idempotency-Key": _opaque("idem-reserve-container")},
            json={"reason": "manual_hold", "metadata": {}},
        )
        assert reserve_container.status_code == 200, reserve_container.text
        reservation_euid = reserve_container.json()["reservation_euid"]

        blocked_claim = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{material['container_euid']}/claim",
            headers={"Idempotency-Key": _opaque("idem-claim-blocked")},
            json={"metadata": {}},
        )
        assert blocked_claim.status_code == 400

        release_container = client.post(
            f"/api/v1/external/atlas/beta/reservations/{reservation_euid}/release",
            headers={"Idempotency-Key": _opaque("idem-release-container")},
            json={"reason": "released", "metadata": {}},
        )
        assert release_container.status_code == 200, release_container.text

        unblocked_claim = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{material['container_euid']}/claim",
            headers={"Idempotency-Key": _opaque("idem-claim-unblocked")},
            json={"metadata": {}},
        )
        assert unblocked_claim.status_code == 200, unblocked_claim.text
        claim_euid = unblocked_claim.json()["claim_euid"]
        client.post(
            f"/api/v1/external/atlas/beta/claims/{claim_euid}/release",
            headers={"Idempotency-Key": _opaque("idem-release-claim")},
            json={"reason": "completed", "metadata": {}},
        )

        reserve_specimen = client.post(
            f"/api/v1/external/atlas/beta/materials/{material['specimen_euid']}/reservations",
            headers={"Idempotency-Key": _opaque("idem-reserve-specimen")},
            json={"reason": "qc_hold", "metadata": {}},
        )
        assert reserve_specimen.status_code == 200, reserve_specimen.text
        specimen_reservation_euid = reserve_specimen.json()["reservation_euid"]

        blocked_stage = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract-blocked")},
            json={
                "source_specimen_euid": material["specimen_euid"],
                "plate_name": "beta-reservation-plate",
                "well_name": "A1",
                "extraction_type": "cfdna",
                "atlas_test_fulfillment_item_euid": atlas_context["fulfillment_items"][
                    0
                ]["atlas_test_fulfillment_item_euid"],
                "metadata": {"operator": "pytest"},
            },
        )
        assert blocked_stage.status_code == 400

        release_specimen = client.post(
            f"/api/v1/external/atlas/beta/reservations/{specimen_reservation_euid}/release",
            headers={"Idempotency-Key": _opaque("idem-release-specimen")},
            json={"reason": "released", "metadata": {}},
        )
        assert release_specimen.status_code == 200, release_specimen.text

        extraction = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract-after-release")},
            json={
                "source_specimen_euid": material["specimen_euid"],
                "plate_name": "beta-reservation-plate",
                "well_name": "A1",
                "extraction_type": "cfdna",
                "atlas_test_fulfillment_item_euid": atlas_context["fulfillment_items"][
                    0
                ]["atlas_test_fulfillment_item_euid"],
                "metadata": {"operator": "pytest"},
            },
        )
        assert extraction.status_code == 200, extraction.text


def test_consume_prevents_stage_reuse_and_implicit_claim_still_works():
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    with TestClient(app) as client:
        material, atlas_context = _create_material_and_queue(client)
        extraction = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract-consume")},
            json={
                "source_specimen_euid": material["specimen_euid"],
                "plate_name": "beta-consume-plate",
                "well_name": "A1",
                "extraction_type": "cfdna",
                "atlas_test_fulfillment_item_euid": atlas_context["fulfillment_items"][
                    0
                ]["atlas_test_fulfillment_item_euid"],
                "consume_source": True,
                "metadata": {"operator": "pytest"},
            },
        )
        assert extraction.status_code == 200, extraction.text

        second_extraction = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract-reuse")},
            json={
                "source_specimen_euid": material["specimen_euid"],
                "plate_name": "beta-consume-plate",
                "well_name": "A2",
                "extraction_type": "cfdna",
                "atlas_test_fulfillment_item_euid": atlas_context["fulfillment_items"][
                    0
                ]["atlas_test_fulfillment_item_euid"],
                "metadata": {"operator": "pytest"},
            },
        )
        assert second_extraction.status_code == 400


def test_metadata_normalization_and_execution_lineage_validation():
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    instrument_euid = _ensure_reference_instance(category="equipment")
    reagent_euid = _ensure_reference_instance(category="content", type_name="reagent")

    with TestClient(app) as client:
        material, atlas_context = _create_material_and_queue(client)
        extraction = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract-metadata")},
            json={
                "source_specimen_euid": material["specimen_euid"],
                "plate_name": "beta-metadata-plate",
                "well_name": "A1",
                "extraction_type": "cfdna",
                "atlas_test_fulfillment_item_euid": atlas_context["fulfillment_items"][
                    0
                ]["atlas_test_fulfillment_item_euid"],
                "metadata": {
                    "operator": "  tech-1  ",
                    "method_version": "  v2.0 ",
                    "instrument_euid": instrument_euid,
                    "reagent_euid": reagent_euid,
                    "custom_key": "custom-value",
                    "empty_value": "   ",
                },
            },
        )
        assert extraction.status_code == 200, extraction.text
        output_euid = extraction.json()["extraction_output_euid"]

        bad_metadata = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract-bad-metadata")},
            json={
                "source_specimen_euid": material["specimen_euid"],
                "plate_name": "beta-metadata-plate",
                "well_name": "A2",
                "extraction_type": "cfdna",
                "atlas_test_fulfillment_item_euid": atlas_context["fulfillment_items"][
                    0
                ]["atlas_test_fulfillment_item_euid"],
                "metadata": {
                    "instrument_euid": material["specimen_euid"],
                },
            },
        )
        assert bad_metadata.status_code == 400
        assert "instrument_euid" in bad_metadata.text

    bdb = BLOOMdb3(app_username="pytest-beta-queue")
    try:
        instance = (
            bdb.session.query(bdb.Base.classes.generic_instance)
            .filter(
                bdb.Base.classes.generic_instance.euid == output_euid,
                bdb.Base.classes.generic_instance.is_deleted.is_(False),
            )
            .one()
        )
        props = (instance.json_addl or {}).get("properties", {})
        metadata = props.get("metadata") if isinstance(props, dict) else {}
        assert metadata["operator"] == "tech-1"
        assert metadata["method_version"] == "v2.0"
        assert metadata["custom_key"] == "custom-value"
        assert "empty_value" not in metadata

        lineage_targets = {
            (lineage.relationship_type, lineage.child_instance.euid)
            for lineage in get_parent_lineages(instance)
            if not lineage.is_deleted and lineage.child_instance is not None
        }
        assert ("beta_used_instrument", instrument_euid) in lineage_targets
        assert ("beta_used_reagent", reagent_euid) in lineage_targets
    finally:
        bdb.close()
