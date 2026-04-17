from __future__ import annotations

from bloom_lims.auth.repositories.tapdb import users as repo


def test_user_select_sql_targets_sys_actor_users() -> None:
    assert "gi.category = 'SYS'" in repo._USER_SELECT_SQL
    assert "gi.category = 'generic'" not in repo._USER_SELECT_SQL


def test_set_user_role_updates_sys_actor_user_by_uid() -> None:
    calls: list[dict[str, object]] = []

    class FakeResult:
        @staticmethod
        def fetchone():
            return (42,)

    class FakeSession:
        def execute(self, statement, params):
            calls.append({"sql": str(statement), "params": dict(params)})
            return FakeResult()

    assert repo.set_user_role(FakeSession(), 42, "ADMIN") is True
    assert "gi.category = 'SYS'" in calls[0]["sql"]
    assert calls[0]["params"] == {"uid": 42, "role": "ADMIN"}
