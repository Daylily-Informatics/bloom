from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


def test_project_dependencies_pin_release_train_versions() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]

    assert "cli-core-yo==2.0.0" in dependencies
    assert "daylily-auth-cognito==2.0.2" in dependencies
    assert "daylily-tapdb==5.0.4" in dependencies
    assert "zebra-day==5.1.3" in dependencies
