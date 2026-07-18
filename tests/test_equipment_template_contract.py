"""Equipment template contracts for the Bjuice sequencing backfill."""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CATALOG = {
    ("generic", "1.0"),
    ("novaseq-6000", "1.1"),
    ("novaseq-x-series", "1.0"),
    ("ont-minion", "1.1"),
    ("ont-promethion", "1.0"),
    ("ultima-ug-100", "1.0"),
    ("ultima-ug-200-series", "1.0"),
    ("pacbio-revio", "1.0"),
    ("pacbio-vega", "1.0"),
    ("pacbio-sequel-ii", "1.0"),
    ("pacbio-sequel-iie", "1.0"),
    ("pacbio-onso", "1.0"),
}
CANONICAL_PROPERTIES = {
    "comments",
    "identification_notes",
    "instrument_id",
    "lab_code",
    "lifecycle_status",
    "location",
    "manufacturer",
    "model",
    "model_family",
    "name",
    "operational_status",
    "product_documentation_url",
    "room",
    "serial_number",
}


def _equipment_templates() -> dict[tuple[str, str], dict]:
    pack = json.loads(
        (
            PROJECT_ROOT / "config" / "tapdb_templates" / "bloom" / "templates.json"
        ).read_text(encoding="utf-8")
    )
    return {
        (template["subtype"], template["version"]): template
        for template in pack["templates"]
        if template["category"] == "equipment" and template["type"] == "sequencers"
    }


def test_exact_additive_equipment_catalog_is_packaged() -> None:
    templates = _equipment_templates()

    assert EXPECTED_CATALOG <= templates.keys()
    assert ("novaseq-6000", "1.0") in templates
    assert ("ont-minion", "1.0") in templates


def test_new_equipment_templates_share_prefix_and_canonical_properties() -> None:
    templates = _equipment_templates()

    for key in EXPECTED_CATALOG:
        template = templates[key]
        assert template["instance_prefix"] == "BEQ"
        assert template["polymorphic_discriminator"] == "equipment_template"
        assert template["instance_polymorphic_identity"] == "equipment_instance"
        assert template["bstatus"] == "active"
        assert template["is_singleton"] is False
        assert template["json_addl"]["semantic_category"] == "equipment"
        properties = template["json_addl"]["properties"]
        assert set(properties) == CANONICAL_PROPERTIES
        assert "serial" not in properties
        assert "operataional_status" not in properties


def test_equipment_catalog_artifact_matches_authoritative_pack() -> None:
    artifact_path = (
        PROJECT_ROOT
        / "docs"
        / "plans"
        / "20260718T044845Z_bjuice_atlas_bloom_templates_backfill_artifacts"
        / "bloom_equipment_template_catalog.json"
    )
    catalog = json.loads(artifact_path.read_text(encoding="utf-8"))
    catalog_keys = {(row["subtype"], row["version"]) for row in catalog}

    assert catalog_keys == EXPECTED_CATALOG
    for row in catalog:
        assert row["instance_prefix"] == "BEQ"
        assert row["is_singleton"] is False
        assert row["bstatus"] == "active"

    by_key = {(row["subtype"], row["version"]): row for row in catalog}
    assert by_key[("novaseq-6000", "1.1")]["lifecycle_status"] == "current"
    assert (
        _equipment_templates()[("novaseq-6000", "1.1")]["json_addl"]["properties"][
            "lifecycle_status"
        ]
        == "current"
    )
