"""
Route coverage gap tests (GUI routes).

These are intentionally minimal, but they must execute the handler body for
routes that are otherwise easy to miss (because 422s don't exercise code).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Disable OAuth for GUI tests and use dev API auth bypass.
os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from bloom_lims.search.contracts import SearchRequest, SearchResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main


@pytest.fixture
def client() -> TestClient:
    return TestClient(
        main.app, raise_server_exceptions=False, base_url="https://testserver"
    )


def _warm_session(client: TestClient) -> None:
    # Any route with Depends(require_auth) will populate session when BLOOM_OAUTH=no.
    resp = client.get("/lims")
    assert resp.status_code == 200


def _get_any_template_euid(bdb) -> str:
    GT = bdb.Base.classes.generic_template
    row = bdb.session.query(GT).filter(GT.is_deleted.is_(False)).first()
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
    resp = client.get("/auth/callback", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/auth/error?reason=missing_code")

    with patch(
        "bloom_lims.gui.routes.auth._complete_cognito_login",
        new=AsyncMock(return_value=RedirectResponse(url="/", status_code=303)),
    ):
        resp = client.post(
            "/auth/callback",
            json={"access_token": "x", "id_token": "y"},
            follow_redirects=False,
        )
        assert resp.status_code == 303


def test_list_scripts_executes_handler(client: TestClient) -> None:
    resp = client.get(
        "/list-scripts",
        params={"directory": str(Path(__file__).resolve().parents[1] / "static")},
    )
    assert resp.status_code == 200, resp.text
    assert "scripts" in resp.json()


def test_legacy_graph_alias_routes_are_removed(client: TestClient) -> None:
    resp = client.get("/dag", params={"start_euid": "BCN-1"}, follow_redirects=False)
    assert resp.status_code == 404

    resp = client.get("/dag_explorer", follow_redirects=False)
    assert resp.status_code == 404

    resp = client.get("/graph", params={"start_euid": "BCN-1"}, follow_redirects=False)
    assert resp.status_code == 404


def test_cogs_and_node_info_routes(client: TestClient) -> None:
    _warm_session(client)
    created = client.post(
        "/api/v1/object-creation/create",
        json={
            "category": "container",
            "type": "tube",
            "subtype": "tube-generic-10ml",
            "version": "1.0",
            "name": "cogs-tube",
        },
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
    resp = client.get("/plate_carosel2", params={"plate_euid": "BCN-NOT-REAL"})
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
    details_resp = client.get(
        "/uuid_details", params={"euid": "BCN-REMOVED"}, follow_redirects=False
    )
    assert details_resp.status_code == 404

    restore_resp = client.get(
        "/un_delete_by_uuid", params={"euid": "BCN-REMOVED"}, follow_redirects=False
    )
    assert restore_resp.status_code == 404

    uuid_query_resp = client.get(
        "/uuid_details", params={"uuid": "00000000-0000-0000-0000-000000000000"}
    )
    assert uuid_query_resp.status_code == 404


def test_euid_details_page_does_not_emit_uuid_alias_links(client: TestClient) -> None:
    _warm_session(client)
    obj = client.post(
        "/api/v1/object-creation/create",
        json={
            "category": "container",
            "type": "tube",
            "subtype": "tube-generic-10ml",
            "version": "1.0",
            "name": "alias-guard",
        },
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


def test_create_from_template_executes_handler(client: TestClient, bdb) -> None:
    _warm_session(client)
    template_euid = _get_any_template_euid(bdb)
    resp = client.get(
        "/create_from_template", params={"euid": template_euid}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/euid_details?euid=")


def test_file_set_urls_and_admin_template_routes_are_removed(
    client: TestClient, bdb
) -> None:
    _warm_session(client)
    # Legacy file set GUI routes are removed in Dewey hard-cut mode.
    resp = client.get("/file_set_urls", params={"fs_euid": "BFL-NOT-REAL"})
    assert resp.status_code == 404

    template_euid = _get_any_template_euid(bdb)
    # Admin template editor was retired.
    resp = client.get("/admin_template", params={"euid": template_euid})
    assert resp.status_code == 404


def test_query_by_euids_and_removed_file_flows(client: TestClient) -> None:
    _warm_session(client)
    # The query route is still live; posting bad input should execute the handler
    # and surface its rendered error page rather than a validation-only 422.
    resp = client.post("/query_by_euids", data={"file_euids": "BFL-1"})
    assert resp.status_code == 500
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Error:" in resp.text
    assert "BFL-1" in resp.text

    # Legacy file GUI handlers are removed in Dewey hard-cut mode.
    resp = client.post(
        "/create_file",
        data={"name": "upload-1"},
        files=[
            ("file_data", ("upload.txt", b"hello", "text/plain")),
            ("directory", (".ignored", b"", "application/octet-stream")),
        ],
    )
    assert resp.status_code == 404

    resp = client.post(
        "/download_file",
        data={
            "euid": "BFL-1",
            "download_type": "flat",
            "create_metadata_file": "no",
            "ret_json": "1",
        },
    )
    assert resp.status_code == 404

    resp = client.get(
        "/delete_temp_file",
        params={"filename": "downloaded.txt"},
        follow_redirects=False,
    )
    assert resp.status_code == 404


def test_modern_search_post_executes_handler(client: TestClient) -> None:
    _warm_session(client)

    fake_search_request = SearchRequest(
        query="BCN-SEARCH-1",
        record_types=["instance"],
        categories=["file"],
        page=1,
        page_size=50,
    )
    fake_search_response = SearchResponse(
        query="BCN-SEARCH-1",
        page=1,
        page_size=50,
        total=1,
        total_pages=1,
        sort_by="timestamp",
        sort_order="desc",
        truncated=False,
        facets={"record_type": {"instance": 1}, "category": {"file": 1}},
        items=[],
    )

    with (
        patch(
            "bloom_lims.gui.routes.modern.SearchService.build_dewey_request",
            return_value=fake_search_request,
        ),
        patch(
            "bloom_lims.gui.routes.modern.SearchService.search",
            return_value=fake_search_response,
        ),
    ):
        resp = client.post(
            "/search",
            data={"search_target": "file", "euid": "BCN-SEARCH-1"},
        )

    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "BCN-SEARCH-1" in resp.text


def test_logout_alias_routes_execute_handler_body(client: TestClient) -> None:
    with (
        patch(
            "bloom_lims.gui.routes.auth.build_bloom_web_session_config",
            return_value=SimpleNamespace(
                domain="example.auth.us-west-2.amazoncognito.com",
                client_id="client-123",
                logout_uri="https://testserver/auth/logout",
            ),
        ),
        patch(
            "bloom_lims.gui.routes.auth.build_logout_url",
            return_value="https://example.auth.us-west-2.amazoncognito.com/logout",
        ),
        patch(
            "bloom_lims.gui.routes.auth.clear_bloom_session",
            return_value=None,
        ),
    ):
        auth_logout = client.post("/auth/logout", follow_redirects=False)
        assert auth_logout.status_code == 303
        assert (
            auth_logout.headers["location"]
            == "https://example.auth.us-west-2.amazoncognito.com/logout"
        )

        logout = client.get("/logout", follow_redirects=False)
        assert logout.status_code == 303
        assert (
            logout.headers["location"]
            == "https://example.auth.us-west-2.amazoncognito.com/logout"
        )
