from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

import bloom_lims.tapdb_adapter as tapdb_adapter
from bloom_lims.tapdb_adapter import generic_instance_lineage, generic_template
from bloom_lims.template_identity import instance_semantic_category


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


def test_instance_semantic_category_falls_back_to_parent_template():
    template = SimpleNamespace(json_addl={"semantic_category": "container"})
    instance = SimpleNamespace(json_addl={}, parent_template=template, category="BCN")

    assert instance_semantic_category(instance) == "container"


class _FakeTapdbConnection:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.transaction_context_connections: list[object] = []

    def install_transaction_context(self, connection) -> None:
        self.transaction_context_connections.append(connection)

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
            "server_port": "5566",
            "user": "tester",
            "password": "",
            "database": "tapdb_bloom_dev",
            "schema_name": "tapdb_bloom_tests_dev",
            "region": "us-west-2",
            "iam_auth": False,
            "allow_global_claims": True,
            "config_path": "/tmp/tapdb-bloom-tests.yaml",
        },
    )
    monkeypatch.setattr(tapdb_adapter, "TAPDBConnection", _factory)
    monkeypatch.setattr(
        tapdb_adapter, "maybe_install_engine_metrics", lambda *_args, **_kwargs: None
    )
    return holder


def test_bloomdb3_installs_tapdb_context_for_every_transaction(fake_tapdb):
    db = tapdb_adapter.BLOOMdb3(app_username="pytest@example.com")
    conn = fake_tapdb["conn"]

    assert conn.kwargs["schema_name"] == "tapdb_bloom_tests_dev"
    assert conn.kwargs["config_identity"].startswith("/")
    assert conn.kwargs["connection_role"] == "runtime"

    db.session.execute(text("CREATE TABLE receipts (value INTEGER NOT NULL)"))
    db.session.commit()
    db.session.execute(text("INSERT INTO receipts VALUES (1)"))
    db.session.commit()

    with pytest.raises(RuntimeError, match="rollback probe"):
        db.session.execute(text("INSERT INTO receipts VALUES (2)"))
        raise RuntimeError("rollback probe")
    db.session.rollback()

    assert db.session.execute(text("SELECT value FROM receipts")).scalars().all() == [1]
    assert len(conn.transaction_context_connections) == 4

    db.close()


def test_bloomdb3_new_session_gets_its_own_transaction_context(fake_tapdb):
    db = tapdb_adapter.BLOOMdb3(app_username="pytest@example.com")
    conn = fake_tapdb["conn"]

    new_session = db.new_session()
    new_session.execute(text("SELECT 1"))

    assert conn.transaction_context_connections == [new_session.connection()]

    new_session.close()
    db.close()
