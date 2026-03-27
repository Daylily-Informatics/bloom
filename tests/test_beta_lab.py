"""Focused tests for beta lab route guards and resolver contract."""

from __future__ import annotations

import asyncio
import os
import secrets
import sys

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from bloom_lims.api.v1.beta_lab import require_external_ursa_read
from bloom_lims.api.v1.dependencies import (
    APIUser,
    require_external_token_auth,
    require_external_ursa_api_enabled,
)
from bloom_lims.auth.rbac import ENABLE_ATLAS_API_GROUP, ENABLE_URSA_API_GROUP
from bloom_lims.bobjs import BloomObj
from bloom_lims.db import get_parent_lineages

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


def _token_user(groups: list[str]) -> APIUser:
    return APIUser(
        email="token-user@example.com",
        user_id="token-user",
        roles=["INTERNAL_READ_ONLY"],
        groups=groups,
        auth_source="token",
    )


def test_require_external_ursa_api_enabled_rejects_missing_group():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_external_ursa_api_enabled(_token_user(groups=[])))
    assert exc.value.status_code == 403
    assert "ENABLE_URSA_API" in str(exc.value.detail)


def test_require_external_ursa_api_enabled_allows_group_member():
    user = _token_user(groups=[ENABLE_URSA_API_GROUP])
    resolved = asyncio.run(require_external_ursa_api_enabled(user))
    assert resolved.user_id == "token-user"


def test_run_resolver_requires_full_key_query_params():
    client = TestClient(app)
    app.dependency_overrides[require_external_ursa_read] = lambda: APIUser(
        email="resolver-user@example.com",
        user_id="resolver-user",
        roles=["INTERNAL_READ_ONLY"],
        groups=[ENABLE_URSA_API_GROUP],
        auth_source="token",
    )
    try:
        response = client.get("/api/v1/external/atlas/beta/runs/RUN-1/resolve")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(require_external_ursa_read, None)


def test_material_registration_links_fulfillment_items_on_container_and_patient_on_specimen(bdb):
    def _atlas_rw_user() -> APIUser:
        token = secrets.token_hex(8)
        return APIUser(
            email="atlas-beta@example.com",
            user_id=f"atlas-user-{token}",
            roles=["INTERNAL_READ_WRITE"],
            groups=[ENABLE_ATLAS_API_GROUP],
            auth_source="token",
            is_service_account=True,
            token_scope="internal_rw",
            token_id=f"token-{token}",
        )

    def _atlas_refs(instance):
        refs: list[dict] = []
        for lineage in get_parent_lineages(instance):
            if lineage.is_deleted or lineage.relationship_type != "has_external_reference":
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            payload = child.json_addl or {}
            props = payload.get("properties") if isinstance(payload, dict) else {}
            if not isinstance(props, dict):
                continue
            if str(props.get("provider") or "").strip() != "atlas":
                continue
            refs.append(props)
        return refs

    app.dependency_overrides[require_external_token_auth] = _atlas_rw_user
    client = TestClient(app)
    try:
        atlas_context = {
            "atlas_tenant_id": f"tenant-{secrets.token_hex(8)}",
            "atlas_trf_euid": f"trf-{secrets.token_hex(8)}",
            "atlas_patient_euid": f"patient-{secrets.token_hex(8)}",
            "atlas_testkit_euid": f"kit-{secrets.token_hex(8)}",
            "atlas_shipment_euid": f"shipment-{secrets.token_hex(8)}",
            "atlas_organization_site_euid": f"site-{secrets.token_hex(8)}",
            "fulfillment_items": [
                {
                    "atlas_test_euid": f"test-{secrets.token_hex(8)}",
                    "atlas_test_fulfillment_item_euid": f"proc-{secrets.token_hex(8)}",
                }
            ],
        }
        material = client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": f"idem-material-{secrets.token_hex(8)}"},
            json={"specimen_name": "container-first-link-check", "atlas_context": atlas_context},
        )
        assert material.status_code == 200, material.text
        material_body = material.json()
        specimen_euid = material_body["specimen_euid"]
        container_euid = material_body["container_euid"]
        assert material_body["atlas_context"]["atlas_testkit_euid"] == atlas_context["atlas_testkit_euid"]
        assert material_body["atlas_context"]["atlas_shipment_euid"] == atlas_context["atlas_shipment_euid"]
        assert (
            material_body["atlas_context"]["atlas_organization_site_euid"]
            == atlas_context["atlas_organization_site_euid"]
        )

        bobj = BloomObj(bdb)
        specimen = bobj.get_by_euid(specimen_euid)
        container = bobj.get_by_euid(container_euid)
        assert container.created_dt <= specimen.created_dt

        specimen_refs = _atlas_refs(specimen)
        container_refs = _atlas_refs(container)
        assert any(
            str(ref.get("reference_type")) == "atlas_patient"
            and str(ref.get("atlas_patient_euid")) == atlas_context["atlas_patient_euid"]
            for ref in specimen_refs
        )
        assert not any(
            str(ref.get("reference_type")) == "atlas_test_process_item"
            for ref in specimen_refs
        )
        assert any(
            str(ref.get("reference_type")) == "atlas_test_process_item"
            and str(ref.get("atlas_test_fulfillment_item_euid"))
            == atlas_context["fulfillment_items"][0]["atlas_test_fulfillment_item_euid"]
            for ref in container_refs
        )
        assert any(
            str(ref.get("reference_type")) == "atlas_trf"
            and str(ref.get("atlas_trf_euid")) == atlas_context["atlas_trf_euid"]
            for ref in container_refs
        )
        assert any(
            str(ref.get("reference_type")) == "atlas_testkit"
            and str(ref.get("atlas_testkit_euid")) == atlas_context["atlas_testkit_euid"]
            for ref in container_refs
        )
        assert any(
            str(ref.get("reference_type")) == "atlas_shipment"
            and str(ref.get("atlas_shipment_euid")) == atlas_context["atlas_shipment_euid"]
            for ref in container_refs
        )
        assert any(
            str(ref.get("reference_type")) == "atlas_organization_site"
            and str(ref.get("atlas_organization_site_euid"))
            == atlas_context["atlas_organization_site_euid"]
            for ref in container_refs
        )

        queued = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{container_euid}",
            headers={"Idempotency-Key": f"idem-queue-{secrets.token_hex(8)}"},
            json={"metadata": {"source": "test_beta_lab"}},
        )
        assert queued.status_code == 200, queued.text
        extraction = client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": f"idem-extract-{secrets.token_hex(8)}"},
            json={
                "source_specimen_euid": specimen_euid,
                "well_name": "A1",
                "extraction_type": "gdna",
                "atlas_test_fulfillment_item_euid": atlas_context["fulfillment_items"][0][
                    "atlas_test_fulfillment_item_euid"
                ],
            },
        )
        assert extraction.status_code == 200, extraction.text
    finally:
        client.close()
        app.dependency_overrides.pop(require_external_token_auth, None)


def test_empty_tube_create_and_specimen_update_use_collection_event_reference(bdb):
    def _atlas_rw_user() -> APIUser:
        token = secrets.token_hex(8)
        return APIUser(
            email="atlas-beta@example.com",
            user_id=f"atlas-user-{token}",
            roles=["INTERNAL_READ_WRITE"],
            groups=[ENABLE_ATLAS_API_GROUP],
            auth_source="token",
            is_service_account=True,
            token_scope="internal_rw",
            token_id=f"token-{token}",
        )

    def _atlas_refs(instance):
        refs: list[dict] = []
        for lineage in get_parent_lineages(instance):
            if lineage.is_deleted or lineage.relationship_type != "has_external_reference":
                continue
            child = lineage.child_instance
            if child is None or child.is_deleted:
                continue
            payload = child.json_addl or {}
            props = payload.get("properties") if isinstance(payload, dict) else {}
            if not isinstance(props, dict):
                continue
            if str(props.get("provider") or "").strip() != "atlas":
                continue
            refs.append(props)
        return refs

    app.dependency_overrides[require_external_token_auth] = _atlas_rw_user
    client = TestClient(app)
    try:
        tenant_id = f"tenant-{secrets.token_hex(8)}"
        shipment_euid = f"shipment-{secrets.token_hex(8)}"
        testkit_euid = f"kit-{secrets.token_hex(8)}"
        site_euid = f"site-{secrets.token_hex(8)}"
        create_tube = client.post(
            "/api/v1/external/atlas/beta/tubes",
            headers={"Idempotency-Key": f"idem-tube-{secrets.token_hex(8)}"},
            json={
                "atlas_context": {
                    "atlas_tenant_id": tenant_id,
                    "atlas_shipment_euid": shipment_euid,
                    "atlas_testkit_euid": testkit_euid,
                    "atlas_organization_site_euid": site_euid,
                }
            },
        )
        assert create_tube.status_code == 200, create_tube.text
        tube_body = create_tube.json()
        container_euid = tube_body["container_euid"]

        collection_event_euid = f"cev-{secrets.token_hex(8)}"
        specimen_resp = client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": f"idem-specimen-{secrets.token_hex(8)}"},
            json={
                "container_euid": container_euid,
                "atlas_context": {
                    "atlas_tenant_id": tenant_id,
                    "atlas_shipment_euid": shipment_euid,
                    "atlas_testkit_euid": testkit_euid,
                    "atlas_organization_site_euid": site_euid,
                    "atlas_collection_event_euid": collection_event_euid,
                    "collection_event_snapshot": {
                        "collection_event_euid": collection_event_euid,
                        "collection_type": "venipuncture",
                    },
                },
            },
        )
        assert specimen_resp.status_code == 200, specimen_resp.text
        specimen_body = specimen_resp.json()

        bobj = BloomObj(bdb)
        container = bobj.get_by_euid(container_euid)
        specimen = bobj.get_by_euid(specimen_body["specimen_euid"])

        container_refs = _atlas_refs(container)
        specimen_refs = _atlas_refs(specimen)
        assert any(
            str(ref.get("reference_type")) == "atlas_shipment"
            and str(ref.get("atlas_shipment_euid")) == shipment_euid
            for ref in container_refs
        )
        assert any(
            str(ref.get("reference_type")) == "atlas_testkit"
            and str(ref.get("atlas_testkit_euid")) == testkit_euid
            for ref in container_refs
        )
        assert any(
            str(ref.get("reference_type")) == "atlas_collection_event"
            and str(ref.get("atlas_collection_event_euid")) == collection_event_euid
            and str(ref.get("collection_event_snapshot", {}).get("collection_type")) == "venipuncture"
            for ref in specimen_refs
        )
        assert not any(str(ref.get("reference_type")) == "atlas_patient" for ref in specimen_refs)

        patched = client.patch(
            f"/api/v1/external/atlas/beta/specimens/{specimen_body['specimen_euid']}",
            json={
                "atlas_context": {
                    "atlas_tenant_id": tenant_id,
                    "atlas_collection_event_euid": collection_event_euid,
                    "collection_event_snapshot": {
                        "collection_event_euid": collection_event_euid,
                        "collection_type": "fingerstick",
                        "expected_name": "Pat Ient",
                    },
                }
            },
        )
        assert patched.status_code == 200, patched.text

        updated_specimen_refs = _atlas_refs(bobj.get_by_euid(specimen_body["specimen_euid"]))
        assert any(
            str(ref.get("reference_type")) == "atlas_collection_event"
            and str(ref.get("collection_event_snapshot", {}).get("collection_type")) == "fingerstick"
            and str(ref.get("collection_event_snapshot", {}).get("expected_name")) == "Pat Ient"
            for ref in updated_specimen_refs
        )
        assert not any(
            str(ref.get("reference_type")) == "atlas_patient" for ref in updated_specimen_refs
        )
    finally:
        client.close()
        app.dependency_overrides.pop(require_external_token_auth, None)
