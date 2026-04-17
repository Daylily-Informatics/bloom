from pathlib import Path

from typer.testing import CliRunner

from bloom_lims.cli import build_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_root_environment_contract_uses_environment_yaml() -> None:
    assert (PROJECT_ROOT / "environment.yaml").is_file()
    assert not (PROJECT_ROOT / "environment").with_suffix(".yml").exists()
    assert not (PROJECT_ROOT / "requirements.txt").exists()


def test_activate_is_bare_and_uses_repo_root_editable_install() -> None:
    activate = (PROJECT_ROOT / "activate").read_text(encoding="utf-8")
    deactivate = (PROJECT_ROOT / "bloom_deactivate").read_text(encoding="utf-8")
    environment = (PROJECT_ROOT / "environment.yaml").read_text(encoding="utf-8")

    assert "environment.yaml" in activate
    assert '"${CONDA_PREFIX}/bin/python" -m pip install -e "$BLOOM_ROOT"' in activate
    assert 'python -m pip install -e "$BLOOM_ROOT"' not in activate.replace(
        '"${CONDA_PREFIX}/bin/python" -m pip install -e "$BLOOM_ROOT"', ""
    )
    assert "[dev]" not in activate
    assert "TAPDB_DOMAIN_REGISTRY_PATH" not in activate
    assert "TAPDB_PREFIX_OWNERSHIP_REGISTRY_PATH" not in activate
    assert "BLOOM_TAPDB__DOMAIN_REGISTRY_PATH" not in activate
    assert "BLOOM_TAPDB__PREFIX_OWNERSHIP_REGISTRY_PATH" not in activate
    assert "MERIDIAN_DOMAIN_CODE" not in activate
    assert "TAPDB_OWNER_REPO" not in activate
    assert "export BLOOM_ACTIVE=1" in activate
    assert (PROJECT_ROOT / "bloom_deactivate").is_file()
    assert "unset BLOOM_ACTIVE" in deactivate
    assert "ipython" not in environment.lower()
    assert "psycopg2" not in environment.lower()
    assert "djlint" not in environment.lower()


def test_db_build_help_mentions_target_option() -> None:
    runner = CliRunner()
    result = runner.invoke(build_app(), ["db", "build", "--help"])
    assert result.exit_code == 0
    assert "--target" in result.output
