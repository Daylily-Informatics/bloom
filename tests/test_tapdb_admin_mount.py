"""TapDB admin mount behavior tests."""

from __future__ import annotations

import importlib

from starlette.routing import Mount

from main import app


def test_tapdb_admin_mount_follows_dependency_availability() -> None:
    has_admin = importlib.util.find_spec("admin.main") is not None
    mounted_paths = {
        route.path
        for route in app.routes
        if isinstance(route, Mount)
    }

    if has_admin:
        assert "/tapdb" in mounted_paths
    else:
        assert "/tapdb" not in mounted_paths
