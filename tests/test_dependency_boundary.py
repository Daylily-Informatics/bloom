from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_environment_yaml_is_system_only() -> None:
    environment = yaml.safe_load(
        (PROJECT_ROOT / "environment.yaml").read_text(encoding="utf-8")
    )
    dependencies = environment["dependencies"]
    rendered = (PROJECT_ROOT / "environment.yaml").read_text(encoding="utf-8").lower()

    assert "pip:" not in rendered
    assert "ipython" not in rendered
    assert "psycopg2" not in rendered
    assert "djlint" not in rendered
    assert any(entry == "python=3.12.0" for entry in dependencies)
    assert any(entry == "pip=23.3.1" for entry in dependencies)
    assert any(entry == "setuptools<81" for entry in dependencies)


def test_pyproject_owns_python_dependencies() -> None:
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = pyproject["project"]
    dependencies = project["dependencies"]

    assert "IPython>=8.18.1" in dependencies
    assert "psycopg2==2.9.9" in dependencies
    assert "djlint" in dependencies
    assert "pytest>=8.0" in dependencies
    assert "zebra-day==5.2.0" not in dependencies
    assert "optional-dependencies" not in project
    assert project["scripts"]["bloom"] == "bloom_lims.cli:main"


def test_agents_ban_secondary_install_sets() -> None:
    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "secondary install set" in agents
    assert "`.[dev]`" in agents
    assert "`[project.optional-dependencies]`" in agents


def test_user_facing_files_do_not_reference_dev_extras_or_optional_groups() -> None:
    for relative_path in (
        "README.md",
        "docs/how-tos.md",
        "docs/becoming_a_discoverable_service.md",
        "activate",
    ):
        path = PROJECT_ROOT / relative_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert ".[dev]" not in text, relative_path
        assert "optional-dependencies.dev" not in text, relative_path
