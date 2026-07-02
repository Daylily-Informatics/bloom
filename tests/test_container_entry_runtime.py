from __future__ import annotations

from cli_core_yo import runtime as cli_runtime


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
    cli_runtime._reset()
    try:
        entry.main()
    finally:
        cli_runtime._reset()

    assert observed["config_path"] == config_path
    assert observed["kwargs"] == {
        "port": 8912,
        "host": "0.0.0.0",
        "reload": False,
        "background": False,
        "ssl": False,
        "cert": None,
        "key": None,
    }
