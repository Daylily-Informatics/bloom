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

    assert "cli-core-yo==2.1.1" in dependencies
    assert "daylily-auth-cognito==2.1.5" in dependencies
    assert "daylily-tapdb @ git+https://github.com/Daylily-Informatics/daylily-tapdb.git@9.0.1" in dependencies
    assert "IPython>=8.18.1" in dependencies
    assert "psycopg2-binary==2.9.12" in dependencies
    assert not any(str(dep).startswith("zebra-day") for dep in dependencies)
    assert "djlint" in dependencies
    assert "optional-dependencies" not in data["project"]


def test_dockerfile_copies_tapdb_template_config() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "COPY config ./config" in dockerfile
    assert "COPY static ./static" in dockerfile
    assert "COPY templates ./templates" in dockerfile


def test_dockerfile_installs_git_before_git_pinned_dependencies() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
        encoding="utf-8"
    )

    first_uv_sync = dockerfile.index("RUN uv sync")
    git_install = dockerfile.index("git")
    assert git_install < first_uv_sync


def test_dockerfile_uses_package_specific_scm_version() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION}" not in dockerfile
    assert (
        "ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_BLOOM_LIMS=${SETUPTOOLS_SCM_PRETEND_VERSION}"
        in dockerfile
    )
