from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bloom_lims import tapdb_metrics


def _runtime_with_metrics(value: object):
    return ("target", Path("/tmp/bloom-tapdb.yaml"), {"metrics_enabled": value})


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
    monkeypatch: pytest.MonkeyPatch, value: object, expected: bool
) -> None:
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    monkeypatch.setattr(
        tapdb_metrics,
        "_resolved_bloom_runtime",
        lambda _env_name=None: _runtime_with_metrics(value),
    )

    assert tapdb_metrics.metrics_enabled("target") is expected


def test_metrics_enabled_rejects_malformed_explicit_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tapdb_metrics,
        "_resolved_bloom_runtime",
        lambda _env_name=None: _runtime_with_metrics("sometimes"),
    )

    with pytest.raises(RuntimeError, match="target.metrics_enabled"):
        tapdb_metrics.metrics_enabled("target")


def test_metrics_writer_not_created_when_config_string_disables_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    monkeypatch.setattr(
        tapdb_metrics,
        "_resolved_bloom_runtime",
        lambda _env_name=None: _runtime_with_metrics("false"),
    )

    assert tapdb_metrics._get_writer("target") is None
