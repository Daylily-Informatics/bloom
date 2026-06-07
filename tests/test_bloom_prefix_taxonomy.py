"""Bloom prefix taxonomy and wet-lab template contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bloom_lims.core.validation import ValidationError, validate_euid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PREFIX_CHARS = set("ILOU")


def _template_pack() -> dict:
    return json.loads(
        (
            PROJECT_ROOT / "config" / "tapdb_templates" / "bloom" / "templates.json"
        ).read_text(encoding="utf-8")
    )


def _templates_by_code() -> dict[str, dict]:
    templates: dict[str, dict] = {}
    for template in _template_pack()["templates"]:
        semantic_category = template["json_addl"].get("semantic_category")
        code = (
            f"{semantic_category}/{template['type']}/"
            f"{template['subtype']}/{template['version']}"
        )
        templates[code] = template
    return templates


def test_wet_lab_templates_use_bloom_prefix_taxonomy() -> None:
    templates = _templates_by_code()

    expected_prefixes = {
        "container/tube/tube-generic-10ml/1.0": "BCT",
        "container/plate/fixed-plate-96/1.0": "BCP",
        "container/plate/sequencing-library-plate-96/1.0": "BCP",
        "container/plate/index-plate-96/1.0": "BCP",
        "container/well/fixed-plate-well/1.0": "BCW",
        "container/bottle/generic/1.0": "BCB",
        "container/flowcell/generic/1.0": "BCF",
        "container/flowcell_lane/generic/1.0": "BCE",
        "content/specimen/blood-whole/1.0": "BNB",
        "content/specimen/buccal-swab/1.0": "BNS",
        "content/specimen/saliva/1.0": "BNA",
        "content/sample/gdna/1.0": "BNG",
        "content/sample/cfdna/1.0": "BNC",
        "content/sample/sequencing-library/1.0": "BNQ",
        "content/pool/sequencing-library/1.0": "BNP",
        "content/reagent/sequencing-index/1.0": "BNX",
        "data/generic/gdna-quantification/1.0": "BDQ",
        "data/quantification/gdna/1.0": "BDQ",
        "data/operation/extraction/1.0": "BDX",
        "data/operation/extraction-qc/1.0": "BDY",
        "data/operation/library-prep/1.0": "BDP",
        "data/operation/pooling/1.0": "BDN",
        "data/library-index-assignment/sequencing-library/1.0": "BDA",
        "data/execution/transfer/1.0": "BDT",
        "generic/generic/external_object_link/1.0": "BGX",
    }

    for code, expected_prefix in expected_prefixes.items():
        template = templates[code]
        assert template["category"] == expected_prefix
        assert template["instance_prefix"] == expected_prefix


def test_anomaly_template_is_packaged_for_observability() -> None:
    templates = _template_pack()["templates"]
    anomaly = next(
        template
        for template in templates
        if (
            template["category"],
            template["type"],
            template["subtype"],
            template["version"],
        )
        == ("BAN", "ops", "anomaly-record", "1.0")
    )

    assert anomaly["instance_prefix"] == "BAN"
    assert anomaly["json_addl"]["managed_by"] == "bloom"
    assert anomaly["json_addl"]["semantic_category"] == "observability_anomaly"


def test_prefix_taxonomy_rejects_forbidden_letters_and_leading_zero_examples() -> None:
    prefixes = {
        template["instance_prefix"]
        for template in _template_pack()["templates"]
        if template.get("instance_prefix")
    }
    registry = json.loads(
        (
            PROJECT_ROOT / "bloom_lims" / "etc" / "prefix_ownership_registry.json"
        ).read_text(encoding="utf-8")
    )
    prefixes.update(registry["ownership"]["Z"])

    assert all(not (set(prefix) & FORBIDDEN_PREFIX_CHARS) for prefix in prefixes)
    for bad_prefix in ("BCL", "BRI", "BRO", "BRU", "BNL", "BDL"):
        assert bad_prefix not in prefixes

    assert validate_euid("BCP1")
    assert validate_euid("BD1")
    with pytest.raises(ValidationError, match="No leading zeros"):
        validate_euid("BCP01")


def test_prefixes_are_declared_in_packaged_ownership_registry() -> None:
    registry = json.loads(
        (
            PROJECT_ROOT / "bloom_lims" / "etc" / "prefix_ownership_registry.json"
        ).read_text(encoding="utf-8")
    )
    claims = registry["ownership"]["Z"]

    for prefix in {
        "BAN",
        "BC",
        "BCT",
        "BCP",
        "BCW",
        "BCB",
        "BCF",
        "BCE",
        "BCR",
        "BN",
        "BNB",
        "BNS",
        "BNA",
        "BNG",
        "BNC",
        "BNQ",
        "BNP",
        "BNR",
        "BNX",
        "BNK",
        "BD",
        "BDQ",
        "BDX",
        "BDY",
        "BDP",
        "BDN",
        "BDA",
        "BDT",
        "BR",
        "BRM",
        "BRN",
        "BRT",
        "BRP",
        "BRC",
        "BG",
        "BGX",
        "BGM",
        "BGP",
        "BGV",
        "BGR",
        "BGS",
    }:
        assert claims[prefix]["issuer_app_code"] == "bloom"


def test_readme_documents_taxonomy_and_historical_object_rule() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    for snippet in (
        "BC*` | Containers",
        "BN*` | Contents, materials, and reagents",
        "BD*` | Data and evidence objects",
        "BR*` | Runs and executions",
        "BG*` | Generic helpers and external-object mappings",
        "Existing historical objects keep their already minted EUIDs",
        "Prefixes are governance and display labels only",
    ):
        assert snippet in readme
