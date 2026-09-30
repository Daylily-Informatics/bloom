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
