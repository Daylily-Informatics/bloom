"""Regression checks for dynamic action schema hydration."""

from __future__ import annotations

from types import SimpleNamespace

from bloom_lims.gui.actions import hydrate_dynamic_action_groups


def test_hydrate_dynamic_action_groups_removes_retired_assay_markup():
    action_groups = {
        "core": {
            "group_name": "Core Actions",
            "actions": {
                "action/core/add_container_to_assay_q/1.0": {
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

    original_action = action_groups["core"]["actions"][
        "action/core/add_container_to_assay_q/1.0"
    ]
    hydrated_action = hydrated["core"]["actions"][
        "action/core/add_container_to_assay_q/1.0"
    ]

    assert original_action["captured_data"] == {}
    assert "___workflow/assay/" not in hydrated_action["captured_data"]
    assert hydrated_action["ui_schema"]["fields"] == []


def test_hydrate_dynamic_action_groups_adds_relationship_type_dropdown():
    action_groups = {
        "core": {
            "group_name": "Core Actions",
            "actions": {
                "action/core/add-relationships/1.0": {
                    "method_name": "do_action_add_relationships",
                    "capture_data": "yes",
                    "captured_data": {},
                    "ui_schema": {"title": "Add Relationships", "fields": []},
                }
            },
        }
    }

    hydrated = hydrate_dynamic_action_groups(action_groups, SimpleNamespace())
    fields = hydrated["core"]["actions"]["action/core/add-relationships/1.0"][
        "ui_schema"
    ]["fields"]
    relationship_field = next(
        field for field in fields if field["name"] == "relationship_type"
    )

    assert relationship_field["type"] == "select"
    assert relationship_field["required"] is True
    assert {"value": "derived_from", "label": "derived_from"} in relationship_field[
        "options"
    ]
    assert {
        "value": "beta_sequencing_run",
        "label": "beta_sequencing_run",
    } in relationship_field["options"]


def test_hydrate_dynamic_action_groups_hides_subject_decision_scope_action():
    action_groups = {
        "core": {
            "group_name": "Core Actions",
            "actions": {
                "action/core/create-subject-and-anchor/1.0": {
                    "method_name": "do_action_create_subject_and_anchor",
                    "action_visible": "0",
                    "capture_data": "yes",
                    "captured_data": {},
                    "ui_schema": {"title": "Create Subject", "fields": []},
                }
            },
        }
    }

    hydrated = hydrate_dynamic_action_groups(action_groups, SimpleNamespace())

    assert hydrated["core"]["actions"] == {}
