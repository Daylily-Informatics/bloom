"""
Graph viewer route/API contract tests (mocked, no live DB dependency).
"""

import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

from main import app, require_auth


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


class _DummyDB:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _FakeTemplate:
    pass


class _FakeLineage:
    parent_instance_uuid = "parent_instance_uuid"
    child_instance_uuid = "child_instance_uuid"
    relationship_type = "relationship_type"
    is_deleted = "is_deleted"


class _FakeInstance:
    euid = "euid"
    is_deleted = "is_deleted"
    uuid = "uuid"


def _fake_bobj_for_object_detail(euid: str = "CX-TEST"):
    fake_instance = _FakeInstance()
    fake_instance.uuid = "uuid-1"
    fake_instance.euid = euid
    fake_instance.name = "Test Container"
    fake_instance.type = "tube"
    fake_instance.category = "container"
    fake_instance.subtype = "tube-generic"
    fake_instance.version = "1.0"
    fake_instance.bstatus = "active"
    fake_instance.json_addl = {"properties": {"name": "Test Container"}}
    fake_instance.created_dt = datetime(2026, 3, 2, 12, 0, 0)
    fake_instance.modified_dt = datetime(2026, 3, 2, 12, 10, 0)

    fake_bobj = MagicMock()
    fake_bobj.get_by_euid.return_value = fake_instance
    fake_bobj.Base = SimpleNamespace(
        classes=SimpleNamespace(
            generic_template=_FakeTemplate,
            generic_instance_lineage=_FakeLineage,
            generic_instance=_FakeInstance,
        )
    )
    return fake_bobj


def _fake_bobj_for_lineage_create(existing_lineage=False):
    parent_obj = SimpleNamespace(uuid="parent-uuid", euid="PARENT-1")
    child_obj = SimpleNamespace(uuid="child-uuid", euid="CHILD-1")
    found_existing = SimpleNamespace(uuid="lineage-existing") if existing_lineage else None

    class _FakeQuery:
        def __init__(self, value):
            self._value = value

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self._value

    class _FakeSession:
        def __init__(self):
            self._instance_calls = 0
            self.committed = False
            self.rolled_back = False

        def query(self, cls):
            if cls is _FakeInstance:
                self._instance_calls += 1
                if self._instance_calls == 1:
                    return _FakeQuery(parent_obj)
                return _FakeQuery(child_obj)
            return _FakeQuery(found_existing)

        def flush(self):
            return None

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    fake_bobj = MagicMock()
    fake_bobj.session = _FakeSession()
    fake_bobj.Base = SimpleNamespace(
        classes=SimpleNamespace(
            generic_template=_FakeTemplate,
            generic_instance_lineage=_FakeLineage,
            generic_instance=_FakeInstance,
        )
    )
    fake_bobj.create_generic_instance_lineage_by_euids.return_value = SimpleNamespace(
        euid="LN-NEW",
        uuid="ln-uuid-1",
    )
    return fake_bobj


def _fake_bobj_for_delete():
    obj = SimpleNamespace(euid="DEL-1")

    class _FakeSession:
        def __init__(self):
            self.committed = False

        def flush(self):
            return None

        def commit(self):
            self.committed = True

        def rollback(self):
            return None

    fake_bobj = MagicMock()
    fake_bobj.get_by_euid.return_value = obj
    fake_bobj.session = _FakeSession()
    return fake_bobj


class TestGraphViewerRoutes:
    def test_dindex2_renders_graph_bootstrap(self, client):
        response = client.get("/dindex2?globalStartNodeEUID=AY1&globalFilterLevel=4")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "/static/js/graph.js" in response.text
        assert "id=\"start-euid\"" in response.text
        assert "id=\"search-query\"" in response.text
        assert "id=\"transparency-slider\"" in response.text
        assert "id=\"distance-slider\"" in response.text
        assert "I + left click node" in response.text
        assert "initGraphPage()" in response.text

    def test_graph_alias_redirects_to_dindex2(self, client):
        response = client.get("/graph?start_euid=AY1&depth=3", follow_redirects=False)
        assert response.status_code == 307
        location = response.headers["location"]
        assert location.startswith("/dindex2?")
        assert "globalStartNodeEUID=AY1" in location
        assert "globalFilterLevel=3" in location


class TestGraphViewerApis:
    def test_api_graph_data_returns_elements(self, client):
        fake_nodes = [{"data": {"id": "N1", "category": "container", "color": "#8B00FF"}}]
        fake_edges = [{"data": {"id": "E1", "source": "N1", "target": "N2"}}]
        fake_bobj = MagicMock()

        with patch("main.BLOOMdb3", _DummyDB), patch("main.BloomObj", return_value=fake_bobj), patch(
            "main._build_graph_elements_for_start", return_value=(fake_nodes, fake_edges)
        ):
            response = client.get("/api/graph/data?start_euid=AY1&depth=3")

        assert response.status_code == 200
        payload = response.json()
        assert payload["elements"]["nodes"] == fake_nodes
        assert payload["elements"]["edges"] == fake_edges
        assert payload["meta"]["start_euid"] == "AY1"
        assert payload["meta"]["depth"] == 3

    def test_api_graph_data_unknown_start_is_safe(self, client):
        fake_bobj = MagicMock()
        with patch("main.BLOOMdb3", _DummyDB), patch("main.BloomObj", return_value=fake_bobj), patch(
            "main._build_graph_elements_for_start", return_value=([], [])
        ):
            response = client.get("/api/graph/data?start_euid=ZZZ-NONEXISTENT&depth=3")

        assert response.status_code == 200
        payload = response.json()
        assert payload["elements"]["nodes"] == []
        assert payload["elements"]["edges"] == []

    def test_api_object_detail_returns_payload(self, client):
        fake_bobj = _fake_bobj_for_object_detail("CX-TEST")
        with patch("main.BLOOMdb3", _DummyDB), patch("main.BloomObj", return_value=fake_bobj):
            response = client.get("/api/object/CX-TEST")

        assert response.status_code == 200
        payload = response.json()
        assert payload["euid"] == "CX-TEST"
        assert payload["category"] == "container"
        assert payload["type"] == "instance"

    def test_api_lineage_rejects_non_admin(self, client):
        def _non_admin_auth():
            return {"email": "john@daylilyinformatics.com", "role": "user"}

        app.dependency_overrides[require_auth] = _non_admin_auth
        try:
            response = client.post(
                "/api/lineage",
                json={"parent_euid": "PARENT-1", "child_euid": "CHILD-1", "relationship_type": "generic"},
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_api_lineage_admin_create_success(self, client):
        fake_bobj = _fake_bobj_for_lineage_create(existing_lineage=False)
        with patch("main.BLOOMdb3", _DummyDB), patch("main.BloomObj", return_value=fake_bobj):
            response = client.post(
                "/api/lineage",
                json={"parent_euid": "PARENT-1", "child_euid": "CHILD-1", "relationship_type": "generic"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["euid"] == "LN-NEW"

    def test_api_lineage_duplicate_returns_409(self, client):
        fake_bobj = _fake_bobj_for_lineage_create(existing_lineage=True)
        with patch("main.BLOOMdb3", _DummyDB), patch("main.BloomObj", return_value=fake_bobj):
            response = client.post(
                "/api/lineage",
                json={"parent_euid": "PARENT-1", "child_euid": "CHILD-1", "relationship_type": "generic"},
            )
        assert response.status_code == 409

    def test_api_object_delete_rejects_non_admin(self, client):
        def _non_admin_auth():
            return {"email": "john@daylilyinformatics.com", "role": "user"}

        app.dependency_overrides[require_auth] = _non_admin_auth
        try:
            response = client.delete("/api/object/DEL-1")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_api_object_delete_admin_soft_delete(self, client):
        fake_bobj = _fake_bobj_for_delete()
        with patch("main.BLOOMdb3", _DummyDB), patch("main.BloomObj", return_value=fake_bobj):
            response = client.delete("/api/object/DEL-1")

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["hard_delete_applied"] is False
