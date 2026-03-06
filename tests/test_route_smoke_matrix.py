"""Route smoke matrix tests.

These tests guarantee every registered API endpoint and GUI route has at least one
request exercised in pytest.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

os.environ["BLOOM_OAUTH"] = "no"
os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app  # noqa: E402


@dataclass(frozen=True)
class RouteCall:
    method: str
    path: str
    name: str


def _route_calls(prefix: str | None) -> list[RouteCall]:
    rows: list[RouteCall] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if prefix is not None and not route.path.startswith(prefix):
            continue
        if prefix is None and route.path.startswith("/api/v1"):
            continue
        for method in sorted(route.methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            rows.append(RouteCall(method=method, path=route.path, name=route.name or "<unnamed>"))
    rows.sort(key=lambda row: (row.path, row.method))
    return rows


API_ROUTE_CALLS = _route_calls("/api/v1")
GUI_ROUTE_CALLS = _route_calls(None)


def _path_value(param_name: str) -> str:
    key = param_name.lower()
    if "file_path" in key:
        return "placeholder/path.txt"
    if key in {"category", "group_code"}:
        return "API_ACCESS" if key == "group_code" else "container"
    if key in {"tracking_number"}:
        return "123456789012"
    if "euid" in key:
        return "ZZ-TEST"
    if key in {"test_order_id"}:
        return "TO-TEST"
    if "uuid" in key or key.endswith("_id") or key == "id" or key.endswith("_uuid"):
        return str(uuid.uuid4())
    return "test"


_PATH_PARAM_RE = re.compile(r"\{([^{}]+)\}")


def _materialize_path(path_template: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        raw_name = match.group(1)
        if ":" in raw_name:
            name, _converter = raw_name.split(":", 1)
        else:
            name = raw_name
        return _path_value(name)

    return _PATH_PARAM_RE.sub(_replace, path_template)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, base_url="https://testserver",  raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _patch_side_effects(monkeypatch: pytest.MonkeyPatch):
    # Prevent admin zebra startup route from launching local scripts in smoke matrix.
    monkeypatch.setattr("bloom_lims.gui.routes.legacy.shutil.which", lambda _cmd: "/usr/local/bin/zday_start")
    monkeypatch.setattr(
        "bloom_lims.gui.routes.legacy.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=["zday_start"], returncode=0, stdout="ok", stderr=""),
    )

    # Keep tracking endpoints deterministic and local.
    monkeypatch.setattr("bloom_lims.api.v1.tracking._get_fedex_tracker", lambda: None)


@pytest.mark.parametrize(
    "route_call",
    API_ROUTE_CALLS,
    ids=lambda row: f"{row.method} {row.path}",
)
def test_api_route_smoke_matrix(client: TestClient, route_call: RouteCall):
    url = _materialize_path(route_call.path)
    kwargs = {"follow_redirects": False}
    if route_call.method in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = {}

    response = client.request(route_call.method, url, **kwargs)

    # We only require that the route/method is exercised; many endpoints will
    # intentionally return auth/validation/not-found for synthetic payloads.
    assert response.status_code != 405, (
        f"Route not exercised as expected: {route_call.method} {route_call.path} "
        f"(resolved {url}, status={response.status_code})"
    )


@pytest.mark.parametrize(
    "route_call",
    GUI_ROUTE_CALLS,
    ids=lambda row: f"{row.method} {row.path}",
)
def test_gui_route_smoke_matrix(client: TestClient, route_call: RouteCall):
    url = _materialize_path(route_call.path)
    kwargs = {"follow_redirects": False}
    if route_call.method in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = {}

    response = client.request(route_call.method, url, **kwargs)

    assert response.status_code != 405, (
        f"GUI route not exercised as expected: {route_call.method} {route_call.path} "
        f"(resolved {url}, status={response.status_code})"
    )


def test_route_inventory_sanity():
    # Guardrail so future route additions are reflected in this matrix immediately.
    assert len(API_ROUTE_CALLS) > 0
    assert len(GUI_ROUTE_CALLS) > 0
