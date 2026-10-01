"""Offline transaction contract cases; authored, not executed for fleet rollout."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from daylily_tapdb.revisions import RevisionConflict
from bloom_lims import revisions as guard


class Record:
    __table__ = SimpleNamespace(name="generic_instance")

    def __init__(self, uid, revision, name):
        self.uid, self.record_revision, self.name = uid, revision, name


class Session:
    def __init__(self, *records):
        self.info, self.dirty, self.deleted, self.new = {}, set(records), set(), set()
        self.no_autoflush = nullcontext()
        self.rolled_back = False
        self.transaction = SimpleNamespace(parent=None)

    def get_nested_transaction(self):
        return None

    def get_transaction(self):
        return None

    def is_modified(self, obj, include_collections=False):
        return True

    def rollback(self):
        self.rolled_back = True
        self.dirty.clear()


def install_fakes(monkeypatch):
    monkeypatch.setattr(guard, "_RECORDS", (Record,))
    monkeypatch.setattr(guard, "inspect", lambda obj: SimpleNamespace(
        persistent=True,
        mapper=SimpleNamespace(column_attrs=[SimpleNamespace(key="name")]),
        attrs={"name": SimpleNamespace(history=SimpleNamespace(has_changes=lambda: True))},
    ))


def test_all_proposals_survive_native_refresh_and_own_flush_advances_observation(monkeypatch):
    install_fakes(monkeypatch)
    first, second = Record(1, 2, "first proposal"), Record(2, 8, "second proposal")
    session = Session(first, second)
    guard._observe(session, first)
    guard._observe(session, second)

    def lock(_session, rows):
        for row in rows:
            row.name = "persisted value"

    monkeypatch.setattr(guard, "lock_records", lock)
    guard.guard_pending_revisions(session, None, None)
    assert (first.name, second.name) == ("first proposal", "second proposal")
    first.record_revision, second.record_revision = 3, 9
    guard._advance_written_revisions(session, None)
    assert session.info[guard._OBSERVED][guard._key(first)] == 3
    guard.guard_pending_revisions(session, None, None)
    assert not session.rolled_back


def test_evicted_or_refreshed_object_keeps_original_revision_and_conflict_fences_session(monkeypatch):
    install_fakes(monkeypatch)
    original = Record(1, 2, "original read")
    replacement = Record(1, 3, "stale DTO proposal")
    session = Session(replacement)
    guard._observe(session, original)
    guard._observe(session, replacement)
    monkeypatch.setattr(guard, "lock_records", lambda *_args: None)
    with pytest.raises(RevisionConflict):
        guard.guard_pending_revisions(session, None, None)
    session.rollback()
    assert session.rolled_back
    with pytest.raises(RevisionConflict):
        guard.reject_failed_session(session)


def test_unwritten_endpoint_refresh_does_not_advance_original_observation(monkeypatch):
    install_fakes(monkeypatch)

    class Lineage(Record):
        __table__ = SimpleNamespace(name="generic_instance_lineage")

    endpoint = Record(1, 1, "unchanged endpoint")
    lineage = Lineage(2, 5, "lineage proposal")
    session = Session(endpoint, lineage)
    guard._observe(session, endpoint)
    guard._observe(session, lineage)
    monkeypatch.setattr(session, "is_modified", lambda obj, **_kwargs: obj is lineage)

    def lock_lineage_and_endpoint(_session, rows):
        assert rows == [lineage]
        endpoint.record_revision = 2
        endpoint.name = "concurrent endpoint change"

    monkeypatch.setattr(guard, "lock_records", lock_lineage_and_endpoint)
    guard.guard_pending_revisions(session, None, None)
    assert session.info[guard._PENDING] == [lineage]
    lineage.record_revision = 6
    guard._advance_written_revisions(session, None)
    assert session.info[guard._OBSERVED][guard._key(endpoint)] == 1
    assert session.info[guard._OBSERVED][guard._key(lineage)] == 6

    session.dirty = {endpoint}
    endpoint.name = "proposal from original endpoint read"
    monkeypatch.setattr(session, "is_modified", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(guard, "lock_records", lambda *_args: None)
    with pytest.raises(RevisionConflict, match="expected 1, current 2"):
        guard.guard_pending_revisions(session, None, None)


def test_explicit_dto_revision_survives_new_session(monkeypatch):
    install_fakes(monkeypatch)
    row = Record(1, 12, "proposal from revision 10")
    session = Session(row)
    guard._observe(session, row)
    guard.expect_revision(session, row, 10)
    monkeypatch.setattr(guard, "lock_records", lambda *_args: None)
    with pytest.raises(RevisionConflict):
        guard.guard_pending_revisions(session, None, None)
    assert session.info[guard._CONFLICT]


def test_rollback_restores_revision_before_own_flush(monkeypatch):
    install_fakes(monkeypatch)
    row = Record(1, 2, "proposal")
    session = Session(row)
    transaction = type("Transaction", (), {"parent": None})()
    monkeypatch.setattr(session, "get_transaction", lambda: transaction)
    guard._observe(session, row)
    session.info[guard._PENDING] = [row]
    row.record_revision = 3
    guard._advance_written_revisions(session, None)
    guard._restore_rolled_back_observations(session, transaction)
    assert session.info[guard._OBSERVED][guard._key(row)] == 2


def test_swallowed_conflict_is_409_and_does_not_leak_to_next_request():
    import asyncio
    from bloom_lims.attribution import record_revision_conflict
    from bloom_lims.request_db import RequestDatabaseMiddleware

    async def handler(scope, receive, send):
        if scope["conflict"]:
            record_revision_conflict("stale revision")
        await send({"type": "http.response.start", "status": 500 if scope["conflict"] else 200,
                    "headers": []})
        await send({"type": "http.response.body", "body": b"result"})

    async def run():
        app = RequestDatabaseMiddleware(handler)
        statuses = []
        async def send(message):
            if message["type"] == "http.response.start":
                statuses.append(message["status"])
        for conflict in (True, False):
            await app({"type": "http", "conflict": conflict}, None, send)
        assert statuses == [409, 200]

    asyncio.run(run())


def test_batch_conflict_marks_the_original_job_failed_with_409():
    import asyncio
    from bloom_lims.core.batch_operations import BatchProcessor, JobStatus, _batch_jobs, _batch_cancel_flags

    class FailedSession:
        def query(self, *_args):
            raise RevisionConflict("stale batch item")
        def rollback(self):
            pass

    processor = BatchProcessor(SimpleNamespace(
        session=FailedSession(), Base=SimpleNamespace(classes=SimpleNamespace(generic_instance=object)),
    ))
    job = processor.create_job("bulk_update", 1)
    try:
        result = asyncio.run(processor.bulk_update_objects([{"euid": "test-object"}], job=job))
        assert result is job and _batch_jobs[job.job_id] is job
        assert job.status is JobStatus.FAILED and job.error_code == 409
    finally:
        _batch_jobs.pop(job.job_id, None)
        _batch_cancel_flags.pop(job.job_id, None)
