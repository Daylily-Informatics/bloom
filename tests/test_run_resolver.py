"""Focused tests for Bloom's beta run resolver surface."""

from __future__ import annotations

import os
import secrets
import sys

import pytest
from fastapi.testclient import TestClient

from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth
from bloom_lims.auth.rbac import ENABLE_ATLAS_API_GROUP, ENABLE_URSA_API_GROUP

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _external_rw_user() -> APIUser:
    token = secrets.token_hex(8)
    return APIUser(
        email="beta-resolver@example.com",
        user_id=f"user-{token}",
        roles=["READ_WRITE"],
        groups=[ENABLE_ATLAS_API_GROUP, ENABLE_URSA_API_GROUP],
        auth_source="token",
        is_service_account=True,
        token_scope="internal_rw",
        token_id=f"token-{token}",
    )


def _opaque(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def _seed_beta_run(client: TestClient) -> tuple[str, str]:
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
    specimen = client.post(
        "/api/v1/external/atlas/beta/materials",
        headers={"Idempotency-Key": _opaque("idem-material")},
        json={"specimen_name": "resolver-specimen", "atlas_context": atlas_context},
    )
    assert specimen.status_code == 200, specimen.text
    specimen_payload = specimen.json()
    specimen_euid = specimen_payload["specimen_euid"]
    container_euid = specimen_payload["container_euid"]

    queued = client.post(
        f"/api/v1/external/atlas/beta/queues/extraction_rnd/items/{container_euid}",
        headers={"Idempotency-Key": _opaque("idem-queue")},
        json={"metadata": {"queue": "resolver"}},
    )
    assert queued.status_code == 200, queued.text

    extraction = client.post(
        "/api/v1/external/atlas/beta/extractions",
        headers={"Idempotency-Key": _opaque("idem-extract")},
        json={
            "source_specimen_euid": specimen_euid,
            "well_name": "A1",
            "extraction_type": "gdna",
            "atlas_test_fulfillment_item_euid": atlas_context["fulfillment_items"][0]["atlas_test_fulfillment_item_euid"],
        },
    )
    assert extraction.status_code == 200, extraction.text
    extraction_output_euid = extraction.json()["extraction_output_euid"]

    qc = client.post(
        "/api/v1/external/atlas/beta/post-extract-qc",
        headers={"Idempotency-Key": _opaque("idem-qc")},
        json={
            "extraction_output_euid": extraction_output_euid,
            "passed": True,
            "next_queue": "ont_lib_prep",
        },
    )
    assert qc.status_code == 200, qc.text

    lib_prep = client.post(
        "/api/v1/external/atlas/beta/library-prep",
        headers={"Idempotency-Key": _opaque("idem-libprep")},
        json={
            "source_extraction_output_euid": extraction_output_euid,
            "platform": "ONT",
        },
    )
    assert lib_prep.status_code == 200, lib_prep.text
    lib_output_euid = lib_prep.json()["library_prep_output_euid"]

    pool = client.post(
        "/api/v1/external/atlas/beta/pools",
        headers={"Idempotency-Key": _opaque("idem-pool")},
        json={
            "member_euids": [lib_output_euid],
            "platform": "ONT",
        },
    )
    assert pool.status_code == 200, pool.text
    pool_euid = pool.json()["pool_euid"]

    run = client.post(
        "/api/v1/external/atlas/beta/runs",
        headers={"Idempotency-Key": _opaque("idem-run")},
        json={
            "pool_euid": pool_euid,
            "platform": "ONT",
            "flowcell_id": "FLOW-ONT-01",
            "status": "started",
            "assignments": [
                {
                    "lane": "2",
                    "library_barcode": "ONT-IDX-01",
                    "library_prep_output_euid": lib_output_euid,
                }
            ],
        },
    )
    assert run.status_code == 200, run.text
    return run.json()["run_euid"], atlas_context["fulfillment_items"][0]["atlas_test_fulfillment_item_euid"]


def test_run_resolver_returns_404_for_unknown_index():
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    with TestClient(app) as client:
        run_euid, expected_fulfillment_item = _seed_beta_run(client)

        missing = client.get(
            f"/api/v1/external/atlas/beta/runs/{run_euid}/resolve",
            params={
                "flowcell_id": "FLOW-ONT-01",
                "lane": "2",
                "library_barcode": "DOES-NOT-EXIST",
            },
        )
        assert missing.status_code == 404, missing.text

        resolved = client.get(
            f"/api/v1/external/atlas/beta/runs/{run_euid}/resolve",
            params={
                "flowcell_id": "FLOW-ONT-01",
                "lane": "2",
                "library_barcode": "ONT-IDX-01",
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["atlas_test_fulfillment_item_euid"] == expected_fulfillment_item
