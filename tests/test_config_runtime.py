"""Focused regression tests for Bloom runtime configuration."""

from __future__ import annotations

import tempfile
from pathlib import Path

from bloom_lims.config import StorageSettings


def test_storage_temp_dir_uses_system_tempdir():
    assert StorageSettings().temp_dir == str(Path(tempfile.gettempdir()) / "bloom")
