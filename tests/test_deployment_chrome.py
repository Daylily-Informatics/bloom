from __future__ import annotations

import pytest

from bloom_lims.config import (
    DEFAULT_DEPLOYMENT_BANNER_COLOR,
    DeploymentSettings,
    _stable_deployment_color_hex,
)
from bloom_lims.gui.jinja import _resolve_deployment_metadata


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
