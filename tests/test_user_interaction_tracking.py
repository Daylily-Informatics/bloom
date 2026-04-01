"""Unit tests for user actor interaction tracking."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from bloom_lims.domain.base import BloomObj


def _build_bloom_obj_stub() -> BloomObj:
    bo = BloomObj.__new__(BloomObj)
    bo.logger = MagicMock()
    bo.session = MagicMock()
    bo._actor_user_id = None
    bo._actor_email = None
    return bo


def test_track_user_interaction_creates_lineage_from_actor():
    bo = _build_bloom_obj_stub()
    bo._upsert_user_actor = MagicMock(return_value=SimpleNamespace(euid="BAR-1"))
    bo.get_by_euid = MagicMock(
        return_value=SimpleNamespace(euid="BCN-35", is_deleted=False)
    )
    bo.create_generic_instance_lineage_by_euids = MagicMock()

    actor_euid = BloomObj.track_user_interaction(
        bo,
        "BCN-35",
        relationship_type="user_created",
        action_ds={"curr_user": {"email": "user@lsmc.com", "cognito_sub": "sub-1"}},
    )

    assert actor_euid == "BAR-1"
    bo._upsert_user_actor.assert_called_once_with(user_id="sub-1", email="user@lsmc.com")
    bo.create_generic_instance_lineage_by_euids.assert_called_once_with(
        "BAR-1",
        "BCN-35",
        relationship_type="user_created",
    )
    bo.session.commit.assert_called_once()


def test_track_user_interaction_skips_when_target_not_found():
    bo = _build_bloom_obj_stub()
    bo._upsert_user_actor = MagicMock(return_value=SimpleNamespace(euid="BAR-1"))
    bo.get_by_euid = MagicMock(return_value=None)
    bo.create_generic_instance_lineage_by_euids = MagicMock()

    actor_euid = BloomObj.track_user_interaction(bo, "MISSING-EUID")

    assert actor_euid is None
    bo.create_generic_instance_lineage_by_euids.assert_not_called()
    bo.session.commit.assert_not_called()


def test_do_action_base_tracks_user_action_lineage(monkeypatch):
    bo = _build_bloom_obj_stub()
    action_name = "action/core/set_object_status/1.0"
    now_dt = "2026-03-03 12:34:56"
    action_ds = {"deactivate_actions_when_executed": [], "curr_user": "user@lsmc.com"}
    bobj = SimpleNamespace(
        json_addl={
            "action_groups": {
                "core": {
                    "actions": {
                        action_name: {
                            "action_executed": "0",
                            "max_executions": "-1",
                            "executed_datetime": [],
                            "action_user": [],
                            "action_enabled": "1",
                        }
                    }
                }
            }
        }
    )
    bo.get_by_euid = MagicMock(return_value=bobj)
    bo.track_user_interaction = MagicMock()
    monkeypatch.setattr("bloom_lims.domain.base.flag_modified", lambda *_args, **_kwargs: None)

    result = BloomObj._do_action_base(bo, "BCN-35", action_name, "core", action_ds, now_dt)

    assert result is bobj
    action_state = bobj.json_addl["action_groups"]["core"]["actions"][action_name]
    assert action_state["action_executed"] == "1"
    assert action_state["executed_datetime"] == [now_dt]
    assert action_state["action_user"] == ["user@lsmc.com"]
    bo.session.commit.assert_called_once()
    bo.track_user_interaction.assert_called_once_with(
        "BCN-35",
        relationship_type=f"user_action:{action_name}",
        action_ds=action_ds,
    )
