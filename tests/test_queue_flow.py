"""End-to-end tests for Bloom's beta queue-driven lab flow."""

from __future__ import annotations

import os
import secrets
import sys

import pytest
from fastapi.testclient import TestClient

from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth

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
        email="beta-queue@example.com",
        user_id=f"user-{token}",
        roles=["INTERNAL_READ_WRITE"],
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


def test_beta_queue_flow_end_to_end():
    app.dependency_overrides[require_external_token_auth] = _external_rw_user

    atlas_refs = {
        "atlas_tenant_id": _opaque("tenant"),
        "atlas_order_euid": _opaque("order"),
        "atlas_test_order_euid": _opaque("trftest"),
    }
    material_idem = _opaque("idem-material")

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": material_idem},
            json={
                "specimen_name": "beta-whole-blood",
                "properties": {"source": "pytest-beta-queue"},
                "atlas_refs": atlas_refs,
            },
        )
        assert created.status_code == 200, created.text
        material = created.json()
        _assert_no_uuid_keys(material)
        assert material["created"] is True
        assert material["current_queue"] is None
        assert (
            material["atlas_refs"]["atlas_test_order_euid"]
            == atlas_refs["atlas_test_order_euid"]
        )

        replay = client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": material_idem},
            json={
                "specimen_name": "beta-whole-blood",
                "properties": {"source": "pytest-beta-queue"},
                "atlas_refs": atlas_refs,
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["created"] is False

        specimen_euid = material["specimen_euid"]

        by_ref = client.get(
            "/api/v1/external/specimens/by-reference",
            params={"atlas_test_order_euid": atlas_refs["atlas_test_order_euid"]},
        )
        assert by_ref.status_code == 200, by_ref.text
        assert by_ref.json()["total"] >= 1

        queued = client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{specimen_euid}",
            headers={"Idempotency-Key": _opaque("idem-queue")},
            json={"metadata": {"reason": "accepted-material"}},
        )
        assert queued.status_code == 200, queued.text
        queue_body = queued.json()
        _assert_no_uuid_keys(queue_body)
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
                "metadata": {"operator": "pytest"},
            },
        )
        assert extraction.status_code == 200, extraction.text
        extraction_body = extraction.json()
        _assert_no_uuid_keys(extraction_body)
        assert extraction_body["current_queue"] == "post_extract_qc"
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
        lib_output_euid = library_body["library_prep_output_euid"]

        pool = client.post(
            "/api/v1/external/atlas/beta/pools",
            headers={"Idempotency-Key": _opaque("idem-pool")},
            json={
                "member_euids": [lib_output_euid],
                "platform": "ILMN",
                "pool_name": "beta-seq-pool",
                "metadata": {"pool_strategy": "singleplex"},
            },
        )
        assert pool.status_code == 200, pool.text
        pool_body = pool.json()
        assert pool_body["current_queue"] == "ilmn_start_seq_run"
        pool_euid = pool_body["pool_euid"]

        index_string = "IDX-ILMN-A1"
        run = client.post(
            "/api/v1/external/atlas/beta/runs",
            headers={"Idempotency-Key": _opaque("idem-run")},
            json={
                "pool_euid": pool_euid,
                "platform": "ILMN",
                "run_name": "beta-ilmn-run",
                "status": "completed",
                "index_mappings": [
                    {
                        "index_string": index_string,
                        "source_euid": lib_output_euid,
                    }
                ],
                "artifacts": [
                    {
                        "artifact_type": "fastq",
                        "bucket": "beta-runs",
                        "filename": "reads_R1.fastq.gz",
                        "index_string": index_string,
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
        assert run_body["mapping_count"] == 1
        assert run_body["run_folder"] == f"{run_body['run_euid']}/"

        resolved = client.get(
            f"/api/v1/external/atlas/beta/runs/{run_body['run_euid']}/resolve",
            params={"index_string": index_string},
        )
        assert resolved.status_code == 200, resolved.text
        resolved_body = resolved.json()
        _assert_no_uuid_keys(resolved_body)
        assert resolved_body["atlas_tenant_id"] == atlas_refs["atlas_tenant_id"]
        assert resolved_body["atlas_order_euid"] == atlas_refs["atlas_order_euid"]
        assert (
            resolved_body["atlas_test_order_euid"]
            == atlas_refs["atlas_test_order_euid"]
        )
