#!/usr/bin/env bash
set -euo pipefail

DEPLOY_NAME="${1:-${BLOOM_DEPLOYMENT_CODE:-}}"
if [[ -z "${DEPLOY_NAME}" ]]; then
  echo "Usage: $0 <deploy-name>" >&2
  exit 1
fi

source ./activate "${DEPLOY_NAME}"

# TapDB-managed reset + setup + seed for local development.
bloom server stop || true
bloom db build --target local --force
bloom db seed
pytest
