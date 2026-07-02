from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bloom_lims import tapdb_metrics


def _runtime_with_metrics(value: object, config_path: Path):
    return ("target", config_path, {"metrics_enabled": value})


def test_metrics_enabled_honors_explicit_yaml_over_helper_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "tapdb-config.yaml"
    config_path.write_text("target:\n  metrics_enabled: false\n", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    monkeypatch.setattr(
        tapdb_metrics,
        "_resolved_bloom_runtime",
        lambda _env_name=None: ("target", config_path, {"metrics_enabled": True}),
    )

    assert tapdb_metrics.metrics_enabled("target") is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (False, False),
        ("false", False),
        ("0", False),
        ("off", False),
        (True, True),
        ("true", True),
        ("1", True),
        ("on", True),
    ],
)
def test_metrics_enabled_honors_explicit_boolean_strings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: object, expected: bool
) -> None:
    config_path = tmp_path / "tapdb-config.yaml"
    config_path.write_text("target: {}\n", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    monkeypatch.setattr(
        tapdb_metrics,
        "_resolved_bloom_runtime",
        lambda _env_name=None: _runtime_with_metrics(value, config_path),
    )

    assert tapdb_metrics.metrics_enabled("target") is expected


def test_metrics_enabled_rejects_malformed_explicit_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "tapdb-config.yaml"
    config_path.write_text("target: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        tapdb_metrics,
        "_resolved_bloom_runtime",
        lambda _env_name=None: _runtime_with_metrics("sometimes", config_path),
    )

    with pytest.raises(RuntimeError, match="target.metrics_enabled"):
        tapdb_metrics.metrics_enabled("target")


def test_metrics_writer_not_created_when_config_string_disables_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "tapdb-config.yaml"
    config_path.write_text("target: {}\n", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    monkeypatch.setattr(
        tapdb_metrics,
        "_resolved_bloom_runtime",
        lambda _env_name=None: _runtime_with_metrics("false", config_path),
    )

    assert tapdb_metrics._get_writer("target") is None
