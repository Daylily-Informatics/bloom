from __future__ import annotations

from types import SimpleNamespace

from cli_core_yo import runtime as cli_runtime
from daylily_tapdb.cli import context as tapdb_context

import bloom_lims.config as bloom_config


def test_container_entry_initializes_cli_runtime(monkeypatch, tmp_path):
    import bloom_lims.container_entry as entry

    config_path = tmp_path / "bloom.yaml"
    config_path.write_text("application: {}\n", encoding="utf-8")
    monkeypatch.setenv("BLOOM_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("PORT", "8912")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("DEPLOYMENT_CODE", "inf9")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg" / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg" / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg" / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg" / "cache"))

    observed: dict[str, object] = {}

    def fake_start(**kwargs: object) -> None:
        observed["kwargs"] = kwargs
        observed["config_path"] = cli_runtime.get_context().config_path

    monkeypatch.setattr(entry, "_start_server", fake_start)
    monkeypatch.setattr(
        entry,
        "_initialize_tapdb_context",
        lambda: observed.update({"tapdb_context_initialized": True}),
    )
    monkeypatch.setattr(
        entry,
        "_verify_existing_tapdb",
        lambda: observed.update({"tapdb_existing_verified": True}),
    )
    cli_runtime._reset()
    try:
        entry.main()
    finally:
        cli_runtime._reset()

    assert observed["config_path"] == config_path
    assert observed["tapdb_context_initialized"] is True
    assert observed["tapdb_existing_verified"] is True
    assert observed["kwargs"] == {
        "port": 8912,
        "host": "0.0.0.0",
        "reload": False,
        "background": False,
        "ssl": False,
        "cert": None,
        "key": None,
    }


def test_container_entry_sets_exact_tapdb_cli_context(monkeypatch, tmp_path):
    import bloom_lims.container_entry as entry

    config_path = tmp_path / "tapdb.yaml"
    config_path.write_text("meta: {}\n", encoding="utf-8")
    observed: dict[str, object] = {}

    monkeypatch.setattr(bloom_config, "get_settings", lambda: object())
    monkeypatch.setattr(
        bloom_config,
        "apply_runtime_environment",
        lambda _settings: SimpleNamespace(
            client_id="bloom",
            database_name="bloom-day",
            config_path=str(config_path),
        ),
    )
    monkeypatch.setattr(
        tapdb_context,
        "set_cli_context",
        lambda **kwargs: observed.update(kwargs),
    )

    entry._initialize_tapdb_context()

    assert observed == {
        "client_id": "bloom",
        "database_name": "bloom-day",
        "config_path": config_path,
    }


def test_container_entry_verifies_released_templates_without_seeding(monkeypatch):
    import daylily_tapdb
    from daylily_tapdb.templates import loader

    import bloom_lims.container_entry as entry
    import bloom_lims.tapdb_adapter as adapter

    observed: dict[str, object] = {}

    class FakeDB:
        domain_code = "M"
        session = object()

        def __init__(self, *, app_username):
            observed["actor"] = app_username

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(adapter, "BLOOMdb3", FakeDB)
    monkeypatch.setattr(
        loader,
        "load_template_configs",
        lambda _root: [
            {
                "category": "material",
                "type": "specimen",
                "subtype": "blood-whole",
                "version": "1.0",
                "instance_prefix": "persisted-prefix",
            }
        ],
    )
    monkeypatch.setattr(
        daylily_tapdb,
        "require_seeded_templates",
        lambda session, requirements, **kwargs: observed.update(
            {"session": session, "requirements": requirements, **kwargs}
        ),
    )

    entry._verify_existing_tapdb()

    assert observed["actor"] == "bloom-startup-verify-existing"
    assert observed["domain_code"] == "M"
    assert observed["app_name"] == "Bloom"
    assert (
        "material/specimen/blood-whole/1.0/",
        "PERSISTED-PREFIX",
    ) in observed["requirements"]
    assert len(observed["requirements"]) == 3
