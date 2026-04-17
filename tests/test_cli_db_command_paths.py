"""Additional coverage for Bloom DB CLI command wiring."""

from __future__ import annotations

import json
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bloom_lims.cli import build_app
from bloom_lims.config import DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT, DEFAULT_BLOOM_WEB_PORT

db_commands = importlib.import_module("bloom_lims.cli.db")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    return build_app()


def test_run_tapdb_raises_for_nonzero_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_commands, "_tapdb_base_cmd", lambda: ["tapdb"])
    monkeypatch.setattr(
        db_commands,
        "_runtime_env",
        lambda: {
            "AWS_PROFILE": "lsmc",
            "AWS_REGION": "us-west-2",
            "AWS_DEFAULT_REGION": "us-west-2",
            "MERIDIAN_DOMAIN_CODE": "Z",
            "TAPDB_DOMAIN_CODE": "Z",
            "TAPDB_OWNER_REPO": "bloom",
            "TAPDB_DOMAIN_REGISTRY_PATH": "/tmp/domain_code_registry.json",
            "TAPDB_PREFIX_OWNERSHIP_REGISTRY_PATH": "/tmp/prefix_ownership_registry.json",
        },
    )
    monkeypatch.setattr(
        db_commands,
        "apply_runtime_environment",
        lambda _settings: SimpleNamespace(
            config_path="/tmp/bloom-tapdb.yaml",
            env="dev",
            owner_repo_name="bloom",
            domain_code="Z",
            domain_registry_path="/tmp/domain_code_registry.json",
            prefix_ownership_registry_path="/tmp/prefix_ownership_registry.json",
        ),
    )
    captured: dict[str, dict[str, str]] = {}

    def fake_run(cmd, env=None, **_kwargs):
        captured["env"] = env
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(db_commands.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        db_commands._run_tapdb(["db", "setup"], check=True)

    assert exc.value.code == 7
    assert captured["env"]["MERIDIAN_DOMAIN_CODE"] == "Z"
    assert captured["env"]["TAPDB_DOMAIN_CODE"] == "Z"
    assert captured["env"]["TAPDB_OWNER_REPO"] == "bloom"


def test_run_tapdb_returns_nonzero_when_check_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db_commands, "_tapdb_base_cmd", lambda: ["tapdb"])
    monkeypatch.setattr(db_commands, "_runtime_env", lambda: {})
    monkeypatch.setattr(
        db_commands,
        "apply_runtime_environment",
        lambda _settings: SimpleNamespace(
            config_path="/tmp/bloom-tapdb.yaml",
            env="dev",
        ),
    )
    monkeypatch.setattr(
        db_commands.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=3),
    )

    assert db_commands._run_tapdb(["db", "setup"], check=False) == 3


def test_update_tapdb_namespace_config_uses_db_config_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(
        db_commands, "_tapdb_support_email", lambda _env: "support@example.com"
    )
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append((args, check)) or 0,
    )

    db_commands._update_tapdb_namespace_config("dev")

    assert calls == [
        (
            [
                "db-config",
                "update",
                "--env",
                "dev",
                "--support-email",
                "support@example.com",
            ],
            True,
        )
    ]


def test_ensure_tapdb_namespace_config_initializes_then_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(
        db_commands,
        "apply_runtime_environment",
        lambda _settings: SimpleNamespace(
            client_id="bloom",
            database_name="bloom",
            config_path="/tmp/.config/tapdb/bloom/bloom-local2/tapdb-config.yaml",
            env="dev",
            aws_profile="lsmc",
            aws_region="us-west-2",
            owner_repo_name="bloom",
            domain_code="Z",
            domain_registry_path="/tmp/domain_code_registry.json",
            prefix_ownership_registry_path="/tmp/prefix_ownership_registry.json",
        ),
    )
    monkeypatch.setattr(
        db_commands,
        "_local_pg_port",
        lambda _env: str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT),
    )
    monkeypatch.setattr(
        db_commands, "_local_ui_port", lambda _env: str(DEFAULT_BLOOM_WEB_PORT)
    )
    monkeypatch.setattr(
        db_commands, "_tapdb_support_email", lambda _env: "support@example.com"
    )
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append((args, check)) or 0,
    )

    db_commands._ensure_tapdb_namespace_config("dev")

    assert calls == [
        (
            [
                "db-config",
                "init",
                "--client-id",
                "bloom",
                "--database-name",
                "bloom",
                "--owner-repo-name",
                "bloom",
                "--domain-code",
                "dev=Z",
                "--domain-registry-path",
                "/tmp/domain_code_registry.json",
                "--prefix-ownership-registry-path",
                "/tmp/prefix_ownership_registry.json",
                "--env",
                "dev",
                "--db-port",
                "dev=5566",
                "--ui-port",
                "dev=8912",
            ],
            True,
        ),
        (
            [
                "db-config",
                "update",
                "--env",
                "dev",
                "--support-email",
                "support@example.com",
            ],
            True,
        ),
    ]


def test_ensure_tapdb_namespace_config_creates_scoped_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = (
        tmp_path / ".config" / "tapdb" / "bloom" / "bloom-local2" / "tapdb-config.yaml"
    )
    monkeypatch.setattr(
        db_commands,
        "apply_runtime_environment",
        lambda _settings: SimpleNamespace(
            client_id="bloom",
            database_name="bloom",
            config_path=str(config_path),
            env="dev",
            aws_profile="lsmc",
            aws_region="us-west-2",
            owner_repo_name="bloom",
            domain_code="Z",
            domain_registry_path="/tmp/domain_code_registry.json",
            prefix_ownership_registry_path="/tmp/prefix_ownership_registry.json",
        ),
    )
    monkeypatch.setattr(
        db_commands,
        "_local_pg_port",
        lambda _env: str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT),
    )
    monkeypatch.setattr(
        db_commands, "_local_ui_port", lambda _env: str(DEFAULT_BLOOM_WEB_PORT)
    )
    monkeypatch.setattr(
        db_commands, "_tapdb_support_email", lambda _env: "support@example.com"
    )
    monkeypatch.setattr(db_commands, "_run_tapdb", lambda *_args, **_kwargs: 0)

    db_commands._ensure_tapdb_namespace_config("dev")

    assert config_path.parent.exists()


def test_resolve_tapdb_schema_source_skips_dayhoff_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sibling_schema = tmp_path / "daylily-tapdb" / "schema" / "tapdb_schema.sql"
    sibling_schema.parent.mkdir(parents=True, exist_ok=True)
    sibling_schema.write_text("-- sibling schema\n", encoding="utf-8")

    artifact_pkg = (
        tmp_path
        / ".dayhoff"
        / "local"
        / "lsmc5"
        / "repos"
        / "daylily-tapdb"
        / "daylily_tapdb"
        / "__init__.py"
    )
    artifact_pkg.parent.mkdir(parents=True, exist_ok=True)
    artifact_pkg.write_text("# artifact package\n", encoding="utf-8")

    monkeypatch.setattr(db_commands, "_bloom_root", lambda: tmp_path / "bloom")
    monkeypatch.setattr(
        db_commands.importlib,
        "import_module",
        lambda _name: SimpleNamespace(__file__=str(artifact_pkg)),
    )

    assert db_commands._resolve_tapdb_schema_source() == sibling_schema


def test_db_seed_calls_tapdb_template_loader(
    runner: CliRunner,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tapdb_seed: list[tuple[str, bool, bool]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(
        db_commands,
        "_seed_tapdb_templates",
        lambda env_name, include_workflow, overwrite: tapdb_seed.append(
            (env_name, include_workflow, overwrite)
        ),
    )

    result = runner.invoke(cli_app, ["db", "seed"])
    assert result.exit_code == 0
    assert tapdb_seed == [("dev", False, False)]


def test_seed_templates_split_core_and_client_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    core_dir = tmp_path / "core_config"
    client_dir = tmp_path / "config" / "tapdb_templates"
    core_dir.mkdir(parents=True)
    client_dir.mkdir(parents=True)
    core_template_path = tmp_path / "relocated_core" / "system" / "system.json"
    client_template_path = client_dir / "bloom" / "templates.json"
    core_template_path.parent.mkdir(parents=True)
    client_template_path.parent.mkdir(parents=True)
    core_template_path.write_text("[]", encoding="utf-8")
    client_template_path.write_text("[]", encoding="utf-8")

    runtime_ctx = SimpleNamespace(
        domain_code="Z",
        owner_repo_name="bloom",
        domain_registry_path=tmp_path / "domain_code_registry.json",
        prefix_ownership_registry_path=tmp_path / "prefix_ownership_registry.json",
    )
    monkeypatch.setattr(db_commands, "_bloom_root", lambda: tmp_path)
    monkeypatch.setattr(db_commands, "get_settings", lambda: object())
    monkeypatch.setattr(
        db_commands, "apply_runtime_environment", lambda _settings: runtime_ctx
    )
    monkeypatch.setattr(db_commands, "find_tapdb_core_config_dir", lambda: core_dir)
    monkeypatch.setattr(
        db_commands,
        "validate_template_configs",
        lambda _dirs, strict: (
            [
                {
                    "category": "SYS",
                    "type": "system",
                    "subtype": "config",
                    "version": "1.0",
                    "instance_prefix": "SYS",
                    "_source_file": str(core_template_path),
                },
                {
                    "category": "BAC",
                    "type": "beta_lab",
                    "subtype": "claim_material_in_queue",
                    "version": "1.0",
                    "instance_prefix": "BAC",
                    "_source_file": str(client_template_path),
                },
            ],
            [],
        ),
    )

    events: list[tuple[str, object]] = []

    def fake_seed_templates(session, templates, **kwargs):  # noqa: ANN001 - test double
        events.append(
            (
                "seed",
                {
                    "owner_repo_name": kwargs["owner_repo_name"],
                    "templates": [template["instance_prefix"] for template in templates],
                },
            )
        )

    def fake_claim_client_template_prefixes(**kwargs):  # noqa: ANN001 - test double
        events.append(
            (
                "claim",
                {
                    "owner_repo_name": kwargs["owner_repo_name"],
                    "domain_code": kwargs["domain_code"],
                    "templates": [template["instance_prefix"] for template in kwargs["templates"]],
                },
            )
        )

    class FakeSession:
        committed = 0
        rolled_back = 0
        closed = 0
        executed: list[str] = []

        def execute(self, statement):  # noqa: ANN001 - test double
            self.executed.append(getattr(statement, "text", str(statement)))

        def commit(self):
            self.committed += 1

        def rollback(self):
            self.rolled_back += 1

        def close(self):
            self.closed += 1

    class FakeEngine:
        disposed = 0

        def dispose(self):
            self.disposed += 1

    fake_session = FakeSession()
    fake_engine = FakeEngine()
    monkeypatch.setattr(db_commands, "seed_templates", fake_seed_templates)
    monkeypatch.setattr(
        db_commands, "_claim_client_template_prefixes", fake_claim_client_template_prefixes
    )
    monkeypatch.setattr(
        db_commands,
        "BLOOMdb3",
        lambda **_kwargs: SimpleNamespace(session=fake_session, engine=fake_engine),
    )

    db_commands._seed_tapdb_templates("dev", overwrite=False)

    assert events == [
        ("seed", {"owner_repo_name": "daylily-tapdb", "templates": ["SYS"]}),
        (
            "claim",
            {"owner_repo_name": "bloom", "domain_code": "Z", "templates": ["BAC"]},
        ),
        ("seed", {"owner_repo_name": "bloom", "templates": ["BAC"]}),
    ]
    assert any("tapdb_identity_prefix_config" in sql for sql in fake_session.executed)
    assert fake_session.committed == 1
    assert fake_session.rolled_back == 0
    assert fake_session.closed == 1
    assert fake_engine.disposed == 1


def test_claim_client_template_prefixes_writes_registry(
    tmp_path: Path,
) -> None:
    prefix_registry = tmp_path / "prefix_ownership_registry.json"

    db_commands._claim_client_template_prefixes(
        prefix_registry_path=prefix_registry,
        domain_code="Z",
        owner_repo_name="bloom",
        templates=[
            {"instance_prefix": "BAC"},
            {"instance_prefix": "BEX"},
        ],
    )

    payload = json.loads(prefix_registry.read_text(encoding="utf-8"))
    assert payload["version"] == "0.4.0"
    assert payload["ownership"]["Z"]["BAC"]["issuer_app_code"] == "bloom"
    assert payload["ownership"]["Z"]["BEX"]["issuer_app_code"] == "bloom"


def test_claim_client_template_prefixes_ignores_reserved_core_prefixes(
    tmp_path: Path,
) -> None:
    prefix_registry = tmp_path / "prefix_ownership_registry.json"

    db_commands._claim_client_template_prefixes(
        prefix_registry_path=prefix_registry,
        domain_code="Z",
        owner_repo_name="bloom",
        templates=[
            {"instance_prefix": "SYS"},
            {"instance_prefix": "MSG"},
            {"instance_prefix": "BAC"},
        ],
    )

    payload = json.loads(prefix_registry.read_text(encoding="utf-8"))
    assert payload["ownership"]["Z"] == {"BAC": {"issuer_app_code": "bloom"}}


def test_claim_client_template_prefixes_rejects_collision(
    tmp_path: Path,
) -> None:
    prefix_registry = tmp_path / "prefix_ownership_registry.json"
    repo_root = Path(__file__).resolve().parents[1]
    prefix_registry.write_text(
        (repo_root / "bloom_lims" / "etc" / "prefix_ownership_registry.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    payload = json.loads(prefix_registry.read_text(encoding="utf-8"))
    payload["ownership"]["Z"]["BAC"]["issuer_app_code"] = "other-repo"
    prefix_registry.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="claimed by 'other-repo'"):
        db_commands._claim_client_template_prefixes(
            prefix_registry_path=prefix_registry,
            domain_code="Z",
            owner_repo_name="bloom",
            templates=[{"instance_prefix": "BAC"}],
        )


def test_claim_client_template_prefixes_repairs_ownerless_claim(
    tmp_path: Path,
) -> None:
    prefix_registry = tmp_path / "prefix_ownership_registry.json"
    prefix_registry.write_text(
        json.dumps(
            {
                "version": "0.4.0",
                "ownership": {
                    "Z": {
                        "BAC": {},
                    }
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    db_commands._claim_client_template_prefixes(
        prefix_registry_path=prefix_registry,
        domain_code="Z",
        owner_repo_name="bloom",
        templates=[{"instance_prefix": "BAC"}],
    )

    payload = json.loads(prefix_registry.read_text(encoding="utf-8"))
    assert payload["ownership"]["Z"]["BAC"]["issuer_app_code"] == "bloom"


@pytest.mark.parametrize(
    ("force", "expected_calls"),
    [
        (
            False,
            [
                (["pg", "init", "dev"], False),
                (["pg", "start-local", "dev", "--port", str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT)], True),
                (["db", "create", "dev"], False),
                (["db", "schema", "apply", "dev"], True),
                (["db", "schema", "migrate", "dev"], True),
            ],
        ),
        (
            True,
            [
                (["pg", "init", "dev"], False),
                (["pg", "start-local", "dev", "--port", str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT)], True),
                (["db", "delete", "dev", "--force"], False),
                (["db", "create", "dev"], False),
                (["db", "schema", "apply", "dev", "--reinitialize"], True),
                (["db", "schema", "migrate", "dev"], True),
            ],
        ),
    ],
)
def test_db_build_local_runs_explicit_tapdb_steps_before_bloom_seed(
    monkeypatch: pytest.MonkeyPatch,
    force: bool,
    expected_calls: list[tuple[list[str], bool]],
) -> None:
    calls: list[tuple[list[str], bool]] = []
    seeded: list[tuple[str, bool]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(db_commands, "_ensure_tapdb_namespace_config", lambda _env: None)
    monkeypatch.setattr(db_commands, "_ensure_schema_available_for_bloom_root", lambda: None)
    monkeypatch.setattr(
        db_commands,
        "_local_pg_port",
        lambda _env: str(DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT),
    )
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append((args, check)) or 0,
    )
    monkeypatch.setattr(
        db_commands,
        "_seed_tapdb_templates",
        lambda env_name, overwrite=False, **_kwargs: seeded.append((env_name, overwrite)),
    )

    db_commands.db_build(force=force)

    assert calls == expected_calls
    assert seeded == [("dev", force)]


@pytest.mark.parametrize(
    ("force", "expected_args"),
    [
        (False, ["db", "schema", "reset", "dev"]),
        (True, ["db", "schema", "reset", "dev", "--force"]),
    ],
)
def test_db_nuke_calls_tapdb_schema_reset(
    runner: CliRunner,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
    force: bool,
    expected_args: list[str],
) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(db_commands, "_current_env", lambda: "dev")
    monkeypatch.setattr(
        db_commands,
        "_run_tapdb",
        lambda args, check=True: calls.append((args, check)) or 0,
    )

    argv = ["db", "nuke"]
    if force:
        argv.append("--force")

    result = runner.invoke(cli_app, argv)
    assert result.exit_code == 0
    assert calls == [(expected_args, True)]
