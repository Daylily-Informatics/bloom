"""
Route coverage gap tests (API).

These tests exist to ensure every API endpoint has at least one test that
executes the handler body (not just FastAPI validation).
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Set up auth bypass BEFORE importing FastAPI app
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

from fastapi.testclient import TestClient

from bloom_lims.api.v1.dependencies import APIUser, require_external_atlas_api_enabled
from bloom_lims.template_identity import template_category_filter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _get_template_euid(
    bdb,
    *,
    category: str,
    type_name: str | None = None,
    subtype: str | None = None,
    version: str | None = None,
) -> str:
    GT = bdb.Base.classes.generic_template
    q = bdb.session.query(GT).filter(GT.is_deleted == False)
    category_filter = template_category_filter(GT, category)
    if category_filter is not None:
        q = q.filter(category_filter)
    domain_code = (os.environ.get("MERIDIAN_DOMAIN_CODE") or "Z").strip().upper() or "Z"
    q = q.filter(GT.domain_code == domain_code)
    if type_name is not None:
        q = q.filter(GT.type == type_name)
    if subtype is not None:
        q = q.filter(GT.subtype == subtype)
    if version is not None:
        q = q.filter(GT.version == version)
    row = q.first()
    assert row is not None, f"Missing template for {category=} {type_name=} {subtype=} {version=}"
    return row.euid


def _create_instance_via_object_creation(
    client: TestClient,
    *,
    category: str,
    type_name: str,
    subtype: str,
    version: str,
    name: str | None = None,
) -> dict:
    payload = {
        "category": category,
        "type": type_name,
        "subtype": subtype,
        "version": version,
    }
    if name is not None:
        payload["name"] = name
    resp = client.post("/api/v1/object-creation/create", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_actions_endpoints_execute_handler_body(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/actions/aliquot",
        json={"source_euid": "NONEXISTENT", "num_aliquots": 1, "volume_unit": "uL"},
    )
    assert resp.status_code == 404

    resp = client.post(
        "/api/v1/actions/transfer",
        json={"source_euid": "NONEXISTENT", "destination_euid": "ALSO_BAD", "volume_unit": "uL"},
    )
    assert resp.status_code == 404

    resp = client.post(
        "/api/v1/actions/pool",
        json={"source_euids": ["NONEXISTENT"], "pool_name": "pool"},
    )
    assert resp.status_code == 404


def test_batch_create_and_update_do_not_require_real_background_work(client: TestClient) -> None:
    with patch(
        "bloom_lims.core.batch_operations.BatchProcessor.bulk_create_objects",
        new=AsyncMock(return_value=None),
    ):
        resp = client.post(
            "/api/v1/batch/create",
            json={"template_euid": "GT-NOT-REAL", "count": 1, "name_pattern": "Obj_{index}"},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["operation"] == "bulk_create"
        assert payload["status"]

    with patch(
        "bloom_lims.core.batch_operations.BatchProcessor.bulk_update_objects",
        new=AsyncMock(return_value=None),
    ):
        resp = client.post(
            "/api/v1/batch/update",
            json={"updates": [{"euid": "NONEXISTENT", "name": "new"}]},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["operation"] == "bulk_update"


def test_tracking_carriers_and_track_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/tracking/carriers")
    assert resp.status_code == 200
    assert "carriers" in resp.json()

    with patch("bloom_lims.api.v1.tracking._get_fedex_tracker", return_value=None):
        resp = client.post("/api/v1/tracking/track", json={"tracking_number": "123", "carrier": "FedEx"})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["carrier"] == "FedEx"
        assert payload.get("error")


def test_containers_content_link_layout_and_delete(client: TestClient, bdb) -> None:
    container_template = _get_template_euid(
        bdb, category="container", type_name="tube", subtype="tube-generic-10ml", version="1.0"
    )
    sample_template = _get_template_euid(bdb, category="content", type_name="sample", subtype="blood-plasma", version="1.0")

    with patch("bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None):
        create_container = client.post(
            "/api/v1/containers/",
            json={
                "template_euid": container_template,
                "name": "coverage-container",
                "container_type": "tube",
            },
        )
    assert create_container.status_code == 200, create_container.text
    create_container_payload = create_container.json()
    assert "uuid" not in create_container_payload
    container_euid = create_container_payload["euid"]

    container_get = client.get(f"/api/v1/containers/{container_euid}")
    assert container_get.status_code == 200, container_get.text
    assert "uuid" not in container_get.json()

    create_sample = client.post(
        "/api/v1/content/samples",
        json={
            "template_euid": sample_template,
            "name": "coverage-sample",
        },
    )
    assert create_sample.status_code == 200, create_sample.text
    create_sample_payload = create_sample.json()
    assert "uuid" not in create_sample_payload
    content_euid = create_sample_payload["euid"]

    content_get = client.get(f"/api/v1/content/{content_euid}")
    assert content_get.status_code == 200, content_get.text
    assert "uuid" not in content_get.json()

    # Place content in container (API v1 route)
    link_resp = client.post(
        f"/api/v1/containers/{container_euid}/contents",
        json={"container_euid": container_euid, "object_euid": content_euid, "position": "A1"},
    )
    assert link_resp.status_code == 200, link_resp.text

    # Remove content from container
    unlink_resp = client.delete(f"/api/v1/containers/{container_euid}/contents/{content_euid}")
    assert unlink_resp.status_code == 200, unlink_resp.text

    # Layout endpoint: exercise handler body (404 is acceptable)
    layout_resp = client.get(f"/api/v1/containers/{container_euid}/layout")
    assert layout_resp.status_code in (200, 404), layout_resp.text

    with patch("bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None):
        del_resp = client.delete(f"/api/v1/containers/{container_euid}")
    assert del_resp.status_code == 200, del_resp.text


def test_content_create_update_and_delete_endpoints(client: TestClient, bdb) -> None:
    sample_template = _get_template_euid(bdb, category="content", type_name="sample", subtype="gdna", version="1.0")
    specimen_template = _get_template_euid(bdb, category="content", type_name="specimen", subtype="blood-whole", version="1.0")
    reagent_template = _get_template_euid(bdb, category="content", type_name="reagent", subtype="naoh", version="1.0")

    sample = client.post(
        "/api/v1/content/samples",
        json={"template_euid": sample_template, "name": "gdna-sample"},
    )
    assert sample.status_code == 200, sample.text
    sample_payload = sample.json()
    assert "uuid" not in sample_payload
    sample_euid = sample_payload["euid"]

    specimen = client.post(
        "/api/v1/content/specimens",
        json={"template_euid": specimen_template, "name": "blood-specimen", "specimen_type": "blood"},
    )
    assert specimen.status_code == 200, specimen.text
    assert "uuid" not in specimen.json()

    reagent = client.post(
        "/api/v1/content/reagents",
        json={"template_euid": reagent_template, "name": "naoh-reagent", "reagent_type": "naoh"},
    )
    assert reagent.status_code == 200, reagent.text
    assert "uuid" not in reagent.json()

    with patch("bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None):
        update = client.put(f"/api/v1/content/{sample_euid}", json={"name": "updated-name"})
    assert update.status_code == 200, update.text

    updated_sample = client.get(f"/api/v1/content/{sample_euid}")
    assert updated_sample.status_code == 200, updated_sample.text
    assert "uuid" not in updated_sample.json()


def test_objects_crud_endpoints(client: TestClient) -> None:
    create = client.post(
        "/api/v1/objects/",
        json={
            "name": "coverage-object",
            "category": "content",
            "type": "sample",
            "subtype": "gdna",
            "json_addl": {"properties": {"name": "coverage-object"}},
        },
    )
    assert create.status_code == 200, create.text
    create_payload = create.json()
    assert "uuid" not in create_payload
    euid = create_payload["euid"]

    get_resp = client.get(f"/api/v1/objects/{euid}")
    assert get_resp.status_code == 200, get_resp.text
    assert "uuid" not in get_resp.json()

    update = client.put(f"/api/v1/objects/{euid}", json={"name": "coverage-object-updated"})
    assert update.status_code == 200, update.text

    delete = client.delete(f"/api/v1/objects/{euid}")
    assert delete.status_code == 200, delete.text


def test_lineages_create_and_delete(client: TestClient) -> None:
    parent = _create_instance_via_object_creation(
        client,
        category="container",
        type_name="tube",
        subtype="tube-generic-10ml",
        version="1.0",
        name="lineage-parent",
    )
    child = _create_instance_via_object_creation(
        client,
        category="container",
        type_name="tube",
        subtype="tube-generic-10ml",
        version="1.0",
        name="lineage-child",
    )

    create = client.post(
        "/api/v1/lineages/",
        json={"parent_euid": parent["euid"], "child_euid": child["euid"], "relationship_type": "generic"},
    )
    assert create.status_code == 200, create.text
    create_payload = create.json()
    assert "uuid" not in create_payload
    lineage_euid = create_payload["euid"]

    listing = client.get(
        "/api/v1/lineages/",
        params={"parent_euid": parent["euid"], "child_euid": child["euid"]},
    )
    assert listing.status_code == 200, listing.text
    listing_payload = listing.json()
    assert any(
        item["euid"] == lineage_euid
        and item["parent_euid"] == parent["euid"]
        and item["child_euid"] == child["euid"]
        for item in listing_payload["items"]
    )
    for item in listing_payload["items"]:
        assert "uuid" not in item

    delete = client.delete(f"/api/v1/lineages/{lineage_euid}")
    assert delete.status_code == 200, delete.text


def test_subjects_workflows_and_steps(client: TestClient, bdb) -> None:
    subj_template = _get_template_euid(bdb, category="subject", type_name="generic", subtype="generic-subject", version="1.0")

    subj = client.post("/api/v1/subjects/", json={"template_euid": subj_template, "name": "subj-1", "external_id": "X1"})
    assert subj.status_code == 200, subj.text
    subj_payload = subj.json()
    assert "uuid" not in subj_payload
    subj_euid = subj_payload["euid"]

    subj_get = client.get(f"/api/v1/subjects/{subj_euid}")
    assert subj_get.status_code == 200, subj_get.text
    assert "uuid" not in subj_get.json()

    subj_update = client.put(f"/api/v1/subjects/{subj_euid}", json={"status": "active"})
    assert subj_update.status_code == 200, subj_update.text

    subj_delete = client.delete(f"/api/v1/subjects/{subj_euid}")
    assert subj_delete.status_code == 200, subj_delete.text

    # Workflows API is retired for beta queue-driven execution and should not be mounted.
    wf = client.post("/api/v1/workflows/?template_euid=WF-NOT-USED&name=coverage-workflow")
    assert wf.status_code == 404, wf.text

    wf_get = client.get("/api/v1/workflows/WF-NOT-USED")
    assert wf_get.status_code == 404, wf_get.text

    wf_update = client.put("/api/v1/workflows/WF-NOT-USED?status=in_progress", json={"properties": {"note": "x"}})
    assert wf_update.status_code == 404, wf_update.text

    steps = client.get("/api/v1/workflows/WF-NOT-USED/steps")
    assert steps.status_code == 404, steps.text


def test_equipment_create_and_maintenance(client: TestClient, bdb) -> None:
    eq_template = _get_template_euid(bdb, category="equipment", type_name="freezer", subtype="freezer-m20c", version="1.0")

    eq = client.post(
        "/api/v1/equipment/",
        json={
            "template_euid": eq_template,
            "name": "coverage-freezer",
            "equipment_type": "freezer",
        },
    )
    assert eq.status_code == 200, eq.text
    eq_payload = eq.json()
    assert "uuid" not in eq_payload
    eq_euid = eq_payload["euid"]

    eq_get = client.get(f"/api/v1/equipment/{eq_euid}")
    assert eq_get.status_code == 200, eq_get.text
    assert "uuid" not in eq_get.json()

    maint = client.post(
        f"/api/v1/equipment/{eq_euid}/maintenance",
        json={
            "maintenance_type": "clean",
            "performed_date": "2026-03-03T00:00:00Z",
            "performed_by": "tester",
            "notes": "ok",
        },
    )
    assert maint.status_code == 200, maint.text


def test_file_sets_and_files_create_endpoints(client: TestClient) -> None:
    file_set = client.post("/api/v1/file-sets/", json={"name": "fs-coverage", "file_type": "generic"})
    assert file_set.status_code == 404, file_set.text

    resp = client.post(
        "/api/v1/files/",
        data={"file_metadata": "{\"name\": \"file-coverage\"}"},
    )
    assert resp.status_code == 404, resp.text


def _external_rw_user() -> APIUser:
    return APIUser(
        email="atlas-beta-route-test@example.com",
        user_id="atlas-beta-route-test",
        roles=["READ_WRITE"],
        auth_source="token",
        token_scope="internal_rw",
        token_id="token-atlas-beta-route-test",
    )


def test_beta_lab_patch_tube_and_consume_material_execute_handler_body(
    client: TestClient,
) -> None:
    class _FakeBetaLabService:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def close(self) -> None:
            return None

        def update_tube(self, *, container_euid: str, payload):
            return {
                "container_euid": container_euid,
                "status": payload.status or "active",
                "atlas_context": (
                    payload.atlas_context.model_dump(mode="json")
                    if payload.atlas_context is not None
                    else {}
                ),
                "properties": dict(payload.properties or {}),
                "idempotency_key": None,
                "current_queue": "extraction_prod",
                "created": False,
            }

        def consume_material(
            self, *, material_euid: str, reason: str | None, metadata: dict, idempotency_key: str | None
        ):
            return {
                "consumption_event_euid": "BCE-ROUTE-COVERAGE",
                "material_euid": material_euid,
                "consumed": True,
                "metadata": {"reason": reason, **dict(metadata or {})},
                "idempotent_replay": False,
            }

    app.dependency_overrides[require_external_atlas_api_enabled] = _external_rw_user
    try:
        with patch("bloom_lims.api.v1.beta_lab.BetaLabService", _FakeBetaLabService):
            patch_tube = client.patch(
                "/api/v1/external/atlas/beta/tubes/BCN-TUBE-1",
                json={
                    "status": "queued",
                    "properties": {"atlas_sync": "ok"},
                    "atlas_context": {"atlas_tenant_id": "tenant-1"},
                },
            )
            assert patch_tube.status_code == 200, patch_tube.text
            assert patch_tube.json()["container_euid"] == "BCN-TUBE-1"

            consume = client.post(
                "/api/v1/external/atlas/beta/materials/BCS-MAT-1/consume",
                headers={"Idempotency-Key": "idem-consume-route"},
                json={
                    "reason": "consumed for route coverage",
                    "metadata": {"operator": "pytest"},
                },
            )
            assert consume.status_code == 200, consume.text
            assert consume.json()["material_euid"] == "BCS-MAT-1"
    finally:
        app.dependency_overrides.pop(require_external_atlas_api_enabled, None)


def test_api_v1_graph_routes_execute_handler_body(client: TestClient) -> None:
    fake_bobj = SimpleNamespace()
    fake_db = SimpleNamespace()

    with patch("bloom_lims.api.v1.graph.BLOOMdb3", return_value=fake_db), patch(
        "bloom_lims.api.v1.graph.BloomObj", return_value=fake_bobj
    ), patch(
        "bloom_lims.api.v1.graph.build_graph_elements_for_start",
        return_value=(
            [{"data": {"id": "BCN-TEST-1", "category": "container"}}],
            [{"data": {"id": "LN-1", "source": "BCN-TEST-1", "target": "BCN-TEST-2"}}],
        ),
    ), patch(
        "bloom_lims.api.v1.graph.build_graph_object_payload",
        return_value={"euid": "BCN-TEST-1", "category": "container", "type": "instance"},
    ):
        graph = client.get("/api/v1/graph/data?start_euid=BCN-TEST-1&depth=3")
        assert graph.status_code == 200, graph.text
        assert graph.json()["meta"]["start_euid"] == "BCN-TEST-1"

        graph_object = client.get("/api/v1/graph/object/BCN-TEST-1")
        assert graph_object.status_code == 200, graph_object.text
        assert graph_object.json()["euid"] == "BCN-TEST-1"
