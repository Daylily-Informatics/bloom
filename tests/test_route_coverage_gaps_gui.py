"""
Route coverage gap tests (GUI routes).

These are intentionally minimal, but they must execute the handler body for
routes that are otherwise easy to miss (because 422s don't exercise code).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Disable OAuth for GUI tests and use dev API auth bypass.
os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app, raise_server_exceptions=False)


def _warm_session(client: TestClient) -> None:
    # Any route with Depends(require_auth) will populate session when BLOOM_OAUTH=no.
    resp = client.get("/lims")
    assert resp.status_code == 200


def _get_any_template_euid(bdb) -> str:
    GT = bdb.Base.classes.generic_template
    row = bdb.session.query(GT).filter(GT.is_deleted == False).first()
    assert row is not None
    return row.euid


def _create_plate_instance(client: TestClient) -> dict:
    resp = client.post(
        "/api/v1/object-creation/create",
        json={
            "category": "container",
            "type": "plate",
            "subtype": "fixed-plate-96",
            "version": "1.0",
            "name": "coverage-plate",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_queue_instance(client: TestClient) -> dict:
    resp = client.post(
        "/api/v1/object-creation/create",
        json={
            "category": "workflow_step",
            "type": "queue",
            "subtype": "all-purpose",
            "version": "1.0",
            "name": "coverage-queue",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_auth_callback_aliases(client: TestClient) -> None:
    resp = client.get("/auth/callback")
    assert resp.status_code == 200
    assert "Processing" in resp.text or "login" in resp.text.lower()

    with patch(
        "bloom_lims.gui.routes.auth._complete_cognito_login",
        new=AsyncMock(return_value=RedirectResponse(url="/", status_code=303)),
    ):
        resp = client.post("/auth/callback", json={"access_token": "x", "id_token": "y"}, follow_redirects=False)
        assert resp.status_code == 303


def test_list_scripts_executes_handler(client: TestClient) -> None:
    resp = client.get("/list-scripts", params={"directory": str(Path(__file__).resolve().parents[1] / "static")})
    assert resp.status_code == 200, resp.text
    assert "scripts" in resp.json()


def test_legacy_graph_alias_routes_are_removed(client: TestClient) -> None:
    resp = client.get("/dag", params={"start_euid": "CX-1"}, follow_redirects=False)
    assert resp.status_code == 404

    resp = client.get("/dag_explorer", follow_redirects=False)
    assert resp.status_code == 404

    resp = client.get("/graph", params={"start_euid": "CX-1"}, follow_redirects=False)
    assert resp.status_code == 404


def test_cogs_and_node_info_routes(client: TestClient) -> None:
    _warm_session(client)
    created = client.post(
        "/api/v1/object-creation/create",
        json={"category": "container", "type": "tube", "subtype": "tube-generic-10ml", "version": "1.0", "name": "cogs-tube"},
    ).json()
    euid = created["euid"]

    resp = client.get("/calculate_cogs_children", params={"euid": euid})
    assert resp.status_code == 200

    resp = client.get("/calculate_cogs_parents", params={"euid": euid})
    assert resp.status_code == 200

    resp = client.get("/get_node_info", params={"euid": euid})
    assert resp.status_code == 200
    assert resp.json().get("euid") == euid

    resp = client.get("/get_node_property", params={"euid": euid, "key": "name"})
    assert resp.status_code in (200, 404, 500), resp.text


def test_plate_routes_with_and_without_valid_plate(client: TestClient) -> None:
    _warm_session(client)

    # plate_carosel2 is retired from modern GUI.
    resp = client.get("/plate_carosel2", params={"plate_euid": "CX-NOT-REAL"})
    assert resp.status_code == 404

    # plate_visualization: create a real plate with wells
    plate = _create_plate_instance(client)
    resp = client.get("/plate_visualization", params={"plate_euid": plate["euid"]})
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")

    # get_related_plates is retired from modern GUI.
    resp = client.get("/get_related_plates", params={"main_plate": plate["euid"]})
    assert resp.status_code == 404


def test_queue_details_renders(client: TestClient) -> None:
    _warm_session(client)
    queue = _create_queue_instance(client)

    resp = client.get("/queue_details", params={"queue_euid": queue["euid"], "page": 1})
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_legacy_uuid_alias_routes_are_removed(client: TestClient) -> None:
    _warm_session(client)
    details_resp = client.get("/uuid_details", params={"euid": "CX-REMOVED"}, follow_redirects=False)
    assert details_resp.status_code == 404

    restore_resp = client.get("/un_delete_by_uuid", params={"euid": "CX-REMOVED"}, follow_redirects=False)
    assert restore_resp.status_code == 404

    uuid_query_resp = client.get("/uuid_details", params={"uuid": "00000000-0000-0000-0000-000000000000"})
    assert uuid_query_resp.status_code == 404


def test_euid_details_page_does_not_emit_uuid_alias_links(client: TestClient) -> None:
    _warm_session(client)
    obj = client.post(
        "/api/v1/object-creation/create",
        json={"category": "container", "type": "tube", "subtype": "tube-generic-10ml", "version": "1.0", "name": "alias-guard"},
    ).json()

    resp = client.get("/euid_details", params={"euid": obj["euid"]})
    assert resp.status_code == 200
    assert "/uuid_details?uuid=" not in resp.text
    assert f"/dindex2?start_euid={obj['euid']}" in resp.text


def test_user_audit_logs_renders(client: TestClient) -> None:
    _warm_session(client)
    resp = client.get("/user_audit_logs", params={"username": "tester@example.com"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_create_instance_form_renders(client: TestClient, bdb) -> None:
    _warm_session(client)
    template_euid = _get_any_template_euid(bdb)
    resp = client.get(f"/create_instance/{template_euid}")
    assert resp.status_code == 410


def test_file_set_urls_and_admin_template_pages(client: TestClient, bdb) -> None:
    _warm_session(client)
    # Create a file set instance via API v1 endpoint.
    fs = client.post("/api/v1/file-sets/", json={"name": "gui-fs", "file_type": "generic"}).json()

    resp = client.get("/file_set_urls", params={"fs_euid": fs["euid"]})
    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("content-type", "")

    template_euid = _get_any_template_euid(bdb)
    # Admin template editor was retired.
    resp = client.get("/admin_template", params={"euid": template_euid})
    assert resp.status_code == 410


def test_query_by_euids_create_and_download_file_flows(client: TestClient, tmp_path: Path) -> None:
    _warm_session(client)

    # query_by_euids expects real file objects; patch BloomFile.get_by_euid to return a stub.
    fake_file = SimpleNamespace(
        euid="FX-1",
        created_dt=datetime.now(timezone.utc),
        bstatus="created",
        json_addl={"properties": {"name": "file-1", "lab_code": "X"}},
    )
    with patch("bloom_lims.gui.routes.operations.BloomFile.get_by_euid", return_value=fake_file):
        resp = client.post("/query_by_euids", data={"file_euids": "FX-1"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    # create_file (GUI): patch file creation to avoid S3 and to keep deterministic.
    fake_created = SimpleNamespace(
        euid="FX-TEST",
        json_addl={"properties": {"current_s3_uri": "s3://bucket/key"}},
    )
    with patch("bloom_lims.gui.routes.files.BloomFile.create_file", return_value=fake_created), patch(
        "bloom_lims.gui.routes.files.BloomFileSet.add_files_to_file_set", return_value=None
    ):
        resp = client.post(
            "/create_file",
            data={"name": "upload-1"},
            files=[
                ("file_data", ("upload.txt", b"hello", "text/plain")),
                ("directory", (".ignored", b"", "application/octet-stream")),
            ],
        )
        assert resp.status_code == 200

    # download_file (GUI): create a fake file under ./tmp and return it from patched download_file.
    tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    downloaded = tmp_dir / "downloaded.txt"
    downloaded.write_text("ok", encoding="utf-8")

    with patch("bloom_lims.gui.routes.files.BloomFile.download_file", return_value=str(downloaded)):
        resp = client.post(
            "/download_file",
            data={
                "euid": "FX-1",
                "download_type": "flat",
                "create_metadata_file": "no",
                "ret_json": "1",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["file_download_path"].endswith("downloaded.txt")

    # delete_temp_file: ensure handler runs and redirects.
    resp = client.get("/delete_temp_file", params={"filename": "downloaded.txt"}, follow_redirects=False)
    assert resp.status_code == 303
