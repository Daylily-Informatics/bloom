"""Tests for GUI action-group hydration/backfill behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from bloom_lims.gui.actions import hydrate_dynamic_action_groups


def test_hydrate_dynamic_action_groups_backfills_missing_schema_fields():
    action_groups = {
        "core": {
            "group_name": "Core Actions",
            "group_order": "1",
            "actions": {
                "action/core/set_object_status/1.0": {
                    "action_name": "Set Status",
                    "method_name": "do_action_set_object_status",
                    "capture_data": "yes",
                    "captured_data": {},
                    "ui_schema": {"title": "Set Status", "fields": []},
                }
            },
        }
    }

    template_action = {
        "capture_data": "yes",
        "ui_schema": {
            "title": "Set Status",
            "fields": [
                {"name": "object_status", "type": "select", "required": True},
            ],
        },
    }
    template = SimpleNamespace(json_addl={"action_template": template_action})
    bobdb = MagicMock()
    bobdb.query_template_by_component_v2.return_value = [template]

    hydrated = hydrate_dynamic_action_groups(action_groups, bobdb)
    fields = hydrated["core"]["actions"]["action/core/set_object_status/1.0"]["ui_schema"]["fields"]
    assert isinstance(fields, list)
    assert fields and fields[0]["name"] == "object_status"


def test_hydrate_dynamic_action_groups_syncs_capture_mode_for_one_click_actions():
    action_groups = {
        "test_requisitions": {
            "group_name": "Test Req Actions",
            "group_order": "1",
            "actions": {
                "action/test_requisitions/set_verification_state/1.0": {
                    "action_name": "Verify Test Req",
                    "method_name": "do_action_set_verification_state",
                    "capture_data": "yes",
                    "captured_data": {},
                    "ui_schema": {"title": "Verify Test Req", "fields": []},
                }
            },
        }
    }

    template_action = {"capture_data": "no", "ui_schema": {"title": "Verify Test Req", "fields": []}}
    template = SimpleNamespace(json_addl={"action_template": template_action})
    bobdb = MagicMock()
    bobdb.query_template_by_component_v2.return_value = [template]

    hydrated = hydrate_dynamic_action_groups(action_groups, bobdb)
    action = hydrated["test_requisitions"]["actions"]["action/test_requisitions/set_verification_state/1.0"]
    assert action["capture_data"] == "no"

