"""Focused regression tests for Bloom runtime configuration."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from bloom_lims.app import create_app
from bloom_lims.config import (
    DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT,
    BloomSettings,
    StorageSettings,
    _deployment_scoped_tapdb_config_path,
    generate_example_webhook_secret,
    get_settings,
    get_tapdb_runtime_context,
    validate_settings,
)
from tests.support.runtime import ensure_test_runtime_environment


def test_storage_temp_dir_uses_system_tempdir():
    assert StorageSettings().temp_dir == str(Path(tempfile.gettempdir()) / "bloom")


def test_nested_env_overrides_template_defaults(monkeypatch):
    monkeypatch.setenv("BLOOM_AUTH__COGNITO_USER_POOL_ID", "pool-from-env")
    monkeypatch.setenv("BLOOM_AUTH__COGNITO_CLIENT_ID", "client-from-env")
    monkeypatch.setenv(
        "BLOOM_AUTH__COGNITO_DOMAIN", "env-test.auth.us-west-2.amazoncognito.com"
    )
    monkeypatch.setenv(
        "BLOOM_AUTH__COGNITO_REDIRECT_URI", "https://example.test/auth/callback"
    )
    get_settings.cache_clear()

    settings = BloomSettings()

    assert settings.auth.cognito_user_pool_id == "pool-from-env"
    assert settings.auth.cognito_client_id == "client-from-env"
    assert settings.auth.cognito_domain == "env-test.auth.us-west-2.amazoncognito.com"
    assert settings.auth.cognito_redirect_uri == "https://example.test/auth/callback"


def test_runtime_bootstrap_replaces_missing_tapdb_config_path(
    monkeypatch, tmp_path: Path
):
    missing_path = tmp_path / "missing-tapdb-config.yaml"
    monkeypatch.setenv("BLOOM_TAPDB__CONFIG_PATH", str(missing_path))
    monkeypatch.delenv("BLOOM_TAPDB__LOCAL_PG_PORT", raising=False)

    config_path = ensure_test_runtime_environment()

    assert config_path.exists()
    assert config_path != missing_path
    assert Path(os.environ["BLOOM_TAPDB__CONFIG_PATH"]).exists()
    assert os.environ["BLOOM_TAPDB__LOCAL_PG_PORT"] == str(
        os.environ.get("BLOOM_TAPDB__LOCAL_PG_PORT", DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT)
    )


def test_strict_app_startup_accepts_synthesized_test_config(
    monkeypatch, tmp_path: Path
):
    monkeypatch.delenv("BLOOM_SKIP_STARTUP_VALIDATION", raising=False)
    monkeypatch.setenv(
        "BLOOM_TAPDB__CONFIG_PATH", str(tmp_path / "missing-startup-config.yaml")
    )

    ensure_test_runtime_environment()
    get_settings.cache_clear()

    app = create_app()

    assert app.title == "FastAPI"


def test_create_app_does_not_mount_upload_or_tmp_static_dirs(
    monkeypatch, tmp_path: Path
):
    monkeypatch.delenv("BLOOM_SKIP_STARTUP_VALIDATION", raising=False)
    monkeypatch.setenv(
        "BLOOM_TAPDB__CONFIG_PATH", str(tmp_path / "missing-startup-config.yaml")
    )

    ensure_test_runtime_environment()
    get_settings.cache_clear()

    app = create_app()
    mount_paths = {route.path for route in app.routes}

    assert "/static" in mount_paths
    assert "/templates" in mount_paths
    assert "/uploads" not in mount_paths
    assert "/tmp" not in mount_paths


def test_generate_example_webhook_secret_is_20_char_alphanumeric():
    secret = generate_example_webhook_secret()
    assert len(secret) == 20
    assert secret.isalnum()


def test_validate_settings_warns_when_atlas_webhook_secret_missing(monkeypatch):
    monkeypatch.setenv("BLOOM_ATLAS__WEBHOOK_SECRET", "")
    get_settings.cache_clear()

    warnings = validate_settings()

    assert any("Atlas webhook signature secret is not configured" in warning for warning in warnings)
    assert any("20-character alphanumeric secret" in warning for warning in warnings)


def test_create_app_logs_atlas_webhook_secret_warning(monkeypatch, tmp_path: Path, caplog):
    monkeypatch.delenv("BLOOM_SKIP_STARTUP_VALIDATION", raising=False)
    monkeypatch.setenv(
        "BLOOM_TAPDB__CONFIG_PATH", str(tmp_path / "missing-startup-config.yaml")
    )
    monkeypatch.setenv("BLOOM_ATLAS__WEBHOOK_SECRET", "")

    ensure_test_runtime_environment()
    get_settings.cache_clear()
    caplog.set_level(logging.WARNING)

    create_app()

    assert any(
        "Atlas webhook signature secret is not configured" in message
        for message in caplog.messages
    )


def test_runtime_context_defaults_to_deployment_scoped_tapdb_config(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("BLOOM_DEPLOYMENT_CODE", "local2")
    monkeypatch.delenv("BLOOM_TAPDB__CONFIG_PATH", raising=False)
    get_settings.cache_clear()

    settings = BloomSettings()
    ctx = get_tapdb_runtime_context(settings)

    assert ctx.config_path == _deployment_scoped_tapdb_config_path("bloom", "bloom")
    assert ctx.config_path.endswith("/.config/tapdb/bloom/bloom-local2/tapdb-config.yaml")


def test_tapdb_version_contract_defaults_match_shipped_templates():
    settings = BloomSettings()

    assert settings.tapdb.min_version == "4.1.1"
    assert settings.tapdb.max_version_exclusive == "4.1.2"

    root_template = Path("config/bloom-config-template.yaml").read_text(encoding="utf-8")
    packaged_template = Path("bloom_lims/etc/bloom-config-template.yaml").read_text(
        encoding="utf-8"
    )

    assert 'min_version: "4.1.1"' in root_template
    assert 'max_version_exclusive: "4.1.2"' in root_template
    assert 'min_version: "4.1.1"' in packaged_template
    assert 'max_version_exclusive: "4.1.2"' in packaged_template
