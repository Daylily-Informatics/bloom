from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_root_environment_contract_uses_environment_yaml() -> None:
    assert (PROJECT_ROOT / "environment.yaml").is_file()
    assert not (PROJECT_ROOT / "environment").with_suffix(".yml").exists()
    assert not (PROJECT_ROOT / "requirements.txt").exists()


def test_activate_only_references_root_environment_yaml() -> None:
    activate = (PROJECT_ROOT / "activate").read_text(encoding="utf-8")
    environment = (PROJECT_ROOT / "environment.yaml").read_text(encoding="utf-8")

    assert "environment.yaml" in activate
    assert "environment" + ".yml" not in activate
    assert "requirements.txt" not in activate
    assert "pip install --no-deps -e" in activate
    assert "-e ." not in environment
