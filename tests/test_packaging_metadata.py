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
    tapdb_spec = read_pyproject_dependency_spec("daylily-tapdb")

    assert "cli-core-yo==2.1.0" in dependencies
    assert "daylily-auth-cognito==2.1.1" in dependencies
    assert f"daylily-tapdb{tapdb_spec}" in dependencies
    assert "IPython>=8.18.1" in dependencies
    assert "psycopg2==2.9.9" in dependencies
    assert not any(str(dep).startswith("zebra-day") for dep in dependencies)
    assert "djlint" in dependencies
    assert "optional-dependencies" not in data["project"]
