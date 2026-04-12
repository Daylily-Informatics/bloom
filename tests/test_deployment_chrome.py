from __future__ import annotations

import pytest
from types import SimpleNamespace

from bloom_lims.config import (
    DEFAULT_DEPLOYMENT_BANNER_COLOR,
    DeploymentSettings,
    _stable_deployment_color_hex,
    _stable_region_color_hex,
)
from bloom_lims.gui.jinja import _resolve_deployment_metadata, refresh_template_globals, templates


def test_deployment_settings_fall_back_to_deployment_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLOOM_DEPLOYMENT_CODE", "staging")

    deployment = DeploymentSettings(name="", color="", is_production=True)

    assert deployment.name == "staging"
    assert deployment.color == _stable_deployment_color_hex("staging")
    assert deployment.is_production is False


def test_deployment_settings_force_prod_names_to_hide_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLOOM_DEPLOYMENT_CODE", "sandbox")

    deployment = DeploymentSettings(name="production", color="", is_production=False)

    assert deployment.name == "production"
    assert deployment.color == _stable_deployment_color_hex("production")
    assert deployment.is_production is True


def test_stable_deployment_color_vectors() -> None:
    assert _stable_deployment_color_hex("510x2") == "#4321ca"
    assert _stable_deployment_color_hex("inflec3") == "#7521ca"
    assert _stable_deployment_color_hex("production") == "#ca2183"


def test_stable_region_color_vectors() -> None:
    assert _stable_region_color_hex("us-east-1") == "#8aca72"
    assert _stable_region_color_hex("us-west-2") == "#a5ca72"


def test_jinja_deployment_metadata_defaults_to_light_aqua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_settings_error():
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr("bloom_lims.config.get_settings", _raise_settings_error)

    deployment = _resolve_deployment_metadata()

    assert deployment == {
        "name": "",
        "color": DEFAULT_DEPLOYMENT_BANNER_COLOR,
        "is_production": False,
    }


def test_environment_chrome_renders_and_hides_with_config_toggle(monkeypatch) -> None:
    enabled_settings = SimpleNamespace(
        app_name="BLOOM LIMS",
        api=SimpleNamespace(version="9.9.9"),
        ui=SimpleNamespace(
            support_email="support@example.com",
            github_repo_url="https://github.com/Daylily-Informatics/bloom",
            show_environment_chrome=True,
        ),
        aws=SimpleNamespace(region="us-east-1"),
        deployment=SimpleNamespace(name="510x2", color="", is_production=False),
    )

    monkeypatch.setattr("bloom_lims.config.get_settings", lambda: enabled_settings)
    monkeypatch.setattr("bloom_lims.gui.jinja._run_git_command", lambda *args: {
        ("rev-parse", "--abbrev-ref", "HEAD"): "codex/bloom-gui-chrome-scm",
        ("rev-parse", "--short", "HEAD"): "abc1234",
        ("describe", "--tags", "--exact-match"): "3.5.15",
    }.get(args, ""))
    monkeypatch.setattr("bloom_lims.gui.jinja.__version__", "3.5.15")

    refresh_template_globals()
    rendered = templates.get_template("modern/base.html").render(
        request=SimpleNamespace(url=SimpleNamespace(path="/")),
        user=None,
        udat=None,
        version="3.5.15",
    )

    assert "bloom-environment-chrome" in rendered
    assert "#4321ca" in rendered
    assert "#8aca72" in rendered
    assert "Branch: codex/bloom-gui-chrome-scm" in rendered
    assert "Tag: 3.5.15" in rendered
    assert "Commit: abc1234" in rendered

    disabled_settings = SimpleNamespace(
        app_name="BLOOM LIMS",
        api=SimpleNamespace(version="9.9.9"),
        ui=SimpleNamespace(
            support_email="support@example.com",
            github_repo_url="https://github.com/Daylily-Informatics/bloom",
            show_environment_chrome=False,
        ),
        aws=SimpleNamespace(region="us-east-1"),
        deployment=SimpleNamespace(name="510x2", color="", is_production=False),
    )
    monkeypatch.setattr("bloom_lims.config.get_settings", lambda: disabled_settings)
    refresh_template_globals()
    rendered_disabled = templates.get_template("modern/base.html").render(
        request=SimpleNamespace(url=SimpleNamespace(path="/")),
        user=None,
        udat=None,
        version="3.5.15",
    )

    assert "bloom-environment-chrome" not in rendered_disabled
    assert "#4321ca" not in rendered_disabled


def test_gui_metadata_uses_unreleased_when_repo_is_not_tagged(monkeypatch) -> None:
    fake_settings = SimpleNamespace(
        app_name="BLOOM LIMS",
        api=SimpleNamespace(version="9.9.9"),
        ui=SimpleNamespace(
            support_email="support@example.com",
            github_repo_url="https://github.com/Daylily-Informatics/bloom",
            show_environment_chrome=True,
        ),
        aws=SimpleNamespace(region="us-west-2"),
        deployment=SimpleNamespace(name="510x2", color="", is_production=False),
    )

    def _git_command(*args):
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "codex/bloom-gui-chrome-scm"
        if args == ("rev-parse", "--short", "HEAD"):
            return "abc1234"
        return ""

    monkeypatch.setattr("bloom_lims.config.get_settings", lambda: fake_settings)
    monkeypatch.setattr("bloom_lims.gui.jinja._run_git_command", _git_command)
    monkeypatch.setattr("bloom_lims.gui.jinja.__version__", "3.5.15")

    refresh_template_globals()
    rendered = templates.get_template("modern/base.html").render(
        request=SimpleNamespace(url=SimpleNamespace(path="/")),
        user=None,
        udat=None,
        version="3.5.15",
    )

    assert "Tag: unreleased" in rendered
