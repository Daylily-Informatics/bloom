"""Runtime route inventory guard for Bloom-owned HTTP handlers."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Mount, Route

from bloom_lims.app import create_app

os.environ["BLOOM_DEV_AUTH_BYPASS"] = "true"
os.environ.setdefault("BLOOM_OAUTH", "no")

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(
        create_app(),
        raise_server_exceptions=False,
        base_url="https://testserver",
    )


def _normalize_path(path: str) -> str:
    return path if path == "/" else path.rstrip("/")


def _sample_path(expr: ast.AST) -> str | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return _normalize_path(expr.value.split("?", 1)[0])
    if isinstance(expr, ast.JoinedStr):
        parts: list[str] = []
        for value in expr.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("SEGMENT")
            else:
                return None
        return _normalize_path("".join(parts).split("?", 1)[0])
    return None


def _route_matches(route: str, sample: str) -> bool:
    pattern = re.escape(_normalize_path(route))
    pattern = re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", pattern)
    return re.fullmatch(pattern, sample) is not None


def _iter_direct_request_samples() -> set[tuple[str, str]]:
    samples: set[tuple[str, str]] = set()
    for path in Path("tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            method = node.func.attr.upper()
            if method not in HTTP_METHODS or not node.args:
                continue
            sample = _sample_path(node.args[0])
            if sample is None:
                continue
            samples.add((method, sample))
    return samples


def _iter_runtime_routes() -> set[tuple[str, str]]:
    app = create_app()
    routes: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, Mount):
            continue
        if not isinstance(route, (APIRoute, Route)):
            continue
        methods = set(route.methods or ()) & HTTP_METHODS
        for method in methods:
            routes.add((method, _normalize_path(route.path)))
    return routes


def test_docs_routes_remain_enabled_and_render(client: TestClient) -> None:
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["openapi"].startswith("3.")

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "Swagger UI" in docs.text

    docs_redirect = client.get("/docs/oauth2-redirect")
    assert docs_redirect.status_code == 200
    assert "oauth2" in docs_redirect.text.lower()

    redoc = client.get("/redoc")
    assert redoc.status_code == 200
    assert "ReDoc" in redoc.text


def test_observability_routes_with_runtime_only_inventory_are_hit_directly(
    client: TestClient,
) -> None:
    api_health = client.get("/api_health")
    assert api_health.status_code == 200
    assert "families" in api_health.json()

    my_health = client.get("/my_health")
    assert my_health.status_code == 200
    assert my_health.json()["principal"]["auth_mode"] == "dev_bypass"

    metrics = client.get("/health/metrics")
    assert metrics.status_code == 200
    assert "uptime_seconds" in metrics.json()


def test_runtime_routes_have_direct_request_coverage() -> None:
    missing = sorted(
        (method, route)
        for method, route in _iter_runtime_routes()
        if not any(
            method == sample_method and _route_matches(route, sample_route)
            for sample_method, sample_route in _iter_direct_request_samples()
        )
    )
    assert missing == []
