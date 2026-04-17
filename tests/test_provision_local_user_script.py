from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def load_module(name: str, relative_path: str):
    path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROVISION = load_module(
    "provision_local_user_script", "scripts/provision_local_user.py"
)


def test_main_persists_canonical_role_with_uid(monkeypatch, capsys):
    calls: list[tuple[object, object]] = []
    added_groups: list[tuple[str, str, str]] = []
    committed: list[str] = []
    rolled_back: list[str] = []
    closed: list[str] = []

    class FakeSession:
        def commit(self):
            committed.append("commit")

        def rollback(self):
            rolled_back.append("rollback")

    class FakeDB:
        def __init__(self, *args, **kwargs):
            self.session = FakeSession()

        def close(self):
            closed.append("close")

    class FakeGroupService:
        def __init__(self, _session):
            self._session = _session

        def ensure_system_groups(self):
            return None

        def add_user_to_group(self, *, group_code: str, user_id: str, added_by: str):
            added_groups.append((group_code, user_id, added_by))

    monkeypatch.setattr(PROVISION, "BLOOMdb3", FakeDB)
    monkeypatch.setattr(
        PROVISION,
        "create_or_get",
        lambda *_args, **_kwargs: (
            SimpleNamespace(
                uid=42,
                euid="BMUSR00042",
                username="dayhoff@lsmc.bio",
                email="dayhoff@lsmc.bio",
            ),
            True,
        ),
    )
    monkeypatch.setattr(
        PROVISION,
        "set_user_role",
        lambda _session, identifier, role: (
            calls.append((identifier, role)),
            True,
        )[1],
    )
    monkeypatch.setattr(PROVISION, "GroupService", FakeGroupService)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "provision_local_user.py",
            "--username",
            "dayhoff@lsmc.bio",
            "--email",
            "dayhoff@lsmc.bio",
            "--name",
            "dayhoff@lsmc.bio",
            "--role",
            "admin",
            "--group",
            "ENABLE_ATLAS_API",
            "--json",
        ],
    )

    result = PROVISION.main()

    assert result == 0
    assert calls == [(42, "ADMIN")]
    assert added_groups == [("ENABLE_ATLAS_API", "42", "42")]
    assert committed == ["commit"]
    assert rolled_back == []
    assert closed == ["close"]
    assert '"uid": 42' in capsys.readouterr().out
