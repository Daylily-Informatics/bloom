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
    assert "USER lsmc" in dockerfile
    assert "python\", \"-m\", \"bloom_lims.container_entry" in dockerfile
    assert ":latest" not in dockerfile
    assert "conda" not in dockerfile.lower()
    assert "tmux" not in entrypoint
    assert "background" not in entrypoint
    assert "${BLOOM_CONFIG_PATH:?BLOOM_CONFIG_PATH is required}" in entrypoint


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

    with patch("bloom_lims.container_entry._start_server") as start:
        container_entry.main()

    assert start.call_args.kwargs == {
        "port": 8912,
        "host": "127.0.0.1",
        "reload": False,
        "background": False,
        "ssl": False,
        "cert": None,
        "key": None,
    }
