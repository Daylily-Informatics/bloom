from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bloom_lims.cli import build_app

users_cli = importlib.import_module("bloom_lims.cli.users")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    return build_app()


def test_issue_token_emits_plaintext_token(
    runner: CliRunner,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committed: list[str] = []
    closed: list[str] = []

    class FakeDB:
        def __init__(self, *args, **kwargs):
            self.session = SimpleNamespace(
                commit=lambda: committed.append("commit"),
                rollback=lambda: committed.append("rollback"),
            )

        def close(self):
            closed.append("close")

    class FakeTokenService:
        def __init__(self, _db):
            self.groups = SimpleNamespace(ensure_system_groups=lambda: None)

        def create_token(self, **kwargs):
            assert kwargs["owner_user_id"] == "42"
            assert kwargs["actor_roles"] == ["ADMIN"]
            assert kwargs["actor_groups"] == ["ADMIN", "API_ACCESS"]
            payload = kwargs["payload"]
            assert payload.scope == "admin"
            return SimpleNamespace(
                token=SimpleNamespace(
                    id="tok-1", token_prefix="blm_deadbeef...", scope="admin"
                ),
                plaintext_token="blm_plaintext_demo",
            )

    monkeypatch.setattr(users_cli, "BLOOMdb3", FakeDB)
    monkeypatch.setattr(
        users_cli,
        "get_by_login_or_email",
        lambda _session, identifier, include_inactive=True: SimpleNamespace(
            uid=42, username=identifier
        ),
    )
    monkeypatch.setattr(users_cli, "UserAPITokenService", FakeTokenService)

    result = runner.invoke(
        cli_app,
        [
            "users",
            "issue-token",
            "--username",
            "john@daylilyinformatics.bio",
            "--token-name",
            "atlas-demo",
            "--scope",
            "admin",
        ],
    )

    assert result.exit_code == 0
    assert "token_id=tok-1" in result.output
    assert "plaintext_token=blm_plaintext_demo" in result.output
    assert committed == ["commit"]
    assert closed == ["close"]


def test_provision_local_emits_user_payload(
    runner: CliRunner,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committed: list[str] = []
    closed: list[str] = []
    added_groups: list[tuple[str, str, str]] = []

    class FakeDB:
        def __init__(self, *args, **kwargs):
            self.session = SimpleNamespace(
                commit=lambda: committed.append("commit"),
                rollback=lambda: committed.append("rollback"),
            )

        def close(self):
            closed.append("close")

    class FakeGroupService:
        def __init__(self, _db):
            return None

        def ensure_system_groups(self):
            return None

        def get_group_codes_for_user(self, _user_id):
            return ["API_ACCESS"]

        def add_user_to_group(self, *, group_code: str, user_id: str, added_by: str):
            added_groups.append((group_code, user_id, added_by))

    monkeypatch.setattr(users_cli, "BLOOMdb3", FakeDB)
    monkeypatch.setattr(
        users_cli,
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
    monkeypatch.setattr(users_cli, "set_user_role", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(users_cli, "GroupService", FakeGroupService)

    result = runner.invoke(
        cli_app,
        [
            "users",
            "provision-local",
            "--username",
            "dayhoff@lsmc.bio",
            "--name",
            "dayhoff@lsmc.bio",
            "--role",
            "admin",
            "--group",
            "API_ACCESS",
            "--group",
            "ENABLE_ATLAS_API",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["username"] == "dayhoff@lsmc.bio"
    assert payload["role"] == "ADMIN"
    assert payload["groups"] == ["API_ACCESS", "ENABLE_ATLAS_API"]
    assert added_groups == [("ENABLE_ATLAS_API", "42", "42")]
    assert committed == ["commit"]
    assert closed == ["close"]


def test_issue_token_errors_for_unknown_user(
    runner: CliRunner,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDB:
        def __init__(self, *args, **kwargs):
            self.session = SimpleNamespace(commit=lambda: None, rollback=lambda: None)

        def close(self):
            return None

    monkeypatch.setattr(users_cli, "BLOOMdb3", FakeDB)
    monkeypatch.setattr(
        users_cli,
        "get_by_login_or_email",
        lambda *_args, **_kwargs: None,
    )

    result = runner.invoke(
        cli_app,
        [
            "users",
            "issue-token",
            "--username",
            "missing@example.com",
            "--token-name",
            "atlas-demo",
        ],
    )

    assert result.exit_code != 0
    assert "User not found" in result.output
