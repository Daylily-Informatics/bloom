#!/usr/bin/env bash
set -euo pipefail

source ./activate

# TapDB-managed reset + setup + seed for local development.
bloom server stop || true
bloom db init --force
bloom db seed
pytest
