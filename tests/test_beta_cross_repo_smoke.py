"""Cross-repo beta smoke flow across Atlas, Bloom, and Ursa contracts."""

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


def _resolve_repo_root(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


ATLAS_ROOT = _resolve_repo_root(
    WORKSPACE_ROOT / "lsmc-atlas",
    WORKSPACE_ROOT.parent / "lsmc" / "lsmc-atlas",
    WORKSPACE_ROOT.parent.parent / "lsmc-atlas",
)
URSA_ROOT = _resolve_repo_root(
    WORKSPACE_ROOT / "daylily-ursa",
    WORKSPACE_ROOT.parent / "daylily-ursa",
    WORKSPACE_ROOT.parent.parent / "daylily-ursa",
)

if ATLAS_ROOT is None or URSA_ROOT is None:
    pytest.skip(
        "Cross-repo beta smoke requires local Atlas and Ursa checkouts.",
        allow_module_level=True,
    )

os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{WORKSPACE_ROOT / '_refactor' / 'atlas_beta_smoke.sqlite'}",
)
for root in (ATLAS_ROOT, URSA_ROOT):
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

from bloom_lims.api.v1.dependencies import APIUser, require_external_token_auth
from bloom_lims.auth.rbac import ENABLE_ATLAS_API_GROUP, ENABLE_URSA_API_GROUP
from bloom_lims.app import create_app as create_bloom_app

try:  # noqa: E402
    from daylib_ursa.analysis_store import (
        AnalysisArtifact,
        AnalysisRecord,
        AnalysisState,
        ReviewState,
        RunResolution,
    )
    from daylib_ursa.atlas_result_client import AtlasResultClient
    from daylib_ursa.bloom_resolver_client import BloomResolverClient
    from daylib_ursa.config import Settings
    from daylib_ursa.workset_api import create_app as create_ursa_app
except ModuleNotFoundError:  # pragma: no cover - compatibility fallback
    from daylib.analysis_store import (
        AnalysisArtifact,
        AnalysisRecord,
        AnalysisState,
        ReviewState,
        RunResolution,
    )
    from daylib.atlas_result_client import AtlasResultClient
    from daylib.bloom_resolver_client import BloomResolverClient
    from daylib.config import Settings
    from daylib.workset_api import create_app as create_ursa_app

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
        roles=["READ_WRITE"],
        groups=[ENABLE_ATLAS_API_GROUP, ENABLE_URSA_API_GROUP],
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
        output_bucket = str(kwargs.get("internal_bucket") or "").strip()
        assert output_bucket
        tenant_id = getattr(resolution, "tenant_id", None)
        if tenant_id is None:
            tenant_id = getattr(resolution, "atlas_tenant_id")
        now = "2026-03-08T00:00:00Z"
        if self.record is None:
            self.record = AnalysisRecord(
                analysis_euid=_opaque("analysis"),
                workset_euid=None,
                run_euid=resolution.run_euid,
                flowcell_id=resolution.flowcell_id,
                lane=resolution.lane,
                library_barcode=resolution.library_barcode,
                sequenced_library_assignment_euid=resolution.sequenced_library_assignment_euid,
                tenant_id=tenant_id,
                atlas_trf_euid=resolution.atlas_trf_euid,
                atlas_test_euid=resolution.atlas_test_euid,
                atlas_test_fulfillment_item_euid=resolution.atlas_test_fulfillment_item_euid,
                analysis_type=kwargs["analysis_type"],
                state=AnalysisState.INGESTED.value,
                review_state=ReviewState.PENDING.value,
                result_status="PENDING",
                run_folder=f"s3://{output_bucket}/{resolution.run_euid}/",
                internal_bucket=output_bucket,
                input_references=list(kwargs.get("input_references") or []),
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
            updated_at="2026-03-08T01:00:00Z",
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
            created_at="2026-03-08T02:00:00Z",
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
            updated_at="2026-03-08T03:00:00Z",
        )
        return self.record

    def mark_returned(self, analysis_euid: str, **kwargs):
        assert self.record is not None
        assert self.record.analysis_euid == analysis_euid
        self.record = replace(
            self.record,
            state=AnalysisState.RETURNED.value,
            result_status=kwargs["atlas_return"].get(
                "result_status", self.record.result_status
            ),
            atlas_return=dict(kwargs["atlas_return"]),
            updated_at="2026-03-08T04:00:00Z",
        )
        return self.record


class SmokeDeweyClient:
    def __init__(self) -> None:
        self._seq = 1
        self._artifacts: dict[str, dict] = {}

    def register_artifact(
        self,
        *,
        artifact_type: str,
        storage_uri: str,
        metadata: dict | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        token = f"AT-SMOKE-{self._seq}"
        self._seq += 1
        self._artifacts[token] = {
            "artifact_euid": token,
            "artifact_type": artifact_type,
            "storage_uri": storage_uri,
            "filename": Path(storage_uri).name,
            "metadata": dict(metadata or {}),
            "idempotency_key": idempotency_key,
        }
        return token

    def resolve_artifact(self, artifact_euid: str) -> dict:
        return dict(self._artifacts[artifact_euid])


class SmokeUrsaAuthProvider:
    def __init__(self, tenant_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id

    def resolve_access_token(self, token: str) -> SimpleNamespace:
        assert token == "atlas-token"
        return SimpleNamespace(
            sub="ursa-smoke-user",
            email="ursa-smoke@example.com",
            name="Ursa Smoke User",
            tenant_id=self.tenant_id,
            roles=["INTERNAL_USER"],
            user_id="ursa-smoke-user",
            is_admin=False,
        )


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
    atlas_trf_euid = _opaque("trf")
    atlas_test_accept = _opaque("test")
    atlas_test_hold = _opaque("test")
    atlas_test_reject = _opaque("test")
    fulfillment_item_accept = _opaque("tpc")
    patient_euid = _opaque("patient")
    shipment_euid = _opaque("shipment")
    captured_return: dict[str, object] = {}

    class FakeIntakeService:
        def __init__(self, db, provided_tenant_id):
            assert provided_tenant_id == tenant_id

        def record_material_outcome(self, data, *, actor_id=None):
            assert actor_id is not None
            if data.outcome.value == "REJECTED":
                return SimpleNamespace(
                    outcome="REJECTED",
                    accepted=False,
                    trf_euid=data.trf_euid,
                    trf_status="REJECTED",
                    test_euids=data.test_euids,
                    fulfillment_item_euids=[],
                    test_statuses={data.test_euids[0]: "REJECTED"},
                    patient_euid=data.patient_euid,
                    container_euid=None,
                    specimen_euid=None,
                    current_queue=None,
                )
            if data.outcome.value == "HOLD":
                return SimpleNamespace(
                    outcome="HOLD",
                    accepted=False,
                    trf_euid=data.trf_euid,
                    trf_status="ON_HOLD",
                    test_euids=data.test_euids,
                    fulfillment_item_euids=[],
                    test_statuses={data.test_euids[0]: "ON_HOLD"},
                    patient_euid=data.patient_euid,
                    container_euid=None,
                    specimen_euid=None,
                    current_queue=None,
                )
            return SimpleNamespace(
                outcome="ACCEPTED",
                accepted=True,
                trf_euid=data.trf_euid,
                trf_status="IN_PROGRESS",
                test_euids=data.test_euids,
                fulfillment_item_euids=[fulfillment_item_accept],
                test_statuses={
                    test_euid: "SPECIMEN_RECEIVED" for test_euid in data.test_euids
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
                fulfillment_run_euid="ASR-SMOKE",
                fulfillment_output_euid="RES-SMOKE",
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
        for outcome, test_euid in (
            ("REJECTED", atlas_test_reject),
            ("HOLD", atlas_test_hold),
        ):
            response = atlas_intake_client.post(
                "/api/intake/outcomes",
                json={
                    "trf_euid": atlas_trf_euid,
                    "test_euids": [test_euid],
                    "patient_euid": patient_euid,
                    "shipment_euid": shipment_euid,
                    "outcome": outcome,
                    "starting_queue": None,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            _assert_no_uuid_keys(body)
            assert body["accepted"] is False
            assert body["fulfillment_item_euids"] == []

        accepted_response = atlas_intake_client.post(
            "/api/intake/outcomes",
            json={
                "trf_euid": atlas_trf_euid,
                "test_euids": [atlas_test_accept],
                "patient_euid": patient_euid,
                "shipment_euid": shipment_euid,
                "outcome": "ACCEPTED",
                "starting_queue": "extraction_prod",
            },
        )
        assert accepted_response.status_code == 200, accepted_response.text
        accepted_body = accepted_response.json()
        _assert_no_uuid_keys(accepted_body)
        assert accepted_body["accepted"] is True
        assert accepted_body["fulfillment_item_euids"] == [fulfillment_item_accept]

        atlas_context = {
            "atlas_tenant_id": str(tenant_id),
            "atlas_trf_euid": atlas_trf_euid,
            "fulfillment_items": [
                {
                    "atlas_test_euid": atlas_test_accept,
                    "atlas_test_fulfillment_item_euid": fulfillment_item_accept,
                }
            ],
        }
        material_response = bloom_client.post(
            "/api/v1/external/atlas/beta/materials",
            headers={"Idempotency-Key": _opaque("idem-material")},
            json={
                "specimen_name": "beta-smoke-whole-blood",
                "properties": {"source": "cross-repo-smoke"},
                "atlas_context": atlas_context,
            },
        )
        assert material_response.status_code == 200, material_response.text
        material = material_response.json()
        _assert_no_uuid_keys(material)
        specimen_euid = material["specimen_euid"]

        queued = bloom_client.post(
            f"/api/v1/external/atlas/beta/queues/extraction_prod/items/{specimen_euid}",
            headers={"Idempotency-Key": _opaque("idem-queue")},
            json={"metadata": {"reason": "accepted-material"}},
        )
        assert queued.status_code == 200, queued.text

        extraction = bloom_client.post(
            "/api/v1/external/atlas/beta/extractions",
            headers={"Idempotency-Key": _opaque("idem-extract")},
            json={
                "source_specimen_euid": specimen_euid,
                "well_name": "A1",
                "extraction_type": "gdna",
                "atlas_test_fulfillment_item_euid": fulfillment_item_accept,
            },
        )
        assert extraction.status_code == 200, extraction.text
        extraction_output_euid = extraction.json()["extraction_output_euid"]

        qc = bloom_client.post(
            "/api/v1/external/atlas/beta/post-extract-qc",
            headers={"Idempotency-Key": _opaque("idem-qc")},
            json={
                "extraction_output_euid": extraction_output_euid,
                "passed": True,
                "next_queue": "ont_lib_prep",
            },
        )
        assert qc.status_code == 200, qc.text

        library_prep = bloom_client.post(
            "/api/v1/external/atlas/beta/library-prep",
            headers={"Idempotency-Key": _opaque("idem-libprep")},
            json={
                "source_extraction_output_euid": extraction_output_euid,
                "platform": "ONT",
            },
        )
        assert library_prep.status_code == 200, library_prep.text
        library_prep_output_euid = library_prep.json()["library_prep_output_euid"]

        pool = bloom_client.post(
            "/api/v1/external/atlas/beta/pools",
            headers={"Idempotency-Key": _opaque("idem-pool")},
            json={
                "member_euids": [library_prep_output_euid],
                "platform": "ONT",
            },
        )
        assert pool.status_code == 200, pool.text
        pool_euid = pool.json()["pool_euid"]

        flowcell_id = "FLOW-BETA-01"
        lane = "2"
        library_barcode = "ONT-LIB-01"
        run = bloom_client.post(
            "/api/v1/external/atlas/beta/runs",
            headers={"Idempotency-Key": _opaque("idem-run")},
            json={
                "pool_euid": pool_euid,
                "platform": "ONT",
                "flowcell_id": flowcell_id,
                "status": "completed",
                "assignments": [
                    {
                        "lane": lane,
                        "library_barcode": library_barcode,
                        "library_prep_output_euid": library_prep_output_euid,
                    }
                ],
                "artifacts": [
                    {
                        "artifact_type": "fastq",
                        "bucket": "beta-analysis-artifacts",
                        "filename": "reads.fastq.gz",
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

        resolved = bloom_client.get(
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
        assert (
            resolved_body["atlas_test_fulfillment_item_euid"] == fulfillment_item_accept
        )

        store = SmokeAnalysisStore()
        dewey_client = SmokeDeweyClient()
        input_artifact_euid = dewey_client.register_artifact(
            artifact_type="fastq",
            storage_uri="s3://beta-analysis-artifacts/input.fastq.gz",
            metadata={"producer_system": "smoke"},
        )
        ursa_app = create_ursa_app(
            store=store,
            bloom_client=BloomResolverClient(
                base_url="https://testserver",
                token="bloom-smoke-token",
                client=bloom_client,  # type: ignore[arg-type]
            ),
            atlas_client=AtlasResultClient(
                base_url="https://testserver",
                api_key="atlas-smoke-key",
                client=atlas_result_client,  # type: ignore[arg-type]
            ),
            dewey_client=dewey_client,
            auth_provider=SmokeUrsaAuthProvider(tenant_id),
            settings=Settings(
                ursa_internal_api_key="ursa-smoke-key",
                ursa_internal_output_bucket="beta-analysis-artifacts",
                bloom_base_url="https://testserver",
                bloom_api_token="bloom-smoke-token",
                atlas_base_url="https://testserver",
                atlas_internal_api_key="atlas-smoke-key",
            ),
        )

        with TestClient(ursa_app) as ursa_client:
            ingest = ursa_client.post(
                "/api/v1/analyses/ingest",
                headers={
                    "Idempotency-Key": _opaque("idem-ingest"),
                    "X-API-Key": "ursa-smoke-key",
                },
                json={
                    "run_euid": run_body["run_euid"],
                    "flowcell_id": flowcell_id,
                    "lane": lane,
                    "library_barcode": library_barcode,
                    "analysis_type": "WGS",
                    "input_references": [
                        {
                            "reference_type": "artifact_euid",
                            "value": input_artifact_euid,
                        }
                    ],
                },
            )
            assert ingest.status_code == 201, ingest.text
            ingest_payload = ingest.json()
            _assert_no_uuid_keys(ingest_payload)
            analysis_euid = ingest_payload["analysis_euid"]
            assert (
                ingest_payload["atlas_test_fulfillment_item_euid"]
                == fulfillment_item_accept
            )
            assert (
                ingest_payload["sequenced_library_assignment_euid"]
                == resolved_body["sequenced_library_assignment_euid"]
            )
            result_artifact_euid = dewey_client.register_artifact(
                artifact_type="vcf",
                storage_uri="s3://beta-analysis-artifacts/result.vcf.gz",
                metadata={"producer_system": "smoke"},
            )

            artifact = ursa_client.post(
                f"/api/v1/analyses/{analysis_euid}/artifacts",
                headers={"X-API-Key": "ursa-smoke-key"},
                json={"artifact_euid": result_artifact_euid},
            )
            assert artifact.status_code == 201, artifact.text

            preapproval = ursa_client.post(
                f"/api/v1/analyses/{analysis_euid}/return",
                headers={
                    "Authorization": "Bearer atlas-token",
                    "Idempotency-Key": _opaque("idem-return-pre"),
                },
                json={"result_status": "COMPLETED", "result_payload": {"variants": []}},
            )
            assert preapproval.status_code == 409, preapproval.text

            review = ursa_client.post(
                f"/api/v1/analyses/{analysis_euid}/review",
                headers={"Authorization": "Bearer atlas-token"},
                json={
                    "review_state": "APPROVED",
                    "reviewer": "qa-reviewer",
                },
            )
            assert review.status_code == 200, review.text

            returned = ursa_client.post(
                f"/api/v1/analyses/{analysis_euid}/return",
                headers={
                    "Authorization": "Bearer atlas-token",
                    "Idempotency-Key": _opaque("idem-return"),
                },
                json={"result_status": "COMPLETED", "result_payload": {"variants": []}},
            )
            assert returned.status_code == 200, returned.text
            return_body = returned.json()
            _assert_no_uuid_keys(return_body)
            assert return_body["state"] == "RETURNED"
            assert return_body["review_state"] == "APPROVED"

    recorded_request = captured_return["request"]
    assert recorded_request.atlas_tenant_id == str(tenant_id)
    assert recorded_request.atlas_trf_euid == atlas_trf_euid
    assert recorded_request.atlas_test_euid == atlas_test_accept
    assert recorded_request.atlas_test_fulfillment_item_euid == fulfillment_item_accept
    assert recorded_request.flowcell_id == flowcell_id
    assert recorded_request.lane == lane
    assert recorded_request.library_barcode == library_barcode
