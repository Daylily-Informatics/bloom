"""Focused regression tests for Bloom runtime configuration."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

import yaml

from bloom_lims import __version__
from bloom_lims.app import create_app
from bloom_lims.config import (
    DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT,
    BloomSettings,
    StorageSettings,
    build_effective_config_summary,
    _deployment_scoped_tapdb_config_path,
    build_default_config_template,
    expected_conda_env_name,
    generate_example_webhook_secret,
    get_settings,
    get_tapdb_runtime_context,
    validate_settings,
)
from tests.support.runtime import ensure_test_runtime_environment


def test_storage_temp_dir_uses_system_tempdir():
    assert StorageSettings().temp_dir == str(Path(tempfile.gettempdir()) / "bloom")


def test_storage_upload_dir_defaults_to_deployment_scoped_runtime(
    monkeypatch, tmp_path: Path
):
    xdg_config_home = tmp_path / ".config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    monkeypatch.setenv("BLOOM_DEPLOYMENT_CODE", "local2")
    monkeypatch.delenv("BLOOM_TAPDB__CONFIG_PATH", raising=False)
    get_settings.cache_clear()

    settings = BloomSettings()
    expected = xdg_config_home / "tapdb" / "bloom" / "bloom-local2" / "dev" / "uploads"

    assert Path(settings.storage.upload_dir) == expected
    assert expected.is_dir()


def test_expected_conda_env_name_uses_deployment_code(monkeypatch):
    monkeypatch.setenv("BLOOM_DEPLOYMENT_CODE", "bringup")
    assert expected_conda_env_name() == "BLOOM-bringup"


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


def test_build_default_config_template_injects_fresh_jwt_secret():
    first = build_default_config_template().decode("utf-8")
    second = build_default_config_template().decode("utf-8")

    assert first != second
    for template in (first, second):
        match = re.search(r'jwt_secret:\s*"([^"]+)"', template)
        assert match is not None
        assert len(match.group(1)) >= 32
        data = yaml.safe_load(template)
        auth = data["auth"]
        assert auth["cognito_allowed_domains"] == [
            "lsmc.com",
            "lsmc.bio",
            "lsmc.life",
            "daylilyinformatics.com",
        ]
        assert (
            auth["cognito_default_tenant_id"] == "00000000-0000-0000-0000-000000000000"
        )
        assert auth["auto_provision_allowed_domains"] == ["lsmc.com"]
        assert data["network"]["allowed_hosts"] == []
        assert "daylilyinformatics.bio" not in template


def test_settings_sources_do_not_include_dotenv():
    init_settings = object()
    env_settings = object()
    dotenv_settings = object()
    file_secret_settings = object()

    sources = BloomSettings.settings_customise_sources(
        BloomSettings,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    )

    assert dotenv_settings not in sources


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

    assert any(
        "Atlas webhook signature secret is not configured" in warning
        for warning in warnings
    )
    assert any("20-character alphanumeric secret" in warning for warning in warnings)


def test_create_app_logs_atlas_webhook_secret_warning(
    monkeypatch, tmp_path: Path, caplog
):
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


def test_runtime_context_defaults_to_deployment_scoped_tapdb_config(
    monkeypatch, tmp_path: Path
):
    xdg_config_home = tmp_path / ".config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    monkeypatch.setenv("BLOOM_DEPLOYMENT_CODE", "local2")
    monkeypatch.delenv("BLOOM_TAPDB__CONFIG_PATH", raising=False)
    get_settings.cache_clear()

    settings = BloomSettings()
    ctx = get_tapdb_runtime_context(settings)

    expected = str(
        xdg_config_home / "tapdb" / "bloom" / "bloom-local2" / "tapdb-config.yaml"
    )

    assert ctx.config_path == _deployment_scoped_tapdb_config_path("bloom", "bloom")
    assert ctx.config_path == expected


def test_tapdb_version_contract_defaults_match_shipped_templates():
    settings = BloomSettings()

    assert settings.tapdb.min_version == "5.1.0"
    assert settings.tapdb.max_version_exclusive == "5.1.1"

    root_template = Path("config/bloom-config-template.yaml").read_text(
        encoding="utf-8"
    )
    packaged_template = Path("bloom_lims/etc/bloom-config-template.yaml").read_text(
        encoding="utf-8"
    )

    assert 'min_version: "5.1.0"' in root_template
    assert 'max_version_exclusive: "5.1.1"' in root_template
    assert 'min_version: "5.1.0"' in packaged_template
    assert 'max_version_exclusive: "5.1.1"' in packaged_template
    assert "allowed_hosts: []" in root_template
    assert "allowed_hosts: []" in packaged_template


def test_settings_accept_network_allowed_hosts() -> None:
    settings = BloomSettings(network={"allowed_hosts": ["bloom.dev2.lsmc.life", "54.218.100.68"]})

    assert settings.network.allowed_hosts == ["bloom.dev2.lsmc.life", "54.218.100.68"]


def test_effective_config_summary_redacts_sensitive_values(
    monkeypatch, tmp_path: Path
):
    ensure_test_runtime_environment()
    monkeypatch.setenv("BLOOM_UI__SHOW_ENVIRONMENT_CHROME", "false")
    monkeypatch.setenv("BLOOM_AUTH__COGNITO_CLIENT_SECRET", "super-secret")
    monkeypatch.setenv("BLOOM_AUTH__JWT_SECRET", "jwt-secret")
    monkeypatch.setenv("BLOOM_ATLAS__WEBHOOK_SECRET", "atlas-secret")
    monkeypatch.setenv("BLOOM_DEPLOYMENT__NAME", "510x2")
    monkeypatch.setenv("BLOOM_AWS__REGION", "us-east-1")
    monkeypatch.setenv("BLOOM_TAPDB__CONFIG_PATH", str(tmp_path / "tapdb.yaml"))
    get_settings.cache_clear()

    summary = build_effective_config_summary()
    rows = {row["key"]: row["value"] for row in summary["effective_rows"]}

    assert summary["build_version"] == __version__
    assert summary["show_environment_chrome"] is False
    assert summary["deployment_name"] == "510x2"
    assert summary["aws_region"] == "us-east-1"
    assert summary["user_config_path"]
    assert summary["template_config_path"]
    assert rows["auth.cognito_client_secret"] == "<redacted>"
    assert rows["auth.jwt_secret"] == "<redacted>"
    assert rows["atlas.webhook_secret"] == "<redacted>"
    assert rows["ui.show_environment_chrome"] == "false"


def test_create_app_uses_scm_version(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("BLOOM_SKIP_STARTUP_VALIDATION", raising=False)
    monkeypatch.setenv("BLOOM_TAPDB__CONFIG_PATH", str(tmp_path / "missing.yaml"))

    ensure_test_runtime_environment()
    get_settings.cache_clear()

    app = create_app()

    assert app.version == __version__
