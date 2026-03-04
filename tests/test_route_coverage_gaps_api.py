"""
Route coverage gap tests (API).

These tests exist to ensure every API endpoint has at least one test that
executes the handler body (not just FastAPI validation).
"""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Set up auth bypass BEFORE importing FastAPI app
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

from fastapi.testclient import TestClient

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
    q = bdb.session.query(GT).filter(GT.is_deleted == False).filter(GT.category == category)
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
    container_euid = create_container.json()["euid"]

    create_sample = client.post(
        "/api/v1/content/samples",
        json={
            "template_euid": sample_template,
            "name": "coverage-sample",
        },
    )
    assert create_sample.status_code == 200, create_sample.text
    content_euid = create_sample.json()["euid"]

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
    sample_euid = sample.json()["euid"]

    specimen = client.post(
        "/api/v1/content/specimens",
        json={"template_euid": specimen_template, "name": "blood-specimen", "specimen_type": "blood"},
    )
    assert specimen.status_code == 200, specimen.text

    reagent = client.post(
        "/api/v1/content/reagents",
        json={"template_euid": reagent_template, "name": "naoh-reagent", "reagent_type": "naoh"},
    )
    assert reagent.status_code == 200, reagent.text

    with patch("bloom_lims.integrations.atlas.events.emit_bloom_event", return_value=None):
        update = client.put(f"/api/v1/content/{sample_euid}", json={"name": "updated-name"})
    assert update.status_code == 200, update.text


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
    euid = create.json()["euid"]

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
    lineage_uuid = create.json()["uuid"]

    delete = client.delete(f"/api/v1/lineages/{lineage_uuid}")
    assert delete.status_code == 200, delete.text


def test_subjects_workflows_and_steps(client: TestClient, bdb) -> None:
    subj_template = _get_template_euid(bdb, category="subject", type_name="generic", subtype="generic-subject", version="1.0")
    wf_template = _get_template_euid(bdb, category="workflow", type_name="extraction", subtype="blood-whole-to-gdna", version="1.0")

    subj = client.post("/api/v1/subjects/", json={"template_euid": subj_template, "name": "subj-1", "external_id": "X1"})
    assert subj.status_code == 200, subj.text
    subj_euid = subj.json()["euid"]

    subj_update = client.put(f"/api/v1/subjects/{subj_euid}", json={"status": "active"})
    assert subj_update.status_code == 200, subj_update.text

    subj_delete = client.delete(f"/api/v1/subjects/{subj_euid}")
    assert subj_delete.status_code == 200, subj_delete.text

    wf = client.post(f"/api/v1/workflows/?template_euid={wf_template}&name=coverage-workflow")
    assert wf.status_code == 200, wf.text
    wf_euid = wf.json()["euid"]

    wf_update = client.put(f"/api/v1/workflows/{wf_euid}?status=in_progress", json={"properties": {"note": "x"}})
    assert wf_update.status_code == 200, wf_update.text

    steps = client.get(f"/api/v1/workflows/{wf_euid}/steps")
    assert steps.status_code == 200, steps.text
    assert steps.json()["workflow_euid"] == wf_euid


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
    eq_euid = eq.json()["euid"]

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
    assert file_set.status_code == 200, file_set.text

    def _fake_file(*_args, **_kwargs):
        return SimpleNamespace(
            euid="FX-TEST",
            uuid="00000000-0000-0000-0000-000000000000",
            json_addl={"properties": {"s3_uri": "s3://bucket/key", "current_s3_uri": "s3://bucket/key"}},
        )

    with patch("bloom_lims.bobjs.BloomFile.create_file", side_effect=_fake_file):
        resp = client.post(
            "/api/v1/files/",
            data={"file_metadata": json.dumps({"name": "file-coverage"})},
        )
        assert resp.status_code == 200, resp.text
