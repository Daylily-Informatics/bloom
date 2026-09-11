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


def _initialize_tapdb_context() -> None:
    from daylily_tapdb.cli.context import set_cli_context

    from bloom_lims.config import apply_runtime_environment, get_settings

    runtime_ctx = apply_runtime_environment(get_settings())
    tapdb_config_path = Path(runtime_ctx.config_path).resolve()
    if not tapdb_config_path.is_absolute() or not tapdb_config_path.is_file():
        raise RuntimeError(
            "Bloom requires an existing absolute TapDB runtime config: "
            f"{tapdb_config_path}"
        )
    set_cli_context(
        client_id=runtime_ctx.client_id,
        database_name=runtime_ctx.database_name,
        config_path=tapdb_config_path,
    )


def _verify_existing_tapdb() -> None:
    """Fail startup unless the released schema and required templates exist."""
    from daylily_tapdb import require_seeded_templates
    from daylily_tapdb.external_references import (
        OPAQUE_IDENTIFIER_TEMPLATE_CODE,
        TAPDB_OBJECT_TEMPLATE_CODE,
    )
    from daylily_tapdb.templates.loader import load_template_configs

    from bloom_lims.tapdb_adapter import BLOOMdb3

    template_root = Path(__file__).resolve().parents[1] / "config" / "tapdb_templates"
    definitions = load_template_configs(template_root)
    requirements = {
        (
            "/".join(
                str(item[key]).strip()
                for key in ("category", "type", "subtype", "version")
            )
            + "/",
            str(item["instance_prefix"]).strip().upper(),
        )
        for item in definitions
    }
    requirements.update(
        {
            (OPAQUE_IDENTIFIER_TEMPLATE_CODE, "XRF"),
            (TAPDB_OBJECT_TEMPLATE_CODE, "XRF"),
        }
    )
    if not requirements:
        raise RuntimeError("Bloom has no released TapDB template requirements")
    with BLOOMdb3(app_username="bloom-startup-verify-existing") as db:
        require_seeded_templates(
            db.session,
            sorted(requirements),
            domain_code=db.domain_code,
            app_name="Bloom",
        )


def main() -> None:
    config_path = _required_absolute_file("BLOOM_CONFIG_PATH")
    _initialize_runtime_context(config_path)
    _initialize_tapdb_context()
    _verify_existing_tapdb()
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
