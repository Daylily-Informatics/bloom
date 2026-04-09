"""Direct API coverage for the execution queue router."""

from __future__ import annotations

import os
import secrets
import sys
from datetime import datetime, UTC

import pytest
from fastapi.testclient import TestClient

from bloom_lims.api.v1.dependencies import APIUser, require_api_auth

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _opaque(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def _internal_rw_user() -> APIUser:
    return APIUser(
        email="execution-api@example.com",
        user_id=_opaque("user"),
        roles=["READ_WRITE"],
        auth_source="token",
        token_scope="internal_rw",
        token_id=_opaque("token"),
    )


def _internal_ro_user() -> APIUser:
    return APIUser(
        email="execution-api-ro@example.com",
        user_id=_opaque("user"),
        roles=["READ_ONLY"],
        auth_source="token",
        token_scope="internal_ro",
        token_id=_opaque("token"),
    )


def _internal_admin_user() -> APIUser:
    return APIUser(
        email="execution-api-admin@example.com",
        user_id=_opaque("user"),
        roles=["ADMIN"],
        auth_source="token",
        token_scope="internal_admin",
        token_id=_opaque("token"),
    )


def _queue_summary() -> dict:
    return {
        "queue_euid": "WQ_EXTRACT",
        "queue_key": "extraction_prod",
        "display_name": "Extraction Production",
        "enabled": True,
        "manual_only": False,
        "operator_visible": True,
        "dispatch_priority": 10,
        "queue_depth": 3,
        "oldest_job_age_seconds": 12.0,
        "newest_job_age_seconds": 1.0,
        "active_leases": 1,
        "held_count": 0,
        "dead_letter_count": 0,
        "failure_rate": 0.0,
    }


def _queue_detail() -> dict:
    payload = _queue_summary()
    payload.update(
        {
            "subject_template_codes": ["workflow_step/queue/all-purpose/1.0"],
            "eligible_states": ["READY", "WAITING_EXTERNAL"],
            "required_worker_capabilities": ["wetlab.extraction"],
            "site_scope": [],
            "platform_scope": [],
            "assay_scope": [],
            "lease_ttl_seconds": 300,
            "max_attempts_default": 3,
            "retry_policy": {
                "mode": "EXPONENTIAL_BACKOFF",
                "initial_delay_seconds": 60,
                "backoff_factor": 2.0,
                "max_delay_seconds": 3600,
            },
            "selection_policy": {
                "order": [
                    "priority_desc",
                    "due_at_asc",
                    "ready_at_asc",
                    "created_dt_asc",
                    "euid_asc",
                ]
            },
            "diagnostics_enabled": True,
            "revision": 1,
            "disabled_reason": None,
        }
    )
    return payload


def _worker_detail(worker_euid: str) -> dict:
    return {
        "worker_euid": worker_euid,
        "worker_key": f"worker://pytest/{worker_euid}",
        "display_name": "Pytest Worker",
        "worker_type": "SERVICE",
        "status": "ONLINE",
        "capabilities": ["wetlab.extraction"],
        "active_lease_count": 0,
        "max_concurrent_leases": 2,
        "heartbeat_at": "2026-04-08T21:00:00+00:00",
        "heartbeat_lag_seconds": 0.1,
        "drain_requested": False,
        "site_scope": [],
        "platform_scope": [],
        "assay_scope": [],
        "heartbeat_ttl_seconds": 120,
        "build_version": "test-build",
        "host": "pytest-host",
        "process_identity": "pytest-proc",
        "disabled_reason": None,
        "last_error_at": None,
        "last_error_class": None,
        "revision": 1,
    }


def _lease_summary() -> dict:
    return {
        "lease_euid": "LEASE-1",
        "lease_token": "lease-token-1",
        "queue_lookup_key": "extraction_prod",
        "subject_lookup_euid": "SUBJ-1",
        "worker_lookup_euid": "WORKER-1",
        "status": "ACTIVE",
        "claimed_at": "2026-04-08T21:00:00+00:00",
        "heartbeat_at": "2026-04-08T21:01:00+00:00",
        "expires_at": "2026-04-08T21:06:00+00:00",
        "released_at": None,
        "release_reason": None,
        "attempt_number": 1,
        "next_action_key": "extract",
        "idempotency_key": "idem-lease",
    }


def _subject_detail() -> dict:
    return {
        "subject_euid": "SUBJ-1",
        "subject_name": "Subject One",
        "subject_category": "workflow_step",
        "template_code": "workflow_step/queue/all-purpose/1.0",
        "execution": {
            "state": "READY",
            "revision": 2,
            "next_queue_key": "extraction_prod",
            "next_action_key": "extract",
            "priority": 5,
            "ready_at": "2026-04-08T21:00:00+00:00",
            "due_at": None,
            "attempt_count": 1,
            "max_attempts_override": None,
            "retry_at": None,
            "hold_state": "NONE",
            "hold_reason": None,
            "cancel_requested": False,
            "terminal": False,
            "last_execution_record_euid": None,
            "queue_cache": {
                "current_queue_key": "extraction_prod",
                "computed_at": "2026-04-08T21:00:00+00:00",
            },
        },
        "diagnostics": {
            "visible_in_queue": True,
            "current_queue_key": "extraction_prod",
            "reasons": [],
        },
        "active_lease": _lease_summary(),
        "active_holds": [],
        "dead_letter": None,
    }


def _subject_history() -> dict:
    return {
        "subject_euid": "SUBJ-1",
        "records": [],
        "leases": [_lease_summary()],
        "holds": [],
        "dead_letters": [],
    }


def _queue_item() -> dict:
    return {
        "subject_euid": "SUBJ-1",
        "subject_name": "Subject One",
        "subject_category": "workflow_step",
        "template_code": "workflow_step/queue/all-purpose/1.0",
        "state": "READY",
        "next_queue_key": "extraction_prod",
        "next_action_key": "extract",
        "priority": 5,
        "ready_at": "2026-04-08T21:00:00+00:00",
        "due_at": None,
        "retry_at": None,
        "attempt_count": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "queue_ready_timestamp": "2026-04-08T21:00:00+00:00",
    }


def _dead_letter_summary() -> dict:
    return {
        "dead_letter_euid": "DLQ-1",
        "subject_lookup_euid": "SUBJ-1",
        "queue_lookup_key": "extraction_prod",
        "last_execution_record_lookup_euid": None,
        "last_lease_lookup_euid": None,
        "dead_lettered_at": "2026-04-08T21:10:00+00:00",
        "failure_count": 1,
        "error_class": "ValueError",
        "error_message": "queue failure",
        "resolution_state": "OPEN",
        "resolved_by_lookup_euid": None,
        "resolved_at": None,
    }


class _FakeExecutionQueueService:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def close(self) -> None:
        return None

    def list_queues(self):
        return [_queue_summary()]

    def get_queue(self, queue_key: str):
        payload = _queue_detail()
        payload["queue_key"] = queue_key
        return payload

    def list_queue_items(self, queue_key: str):
        payload = _queue_item()
        payload["next_queue_key"] = queue_key
        return [payload]

    def get_subject_detail(self, euid: str):
        payload = _subject_detail()
        payload["subject_euid"] = euid
        return payload

    def get_subject_history(self, euid: str):
        payload = _subject_history()
        payload["subject_euid"] = euid
        return payload

    def list_workers(self):
        worker = _worker_detail("WORKER-1")
        return [
            {
                key: worker[key]
                for key in (
                    "worker_euid",
                    "worker_key",
                    "display_name",
                    "worker_type",
                    "status",
                    "capabilities",
                    "active_lease_count",
                    "max_concurrent_leases",
                    "heartbeat_at",
                    "heartbeat_lag_seconds",
                    "drain_requested",
                )
            }
        ]

    def get_worker(self, worker_euid: str):
        return _worker_detail(worker_euid)

    def list_leases(self, status: str | None = None):
        payload = _lease_summary()
        payload["status"] = status or payload["status"]
        return [payload]

    def list_dead_letters(self):
        return [_dead_letter_summary()]

    def register_worker(self, payload, *, executed_by: str):
        worker = _worker_detail("WORKER-REGISTERED")
        worker["worker_key"] = payload.worker_key
        worker["display_name"] = payload.display_name
        worker["capabilities"] = list(payload.capabilities)
        worker["max_concurrent_leases"] = payload.max_concurrent_leases
        return worker

    def heartbeat_worker(self, payload, *, executed_by: str):
        worker = _worker_detail(payload.worker_euid)
        if payload.status is not None:
            worker["status"] = payload.status
        return worker

    def claim_queue_item(self, payload, *, executed_by: str):
        return {
            "status": "claimed",
            "action_key": "claim",
            "subject_euid": payload.subject_euid or "SUBJ-1",
            "worker_euid": payload.worker_euid,
            "lease_euid": "LEASE-1",
            "replayed": False,
            "result": {"queue_key": payload.queue_key},
        }

    def renew_queue_lease(self, payload, *, executed_by: str):
        return {
            "status": "renewed",
            "action_key": "renew-lease",
            "worker_euid": payload.worker_euid,
            "lease_euid": payload.lease_euid,
            "replayed": False,
            "result": {},
        }

    def release_queue_lease(self, payload, *, executed_by: str):
        return {
            "status": "released",
            "action_key": "release-lease",
            "worker_euid": payload.worker_euid,
            "lease_euid": payload.lease_euid,
            "replayed": False,
            "result": {"reason": payload.reason},
        }

    def complete_queue_execution(self, payload, *, executed_by: str):
        return {
            "status": "completed",
            "action_key": payload.action_key,
            "subject_euid": payload.subject_euid,
            "worker_euid": payload.worker_euid,
            "lease_euid": payload.lease_euid,
            "replayed": False,
            "result": dict(payload.result_payload),
        }

    def fail_queue_execution(self, payload, *, executed_by: str):
        return {
            "status": "failed",
            "action_key": payload.action_key,
            "subject_euid": payload.subject_euid,
            "worker_euid": payload.worker_euid,
            "lease_euid": payload.lease_euid,
            "dead_letter_euid": "DLQ-1",
            "replayed": False,
            "result": {"error_message": payload.error_message},
        }

    def place_execution_hold(self, payload, *, executed_by: str):
        return {
            "status": "held",
            "action_key": "hold",
            "subject_euid": payload.subject_euid,
            "worker_euid": payload.placed_by_worker_euid,
            "hold_euid": "HOLD-1",
            "replayed": False,
            "result": {"hold_code": payload.hold_code},
        }

    def release_execution_hold(self, payload, *, executed_by: str):
        return {
            "status": "released",
            "action_key": "release-hold",
            "worker_euid": payload.released_by_worker_euid,
            "hold_euid": payload.hold_euid,
            "replayed": False,
            "result": {},
        }

    def requeue_subject(self, payload, *, executed_by: str):
        return {
            "status": "requeued",
            "action_key": "requeue",
            "subject_euid": payload.subject_euid,
            "replayed": False,
            "result": {"queue_key": payload.queue_key},
        }

    def cancel_subject_execution(self, payload, *, executed_by: str):
        return {
            "status": "canceled",
            "action_key": "cancel",
            "subject_euid": payload.subject_euid,
            "replayed": False,
            "result": {"reason": payload.reason},
        }

    def expire_queue_lease(self, payload, *, executed_by: str):
        return {
            "status": "expired",
            "action_key": "expire-lease",
            "lease_euid": payload.lease_euid,
            "replayed": False,
            "result": {"reason": payload.reason},
        }


def test_execution_queue_router_lists_queues_and_registers_worker():
    app.dependency_overrides[require_api_auth] = _internal_rw_user
    worker_key = f"worker://pytest/{_opaque('worker')}"

    with TestClient(app) as client:
        queues = client.get("/api/v1/execution/queues")
        assert queues.status_code == 200, queues.text
        queue_keys = {item["queue_key"] for item in queues.json()}
        assert "extraction_prod" in queue_keys

        registered = client.post(
            "/api/v1/execution/actions/register-worker",
            json={
                "worker_key": worker_key,
                "display_name": "Pytest Execution Worker",
                "worker_type": "SERVICE",
                "status": "ONLINE",
                "capabilities": ["wetlab.extraction"],
                "max_concurrent_leases": 2,
                "heartbeat_ttl_seconds": 120,
            },
        )
        assert registered.status_code == 200, registered.text
        worker = registered.json()
        assert worker["worker_key"] == worker_key
        assert worker["capabilities"] == ["wetlab.extraction"]
        assert worker["max_concurrent_leases"] == 2

        workers = client.get("/api/v1/execution/workers")
        assert workers.status_code == 200, workers.text
        worker_keys = {item["worker_key"] for item in workers.json()}
        assert worker_key in worker_keys


def test_execution_queue_router_register_worker_requires_write_permission():
    app.dependency_overrides[require_api_auth] = _internal_ro_user

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/execution/actions/register-worker",
            json={
                "worker_key": f"worker://pytest/{_opaque('worker')}",
                "display_name": "Read Only Worker",
                "worker_type": "SERVICE",
                "status": "ONLINE",
            },
        )

    assert response.status_code == 403
    assert "Write permission required" in response.text


def test_execution_queue_router_maps_missing_queue_to_404():
    app.dependency_overrides[require_api_auth] = _internal_rw_user

    with TestClient(app) as client:
        response = client.get(f"/api/v1/execution/queues/{_opaque('missing-queue')}")

    assert response.status_code == 404
    assert "Queue not found" in response.text


def test_execution_queue_router_covers_remaining_runtime_routes(monkeypatch):
    app.dependency_overrides[require_api_auth] = _internal_admin_user
    monkeypatch.setattr(
        "bloom_lims.api.v1.execution_queue.ExecutionQueueService",
        _FakeExecutionQueueService,
    )

    with TestClient(app) as client:
        queue = client.get("/api/v1/execution/queues/extraction_prod")
        assert queue.status_code == 200, queue.text
        assert queue.json()["queue_key"] == "extraction_prod"

        queue_items = client.get("/api/v1/execution/queues/extraction_prod/items")
        assert queue_items.status_code == 200, queue_items.text
        assert queue_items.json()[0]["subject_euid"] == "SUBJ-1"

        subject = client.get("/api/v1/execution/subjects/SUBJ-1")
        assert subject.status_code == 200, subject.text
        assert subject.json()["subject_euid"] == "SUBJ-1"

        history = client.get("/api/v1/execution/subjects/SUBJ-1/history")
        assert history.status_code == 200, history.text
        assert history.json()["subject_euid"] == "SUBJ-1"

        worker = client.get("/api/v1/execution/workers/WORKER-1")
        assert worker.status_code == 200, worker.text
        assert worker.json()["worker_euid"] == "WORKER-1"

        leases = client.get("/api/v1/execution/leases?status=ACTIVE")
        assert leases.status_code == 200, leases.text
        assert leases.json()[0]["status"] == "ACTIVE"

        dead_letter = client.get("/api/v1/execution/dead-letter")
        assert dead_letter.status_code == 200, dead_letter.text
        assert dead_letter.json()[0]["dead_letter_euid"] == "DLQ-1"

        heartbeat = client.post(
            "/api/v1/execution/actions/heartbeat-worker",
            json={"worker_euid": "WORKER-1", "status": "ONLINE"},
        )
        assert heartbeat.status_code == 200, heartbeat.text
        assert heartbeat.json()["worker_euid"] == "WORKER-1"

        claim = client.post(
            "/api/v1/execution/actions/claim",
            json={
                "worker_euid": "WORKER-1",
                "queue_key": "extraction_prod",
                "subject_euid": "SUBJ-1",
                "idempotency_key": "idem-claim",
                "expected_state": "READY",
                "payload": {"priority": 1},
            },
        )
        assert claim.status_code == 200, claim.text
        assert claim.json()["action_key"] == "claim"

        renew = client.post(
            "/api/v1/execution/actions/renew-lease",
            json={
                "lease_euid": "LEASE-1",
                "worker_euid": "WORKER-1",
                "idempotency_key": "idem-renew",
            },
        )
        assert renew.status_code == 200, renew.text
        assert renew.json()["lease_euid"] == "LEASE-1"

        release = client.post(
            "/api/v1/execution/actions/release-lease",
            json={
                "lease_euid": "LEASE-1",
                "worker_euid": "WORKER-1",
                "idempotency_key": "idem-release",
                "reason": "handoff",
            },
        )
        assert release.status_code == 200, release.text
        assert release.json()["action_key"] == "release-lease"

        complete = client.post(
            "/api/v1/execution/actions/complete",
            json={
                "subject_euid": "SUBJ-1",
                "worker_euid": "WORKER-1",
                "lease_euid": "LEASE-1",
                "action_key": "extract",
                "expected_state": "RUNNING",
                "idempotency_key": "idem-complete",
                "result_payload": {"ok": True},
            },
        )
        assert complete.status_code == 200, complete.text
        assert complete.json()["status"] == "completed"

        fail = client.post(
            "/api/v1/execution/actions/fail",
            json={
                "subject_euid": "SUBJ-1",
                "worker_euid": "WORKER-1",
                "lease_euid": "LEASE-1",
                "action_key": "extract",
                "expected_state": "RUNNING",
                "idempotency_key": "idem-fail",
                "retryable": True,
                "error_message": "boom",
            },
        )
        assert fail.status_code == 200, fail.text
        assert fail.json()["dead_letter_euid"] == "DLQ-1"

        hold = client.post(
            "/api/v1/execution/actions/hold",
            json={
                "subject_euid": "SUBJ-1",
                "placed_by_worker_euid": "WORKER-1",
                "queue_key": "extraction_prod",
                "hold_code": "manual_review",
                "reason": "needs review",
                "idempotency_key": "idem-hold",
            },
        )
        assert hold.status_code == 200, hold.text
        assert hold.json()["hold_euid"] == "HOLD-1"

        release_hold = client.post(
            "/api/v1/execution/actions/release-hold",
            json={
                "hold_euid": "HOLD-1",
                "released_by_worker_euid": "WORKER-1",
                "idempotency_key": "idem-release-hold",
            },
        )
        assert release_hold.status_code == 200, release_hold.text
        assert release_hold.json()["action_key"] == "release-hold"

        requeue = client.post(
            "/api/v1/execution/actions/requeue",
            json={
                "subject_euid": "SUBJ-1",
                "queue_key": "extraction_prod",
                "idempotency_key": "idem-requeue",
                "expected_state": "FAILED_RETRYABLE",
            },
        )
        assert requeue.status_code == 200, requeue.text
        assert requeue.json()["status"] == "requeued"

        cancel = client.post(
            "/api/v1/execution/actions/cancel",
            json={
                "subject_euid": "SUBJ-1",
                "idempotency_key": "idem-cancel",
                "reason": "operator cancel",
            },
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == "canceled"

        expire = client.post(
            "/api/v1/execution/actions/expire-lease",
            json={
                "lease_euid": "LEASE-1",
                "idempotency_key": "idem-expire",
                "reason": "lease stale",
            },
        )
        assert expire.status_code == 200, expire.text
        assert expire.json()["status"] == "expired"
