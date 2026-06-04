"""Container foreground entrypoint for Bloom."""

from __future__ import annotations

import os
from pathlib import Path


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _required_absolute_file(name: str) -> Path:
    path = Path(_required_env(name))
    if not path.is_absolute():
        raise RuntimeError(f"{name} must be an absolute path")
    if not path.is_file():
        raise RuntimeError(f"{name} does not exist: {path}")
    return path


def _start_server(**kwargs: object) -> None:
    from bloom_lims.cli.server import start

    start(**kwargs)


def _initialize_runtime_context(config_path: Path) -> None:
    from cli_core_yo.errors import ContextNotInitializedError
    from cli_core_yo.runtime import get_context, initialize
    from cli_core_yo.xdg import resolve_paths

    from bloom_lims.cli import spec

    try:
        get_context()
        return
    except ContextNotInitializedError:
        pass

    initialize(
        spec,
        resolve_paths(spec.xdg),
        config_path=config_path,
        invocation={"entrypoint": "container"},
        backend_name="container",
        backend_kind="container",
        runtime_guard_mode="off",
        runtime_check_skipped=True,
    )


def main() -> None:
    config_path = _required_absolute_file("BLOOM_CONFIG_PATH")
    _initialize_runtime_context(config_path)
    _start_server(
        port=int(_required_env("PORT")),
        host=_required_env("HOST"),
        reload=False,
        background=False,
        ssl=False,
        cert=None,
        key=None,
    )


if __name__ == "__main__":
    main()
