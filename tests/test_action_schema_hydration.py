"""Regression checks for dynamic action schema hydration."""

from __future__ import annotations

from types import SimpleNamespace

from bloom_lims.gui.actions import hydrate_dynamic_action_groups


class _FakeBloomObj:
    def query_instance_by_component_v2(self, *, category: str, type: str):
        assert category == "workflow"
        assert type == "assay"
        return [
            SimpleNamespace(
                euid="AY-1",
                subtype="generic",
                version="1.0",
                name="Assay One",
                json_addl={"properties": {"name": "Assay One"}},
                is_deleted=False,
            )
        ]


def test_hydrate_dynamic_action_groups_backfills_legacy_assay_markup_from_ui_schema():
    action_groups = {
        "test_requisitions": {
            "group_name": "Test Requisitions",
            "actions": {
                "action/test_requisitions/add_container_to_assay_q/1.0": {
                    "method_name": "do_action_add_container_to_assay_q",
                    "capture_data": "yes",
                    "captured_data": {},
                    "ui_schema": {
                        "title": "Add Specimen to Assay Queue",
                        "fields": [
                            {
                                "name": "assay_selection",
                                "type": "select",
                                "required": True,
                                "options_source": "workflow_assays",
                            }
                        ],
                    },
                }
            },
        }
    }

    hydrated = hydrate_dynamic_action_groups(action_groups, _FakeBloomObj())

    original_action = action_groups["test_requisitions"]["actions"]["action/test_requisitions/add_container_to_assay_q/1.0"]
    hydrated_action = hydrated["test_requisitions"]["actions"]["action/test_requisitions/add_container_to_assay_q/1.0"]

    assert original_action["captured_data"] == {}
    assert 'name="assay_selection"' in hydrated_action["captured_data"]["___workflow/assay/"]
    assert 'value="AY-1"' in hydrated_action["captured_data"]["___workflow/assay/"]
    assert hydrated_action["ui_schema"]["fields"][0]["options"] == [
        {"value": "AY-1", "label": "Assay One (generic v1.0) [AY-1]"}
    ]