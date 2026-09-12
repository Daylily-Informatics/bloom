"""Dashboard parity checks using a small, synthetic in-memory database."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    create_engine,
    event,
)
from sqlalchemy.orm import Session, declarative_base

from bloom_lims.dashboard_queries import queue_summary, recent_instances

Base = declarative_base()


class DashboardRow(Base):
    __tablename__ = "dashboard_rows"
    uid = Column(Integer, primary_key=True)
    euid = Column(String, nullable=True)
    name = Column(String)
    category = Column(String)
    type = Column(String)
    subtype = Column(String)
    bstatus = Column(String)
    created_dt = Column(DateTime)
    is_deleted = Column(Boolean, default=False)
    json_addl = Column(JSON)


@pytest.fixture
def dashboard_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    statements = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _conn, _cursor, statement, *_: statements.append(statement),
    )
    with Session(engine) as session:
        yield SimpleNamespace(
            session=session,
            Base=SimpleNamespace(
                classes=SimpleNamespace(generic_instance=DashboardRow)
            ),
            statements=statements,
        )
    engine.dispose()


def test_summary_preserves_counts_normalization_and_deleted_filter(dashboard_db):
    rows = [
        ("queue_definition", " active ", False),
        ("\tqueue_definition\n", "IN_PROGRESS", False),
        ("\u2003queue_definition\u2003", "completed", False),
        ("queue_definition", "Failed", False),
        ("queue_definition", "active", True),
        ("beta_work_item", "OPEN", False),
        (" beta_work_item ", "active", False),
        ("beta_work_item", "completed", False),
        ("beta_work_item", "active", True),
        (None, None, False),
        ("unrelated", "active", False),
    ]
    dashboard_db.session.add_all(
        DashboardRow(
            name=f"Synthetic row {index}",
            bstatus=status,
            is_deleted=deleted,
            json_addl={"properties": {"beta_kind": kind}, "unused": "x" * 4000},
        )
        for index, (kind, status, deleted) in enumerate(rows)
    )
    dashboard_db.session.commit()
    result = queue_summary(dashboard_db)
    assert result == {
        "objects_total": 9,
        "queue_runtime_total": 4,
        "queue_runtime_in_progress": 2,
        "queue_runtime_complete": 1,
        "queue_runtime_exception": 1,
        "workflows_total": 3,
        "workflows_active": 2,
        "queue_kinds": [
            "\tqueue_definition\n",
            "queue_definition",
            "\u2003queue_definition\u2003",
        ],
        "work_item_kinds": [" beta_work_item ", "beta_work_item"],
    }


def test_recent_rows_are_bounded_and_do_not_load_metadata(dashboard_db):
    origin = datetime(2025, 1, 1)
    dashboard_db.session.add_all(
        DashboardRow(
            name=f"Synthetic row {index}",
            created_dt=origin + timedelta(days=index),
            is_deleted=index == 8,
            json_addl={
                "properties": {
                    "beta_kind": "queue_definition" if index < 9 else "unrelated"
                },
                "unused": "x" * 4000,
            },
        )
        for index in range(12)
    )
    dashboard_db.session.commit()
    dashboard_db.statements.clear()
    rows = recent_instances(dashboard_db, beta_kinds=["queue_definition"])
    assert [row.name for row in rows] == [f"Synthetic row {i}" for i in range(7, 2, -1)]
    assert len(dashboard_db.statements) == 1
    statement = dashboard_db.statements[0]
    assert "json_addl" not in statement.split("FROM", 1)[0]
    assert "LIMIT" in statement
    dashboard_db.session.close()
    assert rows[0].name == "Synthetic row 7"


def test_empty_kind_selection_does_not_query(dashboard_db):
    dashboard_db.statements.clear()
    assert recent_instances(dashboard_db, beta_kinds=[]) == []
    assert dashboard_db.statements == []
