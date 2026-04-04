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


MIGRATION = load_module("migrate_bloom_user_roles", "scripts/migrate_bloom_user_roles.py")


def test_infer_role_from_groups_prefers_admin_over_other_groups():
    assert MIGRATION._infer_role_from_groups(["bloom-readwrite", "bloom-admin"]) == "ADMIN"
    assert MIGRATION._infer_role_from_groups(["bloom-readwrite", "bloom-readonly"]) == "READ_WRITE"
    assert MIGRATION._infer_role_from_groups(["bloom-readonly"]) == "READ_ONLY"


def test_migrate_roles_uppercases_and_infers_missing_roles(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeSession:
        def commit(self):
            calls.append(("commit", ""))

        def rollback(self):
            calls.append(("rollback", ""))

    class FakeDB:
        def __init__(self, *args, **kwargs):
            self.session = FakeSession()

        def close(self):
            calls.append(("close", ""))

    users = [
        SimpleNamespace(uid=1, username="one@example.com", email="one@example.com", role="admin"),
        SimpleNamespace(uid=2, username="two@example.com", email="two@example.com", role=""),
        SimpleNamespace(uid=3, username="three@example.com", email="three@example.com", role=None),
    ]

    group_memberships = {
        "1": [],
        "one@example.com": [],
        "two@example.com": ["bloom-readwrite"],
        "3": ["bloom-admin"],
        "three@example.com": ["bloom-admin"],
    }

    class FakeGroupService:
        def __init__(self, _session):
            self._session = _session

        def ensure_system_groups(self):
            return None

        def get_group_codes_for_user(self, user_id):
            return list(group_memberships.get(str(user_id), []))

        def remove_user_from_group(self, *, group_code, user_id, removed_by):
            calls.append((f"remove:{user_id}", str(group_code)))
            return object()

    def fake_set_user_role(_session, identifier, role):
        calls.append((str(identifier), role))
        return True

    monkeypatch.setattr(MIGRATION, "BLOOMdb3", FakeDB)
    monkeypatch.setattr(MIGRATION, "GroupService", FakeGroupService)
    monkeypatch.setattr(MIGRATION, "set_user_role", fake_set_user_role)
    monkeypatch.setattr(MIGRATION, "list_users", lambda _session, include_inactive=True: users)

    result = MIGRATION.migrate_roles(dry_run=False)

    assert result["count"] == 3
    assert result["removed_count"] == 2
    assert ("one@example.com", "ADMIN") in calls
    assert ("two@example.com", "READ_WRITE") in calls
    assert ("three@example.com", "ADMIN") in calls
    assert ("remove:2", "bloom-readwrite") in calls
    assert ("remove:3", "bloom-admin") in calls
    assert ("commit", "") in calls
