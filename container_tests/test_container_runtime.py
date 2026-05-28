from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bloom_lims import container_entry

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_docker_runtime_files_use_foreground_uv_and_no_legacy_runtime() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (PROJECT_ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "uv sync --frozen --no-dev --no-install-project" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "COPY auth ./auth" in dockerfile
    assert "COPY config ./config" in dockerfile
    assert "COPY static ./static" in dockerfile
    assert "COPY templates ./templates" in dockerfile
    assert "USER lsmc" in dockerfile
    assert "python\", \"-m\", \"bloom_lims.container_entry" in dockerfile
    assert ":latest" not in dockerfile
    assert "conda" not in dockerfile.lower()
    assert "tmux" not in entrypoint
    assert "background" not in entrypoint
    assert "${BLOOM_CONFIG_PATH:?BLOOM_CONFIG_PATH is required}" in entrypoint


def test_bloom_gui_is_required_in_container_runtime() -> None:
    app_source = (PROJECT_ROOT / "bloom_lims" / "app.py").read_text(encoding="utf-8")

    assert "from bloom_lims.gui.router import router as gui_router" in app_source
    assert "Skipping GUI router" not in app_source
    assert "Bloom GUI router could not be loaded" in app_source


def test_container_entry_requires_absolute_config_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLOOM_CONFIG_PATH", "relative.yaml")

    with pytest.raises(RuntimeError, match="must be an absolute path"):
        container_entry._required_absolute_file("BLOOM_CONFIG_PATH")


def test_container_entry_runs_foreground_http_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "bloom.yaml"
    config_path.write_text("auth: {}\n", encoding="utf-8")
    monkeypatch.setenv("BLOOM_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8912")

    with (
        patch("bloom_lims.container_entry._initialize_cli_runtime") as init_runtime,
        patch("bloom_lims.container_entry._start_server") as start,
    ):
        container_entry.main()

    init_runtime.assert_called_once_with(config_path)
    assert start.call_args.kwargs == {
        "port": 8912,
        "host": "127.0.0.1",
        "reload": False,
        "background": False,
        "ssl": False,
        "cert": None,
        "key": None,
    }
