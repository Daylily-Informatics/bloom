"""Focused regression tests for Bloom runtime configuration."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from bloom_lims.app import create_app
from bloom_lims.config import BloomSettings, StorageSettings, get_settings
from tests.support.runtime import ensure_test_runtime_environment


def test_storage_temp_dir_uses_system_tempdir():
    assert StorageSettings().temp_dir == str(Path(tempfile.gettempdir()) / "bloom")


def test_nested_env_overrides_template_defaults(monkeypatch):
    monkeypatch.setenv("BLOOM_AUTH__COGNITO_USER_POOL_ID", "pool-from-env")
    monkeypatch.setenv("BLOOM_AUTH__COGNITO_CLIENT_ID", "client-from-env")
    monkeypatch.setenv("BLOOM_AUTH__COGNITO_DOMAIN", "env-test.auth.us-west-2.amazoncognito.com")
    monkeypatch.setenv("BLOOM_AUTH__COGNITO_REDIRECT_URI", "https://example.test/auth/callback")
    get_settings.cache_clear()

    settings = BloomSettings()

    assert settings.auth.cognito_user_pool_id == "pool-from-env"
    assert settings.auth.cognito_client_id == "client-from-env"
    assert settings.auth.cognito_domain == "env-test.auth.us-west-2.amazoncognito.com"
    assert settings.auth.cognito_redirect_uri == "https://example.test/auth/callback"


def test_runtime_bootstrap_replaces_missing_tapdb_config_path(monkeypatch, tmp_path: Path):
    missing_path = tmp_path / "missing-tapdb-config.yaml"
    monkeypatch.setenv("TAPDB_CONFIG_PATH", str(missing_path))
    monkeypatch.delenv("PGPORT", raising=False)

    config_path = ensure_test_runtime_environment()

    assert config_path.exists()
    assert config_path != missing_path
    assert Path(os.environ["TAPDB_CONFIG_PATH"]).exists()
    assert os.environ["PGPORT"] == str(os.environ.get("BLOOM_TAPDB_LOCAL_PG_PORT", "5566"))


def test_strict_app_startup_accepts_synthesized_test_config(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("BLOOM_SKIP_STARTUP_VALIDATION", raising=False)
    monkeypatch.setenv("TAPDB_CONFIG_PATH", str(tmp_path / "missing-startup-config.yaml"))

    ensure_test_runtime_environment()
    get_settings.cache_clear()

    app = create_app()

    assert app.title == "FastAPI"
