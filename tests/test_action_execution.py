"""Focused tests for modern action execution service."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bloom_lims.core import action_execution as action_exec


class _FakeDB:
    def __init__(self):
        self.session = SimpleNamespace(flush=lambda: None)

    def close(self):
        return None


class _FakeQueryObj:
    def __init__(self, instance):
        self._instance = instance
        self.session = SimpleNamespace(flush=lambda: None)

    def get_by_euid(self, _euid):
        return self._instance


class _FakeExecutor:
    def set_actor_context(self, **_kwargs):
        return self


class _SuccessDispatcher:
    def __init__(self, _executor):
        pass

    def execute_action(self, **_kwargs):
        return {"status": "success", "message": "done"}


class _ErrorDispatcher:
    def __init__(self, _executor):
        pass

    def execute_action(self, **_kwargs):
        return {"status": "error", "message": "No handler for action"}


def test_execute_action_backfills_missing_template_uid(monkeypatch):
    instance = SimpleNamespace(
        euid="OB-1",
        category="container",
        json_addl={
            "action_groups": {
                "core": {
                    "actions": {
                        "/core/set-object-status/": {
                            "action_name": "Set Status",
                            "method_name": "do_action_set_object_status",
                            "capture_data": "yes",
                            "captured_data": {},
                            "ui_schema": {"title": "Set Status", "fields": []},
                        }
                    }
                }
            }
        },
    )

    fake_db = _FakeDB()
    query_obj = _FakeQueryObj(instance)
    backfilled = {}

    monkeypatch.setattr(action_exec, "BLOOMdb3", lambda app_username: fake_db)
    monkeypatch.setattr(action_exec, "BloomObj", lambda _bdb: query_obj)
    monkeypatch.setattr(action_exec, "_resolve_executor", lambda _instance, _bdb: _FakeExecutor())
    monkeypatch.setattr(action_exec, "BloomTapDBActionDispatcher", _SuccessDispatcher)
    monkeypatch.setattr(
        action_exec,
        "_resolve_action_template_uid",
        lambda _query_obj, _action_def, _action_key: "123e4567-e89b-12d3-a456-426614174000",
    )

    def _capture_backfill(**kwargs):
        backfilled.update(kwargs)

    monkeypatch.setattr(action_exec, "_backfill_action_template_uid", _capture_backfill)

    request = action_exec.ActionExecuteRequest(
        euid="OB-1",
        action_group="core",
        action_key="/core/set-object-status/",
        captured_data={"object_status": "in_progress"},
    )

    result = action_exec.execute_action_for_instance(
        request,
        app_username="test-user",
        actor_email="test@example.com",
        actor_user_id="user-1",
    )

    assert result["status"] == "success"
    assert result["message"] == "done"
    assert backfilled["action_group"] == "core"
    assert backfilled["action_template_uid"] == "123e4567-e89b-12d3-a456-426614174000"


def test_execute_action_surfaces_dispatcher_errors(monkeypatch):
    instance = SimpleNamespace(
        euid="OB-2",
        category="container",
        json_addl={
            "action_groups": {
                "core": {
                    "actions": {
                        "/core/print-barcode-label/": {
                            "action_name": "Print",
                            "method_name": "do_action_print_barcode_label",
                            "action_template_uid": "123e4567-e89b-12d3-a456-426614174111",
                            "capture_data": "no",
                            "captured_data": {},
                            "ui_schema": {"title": "Print", "fields": []},
                        }
                    }
                }
            }
        },
    )

    fake_db = _FakeDB()
    query_obj = _FakeQueryObj(instance)

    monkeypatch.setattr(action_exec, "BLOOMdb3", lambda app_username: fake_db)
    monkeypatch.setattr(action_exec, "BloomObj", lambda _bdb: query_obj)
    monkeypatch.setattr(action_exec, "_resolve_executor", lambda _instance, _bdb: _FakeExecutor())
    monkeypatch.setattr(action_exec, "BloomTapDBActionDispatcher", _ErrorDispatcher)

    request = action_exec.ActionExecuteRequest(
        euid="OB-2",
        action_group="core",
        action_key="/core/print-barcode-label/",
        captured_data={},
    )

    with pytest.raises(action_exec.ActionExecutionError) as exc:
        action_exec.execute_action_for_instance(
            request,
            app_username="test-user",
            actor_email="test@example.com",
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert "No handler for action" in exc.value.detail
