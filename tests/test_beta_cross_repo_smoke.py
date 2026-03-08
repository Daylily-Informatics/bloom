"""Cross-repo beta smoke flow across Atlas, Bloom, and Ursa HTTP contracts."""

# ruff: noqa: E402, I001

from __future__ import annotations

import os
import secrets
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
ATLAS_ROOT = WORKSPACE_ROOT / "lsmc-atlas"
URSA_ROOT = WORKSPACE_ROOT / "daylily-ursa"
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{WORKSPACE_ROOT / '_refactor' / 'atlas_beta_smoke.sqlite'}",
)
for root in (ATLAS_ROOT, URSA_ROOT):
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth
from bloom_lims.app import create_app as create_bloom_app
from daylib.analysis_store import (  # noqa: E402
    AnalysisArtifact,
    AnalysisRecord,
    AnalysisState,
    ReviewState,
    RunResolution,
)
from daylib.atlas_result_client import AtlasResultClient  # noqa: E402
from daylib.bloom_resolver_client import BloomResolverClient  # noqa: E402
from daylib.config import Settings  # noqa: E402
from daylib.workset_api import create_app as create_ursa_app  # noqa: E402

import app.api.routes.intake as atlas_intake_routes  # noqa: E402
import app.api.routes.ursa_integration as atlas_ursa_routes  # noqa: E402
from app.api.routes.internal import verify_internal_api_key  # noqa: E402
from app.auth.dependencies import (  # noqa: E402
    CurrentUser,
    get_current_user,
    require_internal,
)
from app.db.engine import get_db  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_bloom_auth_env():
    os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
    yield


def _opaque(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def _assert_no_uuid_keys(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert "uuid" not in str(key).lower()
            _assert_no_uuid_keys(value)
        return
    if isinstance(payload, list):
        for item in payload:
            _assert_no_uuid_keys(item)


def _external_rw_user() -> APIUser:
    token = secrets.token_hex(8)
    return APIUser(
        email="beta-smoke@example.com",
        user_id=f"user-{token}",
        roles=["INTERNAL_READ_WRITE"],
        auth_source="token",
        is_service_account=True,
        token_scope="internal_rw",
        token_id=f"token-{token}",
    )


class SmokeAnalysisStore:
    def __init__(self) -> None:
        self.record: AnalysisRecord | None = None

    def ingest_analysis(self, **kwargs):
        resolution: RunResolution = kwargs["resolution"]
        now = "2026-03-07T00:00:00Z"
        if self.record is None:
            self.record = AnalysisRecord(
                analysis_euid=_opaque("analysis"),
                run_euid=resolution.run_euid,
                index_string=resolution.index_string,
                atlas_tenant_id=resolution.atlas_tenant_id,
                atlas_order_euid=resolution.atlas_order_euid,
                atlas_test_order_euid=resolution.atlas_test_order_euid,
                source_euid=resolution.source_euid,
                analysis_type=kwargs["analysis_type"],
                state=AnalysisState.INGESTED.value,
                review_state=ReviewState.PENDING.value,
                result_status="PENDING",
                run_folder=f"s3://{kwargs['artifact_bucket']}/{resolution.run_euid}/",
                artifact_bucket=kwargs["artifact_bucket"],
                result_payload={},
                metadata=dict(kwargs.get("metadata") or {}),
                created_at=now,
                updated_at=now,
                atlas_return={},
                artifacts=[],
            )
        return self.record

    def get_analysis(self, analysis_euid: str):
        if self.record is None or self.record.analysis_euid != analysis_euid:
            return None
        return self.record

    def update_analysis_state(self, analysis_euid: str, **kwargs):
        assert self.record is not None
        assert self.record.analysis_euid == analysis_euid
        self.record = replace(
            self.record,
            state=kwargs["state"].value,
            result_status=kwargs.get("result_status") or self.record.result_status,
            result_payload=kwargs.get("result_payload") or self.record.result_payload,
            metadata={**self.record.metadata, **(kwargs.get("metadata") or {})},
            updated_at="2026-03-07T01:00:00Z",
        )
        return self.record

    def add_artifact(self, analysis_euid: str, **kwargs):
        assert self.record is not None
        assert self.record.analysis_euid == analysis_euid
        artifact = AnalysisArtifact(
            artifact_euid=_opaque("artifact"),
            artifact_type=kwargs["artifact_type"],
            storage_uri=kwargs["storage_uri"],
            filename=kwargs["filename"],
            mime_type=kwargs.get("mime_type"),
            checksum_sha256=kwargs.get("checksum_sha256"),
            size_bytes=kwargs.get("size_bytes"),
            created_at="2026-03-07T02:00:00Z",
            metadata=kwargs.get("metadata") or {},
        )
        self.record = replace(self.record, artifacts=[*self.record.artifacts, artifact])
        return artifact

    def set_review_state(self, analysis_euid: str, **kwargs):
        assert self.record is not None
        assert self.record.analysis_euid == analysis_euid
        self.record = replace(
            self.record,
            state=AnalysisState.REVIEWED.value,
            review_state=kwargs["review_state"].value,
            updated_at="2026-03-07T03:00:00Z",
        )
        return self.record

    def mark_returned(self, analysis_euid: str, **kwargs):
        assert self.record is not None
        assert self.record.analysis_euid == analysis_euid
        self.record = replace(
            self.record,
            state=AnalysisState.RETURNED.value,
            atlas_return=dict(kwargs["atlas_return"]),
            updated_at="2026-03-07T04:00:00Z",
        )
        return self.record


def _build_atlas_intake_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(atlas_intake_routes.router)

    def override_get_db():
        yield None

    async def override_require_internal():
        return None

    def override_current_user():
        return CurrentUser(
            sub=str(uuid.uuid4()),
            email="internal@example.com",
            name="Internal User",
            tenant_id=tenant_id,
            roles=["INTERNAL_USER"],
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_internal] = override_require_internal
    app.dependency_overrides[get_current_user] = override_current_user
    return app


def _build_atlas_result_app() -> FastAPI:
    app = FastAPI()
    app.include_router(atlas_ursa_routes.router)

    def override_get_db():
        yield None

    async def override_verify_internal_api_key():
        return None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_internal_api_key] = override_verify_internal_api_key
    return app


def test_cross_repo_beta_smoke(monkeypatch):
    tenant_id = uuid.uuid4()
    atlas_order_euid = _opaque("order")
    atlas_test_order_euid = _opaque("trftest")
    patient_euid = _opaque("patient")
    index_string = "IDX-ILMN-BETA-01"
    captured_return: dict[str, object] = {}

    class FakeIntakeService:
        def __init__(self, db, provided_tenant_id):
            assert provided_tenant_id == tenant_id

        def record_material_outcome(self, data, *, actor_id=None):
            assert actor_id is not None
            assert data.outcome.value == "ACCEPTED"
            return SimpleNamespace(
                outcome="ACCEPTED",
                accepted=True,
                order_euid=data.order_euid,
                order_status="IN_PROGRESS",
                test_order_euids=data.test_order_euids,
                test_order_statuses={
                    test_order_euid: "SPECIMEN_RECEIVED"
                    for test_order_euid in data.test_order_euids
                },
                patient_euid=data.patient_euid,
                container_euid="CNT-SMOKE",
                specimen_euid="SP-SMOKE",
                current_queue=data.starting_queue,
            )

    class FakeUrsaResultReturnService:
        def __init__(self, db, provided_tenant_id):
            assert provided_tenant_id == tenant_id

        def apply(self, data):
            captured_return["request"] = data
            return SimpleNamespace(
                assay_run_euid="ASR-SMOKE",
                assay_result_euid="RES-SMOKE",
                artifact_euids=["ART-SMOKE-1"],
                results_set_euid="RSET-SMOKE",
                idempotent_replay=False,
            )

    monkeypatch.setattr(atlas_intake_routes, "IntakeService", FakeIntakeService)
    monkeypatch.setattr(
        atlas_ursa_routes,
        "UrsaResultReturnService",
        FakeUrsaResultReturnService,
    )

    bloom_app = create_bloom_app()
    bloom_app.dependency_overrides[require_external_token_auth] = _external_rw_user

    atlas_intake_app = _build_atlas_intake_app(tenant_id)
    atlas_result_app = _build_atlas_result_app()

    with (
        TestClient(atlas_intake_app) as atlas_intake_client,
        TestClient(atlas_result_app) as atlas_result_client,
        TestClient(bloom_app) as bloom_client,
    ):
        intake_response = atlas_intake_client.post(
            "/api/intake/outcomes",
            json={
                "order_euid": atlas_order_euid,
                "test_order_euids": [atlas_test_order_euid],
                "patient_euid": patient_euid,
                "shipment_euid": _opaque("shipment"),
                "outcome": "ACCEPTED",
                "starting_queue": "extraction_prod",
            },
        )
        assert intake_response.status_code == 200, intake_response.text
        assert intake_response.json()["accepted"] is True

        atlas_refs = {
            "atlas_tenant_id": str(tenant_id),
            "atlas_order_euid": atlas_order_euid,
            "atlas_test_order_euid": atlas_test_order_euid,
        }
        material_idem = _opaque("idem-material")
        material_response = bloom_client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": material_idem},
            json={
                "specimen_name": "beta-smoke-whole-blood",
                "properties": {"source": "cross-repo-smoke"},
                "atlas_refs": atlas_refs,
            },
        )
        assert material_response.status_code == 200, material_response.text
        material = material_response.json()
        _assert_no_uuid_keys(material)
        assert material["created"] is True
        specimen_euid = material["specimen_euid"]

        material_replay = bloom_client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": material_idem},
            json={
                "specimen_name": "beta-smoke-whole-blood",
                "properties": {"source": "cross-repo-smoke"},
                "atlas_refs": atlas_refs,
            },
        )
        assert material_replay.status_code == 200, material_replay.text
        assert material_replay.json()["created"] is False

        queue_response = bloom_client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{specimen_euid}",
            headers={"Idempotency-Key": _opaque("idem-queue")},
            json={"metadata": {"reason": "accepted-material"}},
        )
        assert queue_response.status_code == 200, queue_response.text
        assert queue_response.json()["current_queue"] == "extraction_prod"

        extraction_response = bloom_client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extraction")},
            json={
                "source_specimen_euid": specimen_euid,
                "plate_name": "beta-smoke-plate",
                "well_name": "A1",
                "extraction_type": "cfdna",
                "output_name": "beta-smoke-extract",
                "metadata": {"operator": "pytest"},
            },
        )
        assert extraction_response.status_code == 200, extraction_response.text
        extraction = extraction_response.json()
        extraction_output_euid = extraction["extraction_output_euid"]
        assert extraction["current_queue"] == "post_extract_qc"

        qc_response = bloom_client.post(
            "/api/v1/external/atlas/beta/post-extract-qc",
            headers={"Idempotency-Key": _opaque("idem-qc")},
            json={
                "extraction_output_euid": extraction_output_euid,
                "passed": True,
                "next_queue": "ilmn_lib_prep",
                "metrics": {"yield_ng": 42.5},
            },
        )
        assert qc_response.status_code == 200, qc_response.text
        assert qc_response.json()["current_queue"] == "ilmn_lib_prep"

        library_response = bloom_client.post(
            "/api/v1/external/atlas/beta/library-prep",
            headers={"Idempotency-Key": _opaque("idem-libprep")},
            json={
                "source_extraction_output_euid": extraction_output_euid,
                "platform": "ILMN",
                "output_name": "beta-smoke-library",
                "metadata": {"kit": "ilmn-beta"},
            },
        )
        assert library_response.status_code == 200, library_response.text
        library = library_response.json()
        library_euid = library["library_prep_output_euid"]
        assert library["current_queue"] == "ilmn_seq_pool"

        pool_response = bloom_client.post(
            "/api/v1/external/atlas/beta/pools",
            headers={"Idempotency-Key": _opaque("idem-pool")},
            json={
                "member_euids": [library_euid],
                "platform": "ILMN",
                "pool_name": "beta-smoke-pool",
                "metadata": {"pool_strategy": "singleplex"},
            },
        )
        assert pool_response.status_code == 200, pool_response.text
        pool = pool_response.json()
        pool_euid = pool["pool_euid"]
        assert pool["current_queue"] == "ilmn_start_seq_run"

        run_response = bloom_client.post(
            "/api/v1/external/atlas/beta/runs",
            headers={"Idempotency-Key": _opaque("idem-run")},
            json={
                "pool_euid": pool_euid,
                "platform": "ILMN",
                "run_name": "beta-smoke-run",
                "status": "completed",
                "index_mappings": [
                    {
                        "index_string": index_string,
                        "source_euid": library_euid,
                    }
                ],
                "artifacts": [
                    {
                        "artifact_type": "fastq",
                        "bucket": "beta-analysis-artifacts",
                        "filename": "reads_R1.fastq.gz",
                        "index_string": index_string,
                        "metadata": {"read_pair": 1},
                    }
                ],
            },
        )
        assert run_response.status_code == 200, run_response.text
        run_payload = run_response.json()
        _assert_no_uuid_keys(run_payload)
        run_euid = run_payload["run_euid"]
        assert run_payload["run_folder"] == f"{run_euid}/"

        resolver_client = BloomResolverClient(
            base_url=str(bloom_client.base_url).rstrip("/"),
            token="bloom-smoke-token",
            client=bloom_client,
        )
        atlas_client = AtlasResultClient(
            base_url=str(atlas_result_client.base_url).rstrip("/"),
            api_key="atlas-smoke-key",
            client=atlas_result_client,
        )
        ursa_store = SmokeAnalysisStore()
        ursa_app = create_ursa_app(
            ursa_store,
            bloom_client=resolver_client,
            atlas_client=atlas_client,
            settings=Settings(
                cors_origins="*",
                ursa_internal_api_key="ursa-smoke-key",
                bloom_base_url=str(bloom_client.base_url).rstrip("/"),
                atlas_base_url=str(atlas_result_client.base_url).rstrip("/"),
                atlas_internal_api_key="atlas-smoke-key",
            ),
        )

        with TestClient(ursa_app) as ursa_client:
            ingest_response = ursa_client.post(
                "/api/analyses/ingest",
                headers={
                    "X-API-Key": "ursa-smoke-key",
                    "Idempotency-Key": _opaque("idem-ingest"),
                },
                json={
                    "run_euid": run_euid,
                    "index_string": index_string,
                    "analysis_type": "WGS",
                    "artifact_bucket": "beta-analysis-artifacts",
                    "input_files": [f"s3://beta-analysis-artifacts/{run_euid}/reads_R1.fastq.gz"],
                    "metadata": {"pipeline": "beta-smoke"},
                },
            )
            assert ingest_response.status_code == 201, ingest_response.text
            ingest_payload = ingest_response.json()
            analysis_euid = ingest_payload["analysis_euid"]
            assert ingest_payload["atlas_test_order_euid"] == atlas_test_order_euid

            status_response = ursa_client.post(
                f"/api/analyses/{analysis_euid}/status",
                headers={"X-API-Key": "ursa-smoke-key"},
                json={
                    "state": "RUNNING",
                    "result_status": "IN_PROGRESS",
                    "metadata": {"stage": "analysis"},
                    "reason": "started",
                },
            )
            assert status_response.status_code == 200, status_response.text
            assert status_response.json()["state"] == "RUNNING"

            artifact_response = ursa_client.post(
                f"/api/analyses/{analysis_euid}/artifacts",
                headers={"X-API-Key": "ursa-smoke-key"},
                json={
                    "artifact_type": "vcf",
                    "storage_uri": f"s3://beta-analysis-artifacts/{run_euid}/sample.vcf.gz",
                    "filename": "sample.vcf.gz",
                    "mime_type": "application/gzip",
                    "metadata": {"kind": "primary"},
                },
            )
            assert artifact_response.status_code == 201, artifact_response.text

            review_response = ursa_client.post(
                f"/api/analyses/{analysis_euid}/review",
                headers={"X-API-Key": "ursa-smoke-key"},
                json={
                    "review_state": "APPROVED",
                    "reviewer": "beta-reviewer@example.com",
                    "notes": "beta smoke approval",
                },
            )
            assert review_response.status_code == 200, review_response.text
            assert review_response.json()["review_state"] == "APPROVED"

            return_response = ursa_client.post(
                f"/api/analyses/{analysis_euid}/return",
                headers={
                    "X-API-Key": "ursa-smoke-key",
                    "Idempotency-Key": _opaque("idem-return"),
                },
                json={
                    "result_status": "COMPLETED",
                    "result_payload": {"variants": [], "qc": "PASS"},
                },
            )
            assert return_response.status_code == 200, return_response.text
            returned = return_response.json()
            _assert_no_uuid_keys(returned)
            assert returned["state"] == "RETURNED"
            assert returned["atlas_return"]["assay_run_euid"] == "ASR-SMOKE"
            assert returned["atlas_return"]["assay_result_euid"] == "RES-SMOKE"
            assert returned["atlas_return"]["artifact_euids"] == ["ART-SMOKE-1"]
            assert returned["atlas_return"]["results_set_euid"] == "RSET-SMOKE"
            assert returned["atlas_return"]["result_status"] == "COMPLETED"

    recorded_request = captured_return["request"]
    assert recorded_request.atlas_order_euid == atlas_order_euid
    assert recorded_request.atlas_test_order_euid == atlas_test_order_euid
    assert recorded_request.run_euid == run_euid
    assert recorded_request.index_string == index_string
    assert recorded_request.artifacts[0].storage_uri == f"s3://beta-analysis-artifacts/{run_euid}/sample.vcf.gz"
