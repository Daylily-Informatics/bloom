from __future__ import annotations

from pathlib import Path

from tests.support.runtime import read_pyproject_dependency_spec

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


def test_project_dependencies_pin_release_train_versions() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]
    optional_dependencies = data["project"]["optional-dependencies"]
    tapdb_spec = read_pyproject_dependency_spec("daylily-tapdb")
    zebra_spec = read_pyproject_dependency_spec("zebra-day")

    assert "cli-core-yo==2.0.0" in dependencies
    assert "daylily-auth-cognito==2.0.3" in dependencies
    assert f"daylily-tapdb{tapdb_spec}" in dependencies
    assert f"zebra-day{zebra_spec}" not in dependencies
    assert optional_dependencies["zebra_day"] == [f"zebra-day{zebra_spec}"]
