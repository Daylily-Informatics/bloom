"""Regression checks for action button rendering in modern templates."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_modern_euid_details_uses_data_attribute_action_handler():
    template = _read("templates/modern/euid_details.html")

    assert "onclick=\"showCapturedDataFormFromDataAttributes(this)\"" in template
    assert "data-action-json=\"{{ action_value | tojson | e }}\"" in template
    assert "onclick=\"showCapturedDataForm(this, {{ action_value | tojson }}" not in template


def test_modern_workflow_details_uses_data_attribute_action_handler():
    template = _read("templates/modern/workflow_details.html")

    assert "onclick=\"showCapturedDataFormFromDataAttributes(this)\"" in template
    assert "data-action-json=\"{{ action_value | tojson | e }}\"" in template
    assert "onclick=\"showCapturedDataForm(this, {{ action_value }}" not in template
    assert "onclick=\"showCapturedDataForm(this, {{ action_value | tojson }}" not in template
