from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler


def get_clean_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")


def setup_logging() -> None:
    # Configure root logger to capture logs from all libraries (uvicorn included).
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    os.makedirs("logs", exist_ok=True)
    log_filename = f"logs/bloomui_{get_clean_timestamp()}.log"

    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.INFO)

    f_handler = RotatingFileHandler(log_filename, maxBytes=10485760, backupCount=5)
    f_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d"
    )
    c_handler.setFormatter(formatter)
    f_handler.setFormatter(formatter)

    logger.addHandler(c_handler)
    logger.addHandler(f_handler)


def _init_runtime_context() -> None:
    """Apply AWS/TAPDB runtime context and validate tapdb version policy."""
    try:
        from bloom_lims.config import apply_runtime_environment, assert_tapdb_version, get_settings

        settings = get_settings()
        apply_runtime_environment(settings)
        assert_tapdb_version()
    except Exception as exc:
        logging.warning("Runtime context initialization warning: %s", exc)


setup_logging()
_init_runtime_context()


# Import after runtime context so any TapDB/AWS env defaults are applied first.
from bloom_lims.app import create_app  # noqa: E402


# FastAPI app used by uvicorn and by tests.
app = create_app()


# Back-compat re-exports for tests and legacy import paths.
from bloom_lims.gui.deps import require_auth  # noqa: E402
from bloom_lims.gui.routes.graph import _build_graph_elements_for_start  # noqa: E402
