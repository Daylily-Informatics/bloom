from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_root_environment_contract_uses_environment_yaml() -> None:
    assert (PROJECT_ROOT / "environment.yaml").is_file()
    assert not (PROJECT_ROOT / "environment").with_suffix(".yml").exists()
    assert not (PROJECT_ROOT / "requirements.txt").exists()


def test_activate_only_references_root_environment_yaml() -> None:
    activate = (PROJECT_ROOT / "activate").read_text(encoding="utf-8")
    deactivate = (PROJECT_ROOT / "bloom_deactivate").read_text(encoding="utf-8")
    environment = (PROJECT_ROOT / "environment.yaml").read_text(encoding="utf-8")
    root_template = (PROJECT_ROOT / "config" / "bloom-config-template.yaml").read_text(
        encoding="utf-8"
    )
    packaged_template = (
        PROJECT_ROOT / "bloom_lims" / "etc" / "bloom-config-template.yaml"
    ).read_text(encoding="utf-8")

    assert "environment.yaml" in activate
    assert "environment" + ".yml" not in activate
    assert "requirements.txt" not in activate
    assert 'pip install -e "${BLOOM_ROOT}[dev]" -q' in activate
    assert "export BLOOM_ACTIVE=1" in activate
    assert "--no-deps" not in activate
    assert (PROJECT_ROOT / "bloom_deactivate").is_file()
    assert "unset BLOOM_ACTIVE" in deactivate
    assert "-e ." not in environment
    assert "MERIDIAN_DOMAIN_CODE=Z" in root_template
    assert "TAPDB_APP_CODE=B" in root_template
    assert "MERIDIAN_DOMAIN_CODE=Z" in packaged_template
    assert "TAPDB_APP_CODE=B" in packaged_template
