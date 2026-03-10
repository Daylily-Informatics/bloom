"""Regression checks for dynamic action schema hydration."""

from __future__ import annotations

from types import SimpleNamespace

from bloom_lims.gui.actions import hydrate_dynamic_action_groups


def test_hydrate_dynamic_action_groups_removes_retired_assay_markup():
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

    hydrated = hydrate_dynamic_action_groups(action_groups, SimpleNamespace())

    original_action = action_groups["test_requisitions"]["actions"]["action/test_requisitions/add_container_to_assay_q/1.0"]
    hydrated_action = hydrated["test_requisitions"]["actions"]["action/test_requisitions/add_container_to_assay_q/1.0"]

    assert original_action["captured_data"] == {}
    assert "___workflow/assay/" not in hydrated_action["captured_data"]
    assert hydrated_action["ui_schema"]["fields"] == []
