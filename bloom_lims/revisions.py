"""Observed TapDB revisions for every service-owned ORM writer.

Snapshots precede native refresh, and observations survive DTO conversion and
identity-map eviction. A successful flush advances only its own written records.
A conflict fences this session; outer boundaries roll back after ORM unwinds.
"""
from copy import deepcopy

from sqlalchemy import event, inspect
from daylily_tapdb import generic_instance, generic_instance_lineage, generic_template
from daylily_tapdb.revisions import RevisionConflict, lock_records, require_revision

_RECORDS = (generic_instance, generic_instance_lineage, generic_template)
_OBSERVED = "native_observed_revisions"
_CONFLICT = "native_revision_conflict"
_PENDING = "native_written_records"
_HISTORY = "native_revision_write_history"
_MISSING = object()


def _key(obj):
    return (obj.__table__.name, obj.uid)


def _observe(session, obj):
    if isinstance(obj, _RECORDS):
        session.info.setdefault(_OBSERVED, {}).setdefault(_key(obj), obj.record_revision)


def reject_failed_session(session, *_args):
    from bloom_lims.attribution import current_revision_conflict
    conflict = session.info.get(_CONFLICT) or current_revision_conflict()
    if conflict:
        raise RevisionConflict(conflict)


def guard_pending_revisions(session, _flush_context, _instances):
    reject_failed_session(session)
    observed = session.info.setdefault(_OBSERVED, {})
    changed = set(session.dirty) | set(session.deleted)
    proposals = []
    for obj in changed:
        if not isinstance(obj, _RECORDS):
            continue
        state = inspect(obj)
        if not state.persistent:
            continue
        if obj not in session.deleted and not session.is_modified(obj, include_collections=False):
            continue
        changes = {attr.key: deepcopy(getattr(obj, attr.key))
                   for attr in state.mapper.column_attrs
                   if state.attrs[attr.key].history.has_changes()}
        if "record_revision" in changes:
            raise ValueError("TapDB record_revision is server-owned and cannot be assigned")
        if _key(obj) not in observed:
            raise RuntimeError("Persisted TapDB mutation lacks its original revision observation")
        proposals.append((obj, observed[_key(obj)], changes))
    # Native lineage locking may refresh an endpoint without writing it. Only
    # actual proposals and inserted rows may advance their observed revisions.
    session.info[_PENDING] = (
        [obj for obj in session.new if isinstance(obj, _RECORDS)]
        + [obj for obj, _, _ in proposals]
    )
    if not proposals:
        return
    try:
        with session.no_autoflush:
            lock_records(session, [obj for obj, _, _ in proposals])
            for obj, expected, _ in proposals:
                require_revision(obj, expected)
            for obj, _, changes in proposals:
                for name, value in changes.items():
                    setattr(obj, name, value)
    except RevisionConflict as exc:
        message = str(exc)
        # No failed proposal or other pending work may later be committed by a
        # legacy catch-and-continue path, even after an explicit rollback.
        session.info[_CONFLICT] = message
        from bloom_lims.attribution import record_revision_conflict
        record_revision_conflict(message, session)
        raise


def _advance_written_revisions(session, _flush_context):
    observed = session.info.setdefault(_OBSERVED, {})
    for obj in session.info.pop(_PENDING, []):
        transaction = session.get_nested_transaction() or session.get_transaction()
        while transaction is not None:
            history = session.info.setdefault(_HISTORY, {}).setdefault(transaction, {})
            history.setdefault(_key(obj), observed.get(_key(obj), _MISSING))
            transaction = transaction.parent
        if inspect(obj).persistent:
            observed[_key(obj)] = obj.record_revision
        else:
            observed.pop(_key(obj), None)


def _restore_rolled_back_observations(session, transaction):
    observed = session.info.setdefault(_OBSERVED, {})
    for key, previous in session.info.get(_HISTORY, {}).pop(transaction, {}).items():
        if previous is _MISSING:
            observed.pop(key, None)
        else:
            observed[key] = previous
    session.info.pop(_PENDING, None)


def _forget_committed_history(session):
    if not session.in_nested_transaction():
        session.info.pop(_HISTORY, None)


def _reject_bulk_writes(state):
    if (state.is_update or state.is_delete) and getattr(
        getattr(state.statement, "table", None), "name", None
    ) in {model.__table__.name for model in _RECORDS}:
        raise RuntimeError("TapDB writes must use observed ORM records or native CAS operations")


def install_revision_guard(session):
    event.listen(session, "loaded_as_persistent", _observe)
    event.listen(session, "before_flush", guard_pending_revisions)
    event.listen(session, "after_flush_postexec", _advance_written_revisions)
    event.listen(session, "before_commit", reject_failed_session)
    event.listen(session, "do_orm_execute", _reject_bulk_writes)
    event.listen(session, "after_soft_rollback", _restore_rolled_back_observations)
    event.listen(session, "after_commit", _forget_committed_history)


async def run_with_revision_response(app, scope, receive, send):
    from starlette.responses import JSONResponse
    from bloom_lims.attribution import current_revision_conflict, rollback_conflicted_sessions

    started = False
    replaced = False

    async def guarded_send(message):
        nonlocal started, replaced
        if message["type"] == "http.response.start":
            conflict = current_revision_conflict()
            started = True
            if conflict:
                rollback_conflicted_sessions()
                replaced = True
                await JSONResponse(status_code=409, content={
                    "detail": conflict, "error": "revision_conflict",
                })(scope, receive, send)
                return
        if not replaced:
            await send(message)

    try:
        await app(scope, receive, guarded_send)
    except Exception:
        conflict = current_revision_conflict()
        if conflict and not started:
            rollback_conflicted_sessions()
            await JSONResponse(status_code=409, content={
                "detail": conflict, "error": "revision_conflict",
            })(scope, receive, send)
        else:
            raise


def expect_revision(session, obj, expected_revision: int) -> None:
    """Carry a DTO's original observation into a later mutation session."""
    reject_failed_session(session)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("An explicit nonnegative observed record revision is required")
    session.info.setdefault(_OBSERVED, {})[_key(obj)] = expected_revision
