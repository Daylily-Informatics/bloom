"""Scoped offline consumer checks; no database or external-service calls."""

import asyncio
from types import SimpleNamespace

import pytest

from bloom_lims import attribution as identities
from bloom_lims.request_db import RequestDatabaseMiddleware


def test_request_and_sync_dependency_share_identity_but_parallel_requests_do_not(monkeypatch):
    import bloom_lims.config
    monkeypatch.setattr(bloom_lims.config, "get_settings", lambda: SimpleNamespace(
        tapdb=SimpleNamespace(owner_repo_name="bloom")))
    observed = {}

    async def handler(scope, receive, send):
        await asyncio.to_thread(identities.verified_actor, kind="service",
                               issuer="test-token-authority", subject=scope["subject"])
        await asyncio.sleep(0)
        observed[scope["subject"]] = identities.current_attribution()

    async def run():
        app = RequestDatabaseMiddleware(handler)
        await asyncio.gather(*(app({"type": "http", "subject": name}, None, None)
                               for name in ("token-alpha", "token-beta")))
        assert identities._identity.get() is None

    asyncio.run(run())
    assert {value.actor_subject for value in observed.values()} == {"token-alpha", "token-beta"}
    assert len({value.request_id for value in observed.values()}) == 2


def test_failed_request_resets_identity(monkeypatch):
    import bloom_lims.config
    monkeypatch.setattr(bloom_lims.config, "get_settings", lambda: SimpleNamespace(
        tapdb=SimpleNamespace(owner_repo_name="bloom")))

    async def handler(scope, receive, send):
        identities.verified_actor(kind="human", issuer="test-authority", subject="opaque-person")
        raise ValueError("failure")

    with pytest.raises(ValueError, match="failure"):
        asyncio.run(RequestDatabaseMiddleware(handler)({"type": "http"}, None, None))
    assert identities._identity.get() is None


def test_anonymous_request_starts_without_an_actor():
    async def handler(scope, receive, send):
        assert identities.current_attribution() is None
    asyncio.run(RequestDatabaseMiddleware(handler)({"type": "http"}, None, None))


def test_empty_authority_set_still_requires_source_revision(monkeypatch):
    from bloom_lims import reference_preconditions as module
    db = SimpleNamespace(flush=lambda: None)
    monkeypatch.setattr(module, "ExternalReferenceService", lambda _db: SimpleNamespace(
        list_for_source=lambda *_a, **_kw: {"items": [], "page": {"next_cursor": None}}))
    result = module.authority_preconditions(db, SimpleNamespace(record_revision=0), "test-authority")
    assert result == {"expected_source_revision": 0, "expected_lineage_revisions": {}}


def test_sync_background_tasks_keep_actor_snapshot_and_clear_reused_thread():
    from daylily_tapdb.security_context import Attribution
    from bloom_lims.core.async_operations import BackgroundTaskManager

    async def run():
        manager = BackgroundTaskManager(max_workers=1)
        try:
            jobs = []
            for subject in ("first-actor", "second-actor"):
                value = Attribution("human", "test-authority", subject, "bloom", subject, subject)
                with identities.explicit_attribution(value):
                    jobs.append(await manager.submit(identities.current_attribution))
            with identities.explicit_attribution(None):
                jobs.append(await manager.submit(identities.current_attribution))
            results = [await manager.get_result(job, timeout=2) for job in jobs]
            assert [result.result.actor_subject for result in results[:2]] == ["first-actor", "second-actor"]
            assert results[2].result is None
        finally:
            await manager.shutdown()

    asyncio.run(run())


def test_batch_writers_authenticate_before_background_dispatch():
    from bloom_lims.api.v1.batch import router
    from bloom_lims.api.v1.dependencies import require_write

    writers = [route for route in router.routes if route.path in
               {"/batch/create", "/batch/update", "/batch/delete"}]
    assert len(writers) == 3
    assert all(any(dependency.call is require_write for dependency in route.dependant.dependencies)
               for route in writers)


def test_equipment_writers_require_verified_write_identity():
    from bloom_lims.api.v1.equipment import router
    from bloom_lims.api.v1.dependencies import require_write

    writers = [route for route in router.routes if "POST" in route.methods]
    assert len(writers) == 2
    assert all(any(dependency.call is require_write for dependency in route.dependant.dependencies)
               for route in writers)
