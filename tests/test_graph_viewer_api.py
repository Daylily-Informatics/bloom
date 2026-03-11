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

from main import _build_graph_elements_for_start, app, require_auth


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
    parent_instance_uid = "parent_instance_uid"
    child_instance_uid = "child_instance_uid"
    relationship_type = "relationship_type"
    is_deleted = "is_deleted"


class _FakeInstance:
    euid = "euid"
    is_deleted = "is_deleted"
    uid = "uid"


class _FakeExternalRef:
    def __init__(self, **payload):
        self.payload = payload

    def to_public_dict(self, *, ref_index: int):
        return {"ref_index": ref_index, **self.payload}


def _fake_bobj_for_object_detail(euid: str = "CX-TEST"):
    fake_instance = _FakeInstance()
    fake_instance.uid = 101
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
    parent_obj = SimpleNamespace(uid=11, euid="PARENT-1")
    child_obj = SimpleNamespace(uid=22, euid="CHILD-1")
    found_existing = SimpleNamespace(euid="LN-EXISTING") if existing_lineage else None

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
        response = client.get("/dindex2?start_euid=AY1&depth=4")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "/static/js/graph.js" in response.text
        assert "id=\"start-euid\"" in response.text
        assert "id=\"search-query\"" in response.text
        assert "id=\"transparency-slider\"" in response.text
        assert "id=\"distance-slider\"" in response.text
        assert "id=\"type-checkboxes\"" in response.text
        assert "I + left click node" in response.text
        assert "initGraphPage()" in response.text

    def test_graph_alias_route_removed(self, client):
        response = client.get("/graph?start_euid=AY1&depth=3", follow_redirects=False)
        assert response.status_code == 404


class TestGraphViewerApis:
    def test_build_graph_elements_emits_canonical_node_keys(self):
        fake_bobj = MagicMock()
        fake_bobj.fetch_graph_data_by_node_depth.return_value = [
            (
                "CX-1",  # euid
                None,
                "Sample Tube",
                "tube",  # type
                "container",  # category
                "tube-generic",  # subtype
                "1.0",  # version
                None,
                "LN-1",  # lineage_euid
                "WX-1",  # parent
                "CX-1",  # child
                "generic",  # relationship_type
            )
        ]

        nodes, _edges = _build_graph_elements_for_start(fake_bobj, "CX-1", 3)
        assert nodes
        node_data = nodes[0]["data"]
        assert node_data["type"] == "tube"
        assert node_data["category"] == "container"
        assert node_data["subtype"] == "tube-generic"
        assert "btype" not in node_data
        assert "b_sub_type" not in node_data

    def test_api_graph_data_returns_elements(self, client):
        fake_nodes = [{"data": {"id": "N1", "category": "container", "color": "#8B00FF"}}]
        fake_edges = [{"data": {"id": "E1", "source": "N1", "target": "N2"}}]
        fake_bobj = MagicMock()

        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ), patch(
            "bloom_lims.gui.routes.graph._build_graph_elements_for_start",
            return_value=(fake_nodes, fake_edges),
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
        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ), patch(
            "bloom_lims.gui.routes.graph._build_graph_elements_for_start", return_value=([], [])
        ):
            response = client.get("/api/graph/data?start_euid=ZZZ-NONEXISTENT&depth=3")

        assert response.status_code == 200
        payload = response.json()
        assert payload["elements"]["nodes"] == []
        assert payload["elements"]["edges"] == []

    def test_api_object_detail_returns_payload(self, client):
        fake_bobj = _fake_bobj_for_object_detail("CX-TEST")
        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ):
            response = client.get("/api/object/CX-TEST")

        assert response.status_code == 200
        payload = response.json()
        assert payload["euid"] == "CX-TEST"
        assert payload["category"] == "container"
        assert payload["type"] == "instance"
        assert "uuid" not in payload
        assert "btype" not in payload
        assert "b_sub_type" not in payload

    def test_api_object_detail_includes_external_refs(self, client):
        fake_bobj = _fake_bobj_for_object_detail("CX-TEST")
        refs = [
            _FakeExternalRef(
                label="atlas:patient:AT-PAT-1",
                system="atlas",
                root_euid="AT-PAT-1",
                tenant_id="atlas-tenant-1",
                href="https://atlas.local/graph?start_euid=AT-PAT-1&depth=4",
                graph_expandable=True,
            )
        ]
        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ), patch(
            "bloom_lims.graph_support.resolve_external_refs_for_object",
            return_value=refs,
        ):
            response = client.get("/api/object/CX-TEST")

        assert response.status_code == 200
        payload = response.json()
        assert payload["external_refs"] == [
            {
                "label": "atlas:patient:AT-PAT-1",
                "system": "atlas",
                "root_euid": "AT-PAT-1",
                "tenant_id": "atlas-tenant-1",
                "href": "https://atlas.local/graph?start_euid=AT-PAT-1&depth=4",
                "graph_expandable": True,
                "ref_index": 0,
            }
        ]

    def test_api_external_graph_namespaces_remote_graph(self, client):
        fake_bobj = _fake_bobj_for_object_detail("CX-TEST")
        fake_ref = SimpleNamespace(
            root_euid="AT-PAT-1",
            tenant_id="atlas-tenant-1",
            graph_expandable=True,
            reason=None,
            system="atlas",
        )
        fake_service = SimpleNamespace(
            client=SimpleNamespace(
                get_graph_data=lambda **_kwargs: {
                    "elements": {
                        "nodes": [{"data": {"id": "AT-PAT-1", "euid": "AT-PAT-1", "category": "atlas", "color": "#123456"}}],
                        "edges": [{"data": {"id": "AT-LIN-1", "source": "AT-CH-1", "target": "AT-PAT-1"}}],
                    }
                }
            )
        )
        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ), patch(
            "bloom_lims.gui.routes.graph.resolve_external_ref_by_index",
            return_value=fake_ref,
        ), patch(
            "bloom_lims.gui.routes.graph.AtlasService",
            return_value=fake_service,
        ):
            response = client.get("/api/graph/external?source_euid=CX-TEST&ref_index=0&depth=3")

        assert response.status_code == 200
        body = response.json()
        assert body["elements"]["nodes"][0]["data"]["id"] == "ext::atlas::atlas-tenant-1::AT-PAT-1"
        assert body["elements"]["nodes"][0]["data"]["is_external"] is True
        assert body["elements"]["edges"][-1]["data"]["is_external_bridge"] is True

    def test_api_external_graph_object_proxies_remote_detail(self, client):
        fake_bobj = _fake_bobj_for_object_detail("CX-TEST")
        fake_ref = SimpleNamespace(
            root_euid="AT-PAT-1",
            tenant_id="atlas-tenant-1",
            graph_expandable=True,
            reason=None,
            system="atlas",
        )
        fake_service = SimpleNamespace(
            client=SimpleNamespace(
                get_graph_object_detail=lambda **_kwargs: {"euid": "AT-PAT-1", "external_refs": []}
            )
        )
        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ), patch(
            "bloom_lims.gui.routes.graph.resolve_external_ref_by_index",
            return_value=fake_ref,
        ), patch(
            "bloom_lims.gui.routes.graph.AtlasService",
            return_value=fake_service,
        ):
            response = client.get(
                "/api/graph/external/object?source_euid=CX-TEST&ref_index=0&euid=AT-PAT-1"
            )

        assert response.status_code == 200
        assert response.json()["euid"] == "AT-PAT-1"

    def test_get_node_info_returns_payload_without_uuid(self, client):
        fake_bobj = _fake_bobj_for_object_detail("CX-TEST")
        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ):
            response = client.get("/get_node_info?euid=CX-TEST")

        assert response.status_code == 200
        payload = response.json()
        assert payload["euid"] == "CX-TEST"
        assert payload["name"] == "Test Container"
        assert "uuid" not in payload

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
        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ):
            response = client.post(
                "/api/lineage",
                json={"parent_euid": "PARENT-1", "child_euid": "CHILD-1", "relationship_type": "generic"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["euid"] == "LN-NEW"
        assert "uuid" not in payload

    def test_api_lineage_duplicate_returns_409(self, client):
        fake_bobj = _fake_bobj_for_lineage_create(existing_lineage=True)
        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ):
            response = client.post(
                "/api/lineage",
                json={"parent_euid": "PARENT-1", "child_euid": "CHILD-1", "relationship_type": "generic"},
            )
        assert response.status_code == 409

    def test_add_new_edge_rejects_legacy_uuid_keys(self, client):
        response = client.post(
            "/add_new_edge",
            json={"parent_uuid": "PARENT-1", "child_uuid": "CHILD-1"},
        )

        assert response.status_code == 400
        assert "parent_euid and child_euid are required" in response.text

    def test_add_new_edge_accepts_euid_keys(self, client):
        fake_bobj = MagicMock()
        fake_bobj.create_generic_instance_lineage_by_euids.return_value = SimpleNamespace(euid="LN-EDGE")

        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ):
            response = client.post(
                "/add_new_edge",
                json={"parent_euid": "PARENT-1", "child_euid": "CHILD-1"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["euid"] == "LN-EDGE"
        assert "uuid" not in payload

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
        with patch("bloom_lims.gui.routes.graph.BLOOMdb3", _DummyDB), patch(
            "bloom_lims.gui.routes.graph.BloomObj", return_value=fake_bobj
        ):
            response = client.delete("/api/object/DEL-1")

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["hard_delete_applied"] is False
