#!/usr/bin/env bash
set -euo pipefail

source bloom_activate.sh

# TapDB-managed reset + setup + seed for local development.
bloom db stop || true
bloom db init --force
bloom db seed
pytest
