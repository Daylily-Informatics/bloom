from __future__ import annotations

import pytest

import bloom_lims.tapdb_adapter as tapdb_adapter
from bloom_lims.tapdb_adapter import generic_instance_lineage, generic_template


def test_template_exposes_only_canonical_uid_attribute():
    assert generic_template.uid.property.columns[0].name == "uid"
    assert not hasattr(generic_template, "uuid")


def test_lineage_exposes_only_canonical_uid_fk_attributes():
    assert (
        generic_instance_lineage.parent_instance_uid.property.columns[0].name
        == "parent_instance_uid"
    )
    assert not hasattr(generic_instance_lineage, "parent_instance_uuid")
    assert not hasattr(generic_instance_lineage, "child_instance_uuid")


class _FakeSession:
    def __init__(self) -> None:
        self.executed: list[tuple[object, dict[str, str]]] = []

    def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))

    def close(self) -> None:
        return None


class _FakeTapdbConnection:
    def __init__(self, **_kwargs) -> None:
        self.engine = object()
        self._Session = self._raw_session
        self.get_session_calls = 0
        self.sessions: list[_FakeSession] = []

    def _raw_session(self):
        raise AssertionError("BLOOMdb3 must use TAPDBConnection.get_session()")

    def get_session(self):
        self.get_session_calls += 1
        session = _FakeSession()
        self.sessions.append(session)
        return session

    def close(self) -> None:
        return None


@pytest.fixture
def fake_tapdb(monkeypatch: pytest.MonkeyPatch) -> _FakeTapdbConnection:
    holder: dict[str, _FakeTapdbConnection] = {}

    def _factory(**kwargs):
        conn = _FakeTapdbConnection(**kwargs)
        holder["conn"] = conn
        return conn

    monkeypatch.setattr(
        tapdb_adapter,
        "get_tapdb_db_config",
        lambda: {
            "engine_type": "local",
            "host": "localhost",
            "port": "5566",
            "user": "tester",
            "password": "",
            "database": "tapdb_bloom_dev",
        },
    )
    monkeypatch.setattr(tapdb_adapter, "TAPDBConnection", _factory)
    monkeypatch.setattr(tapdb_adapter, "maybe_install_engine_metrics", lambda *_args, **_kwargs: None)
    return holder


def test_bloomdb3_bootstraps_sessions_via_tapdb_connection(fake_tapdb):
    db = tapdb_adapter.BLOOMdb3(app_username="pytest@example.com")
    conn = fake_tapdb["conn"]

    assert conn.get_session_calls == 1
    assert db.session is conn.sessions[0]
    assert conn.sessions[0].executed[-1][1] == {
        "username": "pytest@example.com"
    }

    db.close()


def test_bloomdb3_new_session_uses_tapdb_prepared_session(fake_tapdb):
    db = tapdb_adapter.BLOOMdb3(app_username="pytest@example.com")
    conn = fake_tapdb["conn"]

    new_session = db.new_session()

    assert conn.get_session_calls == 2
    assert new_session is conn.sessions[-1]
    assert new_session.executed[-1][1] == {"username": "pytest@example.com"}

    db.close()
