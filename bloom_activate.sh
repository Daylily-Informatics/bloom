#!/usr/bin/env bash
# =============================================================================
# BLOOM LIMS - Environment Activation Script (TapDB runtime)
# =============================================================================

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Error: This script must be sourced, not executed."
    echo "Usage: source bloom_activate.sh"
    exit 1
fi

_bloom_script_path() {
    if [[ -n "${ZSH_VERSION:-}" ]]; then
        printf '%s\n' "${(%):-%x}"
    elif [[ -n "${BASH_SOURCE[0]:-}" ]]; then
        printf '%s\n' "${BASH_SOURCE[0]}"
    else
        printf '%s\n' "$0"
    fi
}

_BLOOM_SCRIPT_PATH="$(_bloom_script_path)"
BLOOM_ROOT="$(cd "$(dirname "${_BLOOM_SCRIPT_PATH}")" && pwd)"
unset -f _bloom_script_path
unset _BLOOM_SCRIPT_PATH

_GREEN='\033[0;32m'
_YELLOW='\033[1;33m'
_BLUE='\033[0;34m'
_CYAN='\033[0;36m'
_NC='\033[0m'
_BLOOM_PYTHON=""

echo -e "${_BLUE}Activating BLOOM LIMS environment...${_NC}"

if command -v conda &> /dev/null; then
    if [[ -n "${ZSH_VERSION:-}" ]]; then
        eval "$(conda shell.zsh hook)" 2>/dev/null || true
    elif [[ -n "${BASH_VERSION:-}" ]]; then
        eval "$(conda shell.bash hook)" 2>/dev/null || true
    else
        source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    fi

    if conda info --envs | grep -q "^BLOOM "; then
        echo -e "  ${_GREEN}✓${_NC} Activating conda environment: BLOOM"
        conda activate BLOOM
        if [[ -n "$CONDA_PREFIX" ]] && [[ -d "$CONDA_PREFIX/bin" ]]; then
            export PATH="$CONDA_PREFIX/bin:$PATH"
        fi
    else
        echo -e "  ${_YELLOW}⚠${_NC} Conda environment 'BLOOM' not found."
        if [[ -f "$BLOOM_ROOT/bloom_env.yaml" ]]; then
            echo -e "  ${_CYAN}→${_NC} Installing conda environment from bloom_env.yaml..."
            if conda env create -f "$BLOOM_ROOT/bloom_env.yaml"; then
                echo -e "  ${_GREEN}✓${_NC} Conda environment created successfully"
                conda activate BLOOM
                if [[ -n "$CONDA_PREFIX" ]] && [[ -d "$CONDA_PREFIX/bin" ]]; then
                    export PATH="$CONDA_PREFIX/bin:$PATH"
                fi
            else
                echo -e "  ${_YELLOW}⚠${_NC} Failed to create conda environment."
            fi
        else
            echo -e "  ${_YELLOW}⚠${_NC} bloom_env.yaml not found."
        fi
    fi
else
    echo -e "  ${_YELLOW}⚠${_NC} Conda not found."
    return 1
fi

if [[ "${CONDA_DEFAULT_ENV:-}" != "BLOOM" ]] || [[ -z "${CONDA_PREFIX:-}" ]] || [[ ! -x "${CONDA_PREFIX}/bin/python" ]]; then
    echo -e "  ${_YELLOW}⚠${_NC} BLOOM conda environment is required."
    echo -e "  ${_CYAN}→${_NC} Run 'conda env create -f bloom_env.yaml' if needed, then retry 'source bloom_activate.sh'."
    return 1
fi

_BLOOM_PYTHON="${CONDA_PREFIX}/bin/python"
_BLOOM_PYTHON_BIN="$(dirname "${_BLOOM_PYTHON}")"
export PATH="${_BLOOM_PYTHON_BIN}:$PATH"

if ! command -v bloom &> /dev/null || ! "${_BLOOM_PYTHON}" -m pip show bloom_lims &> /dev/null 2>&1; then
    echo -e "  ${_CYAN}→${_NC} Installing bloom CLI..."
    if ! "${_BLOOM_PYTHON}" -m pip install -e "$BLOOM_ROOT" -q; then
        echo -e "  ${_YELLOW}⚠${_NC} Failed to install bloom into the BLOOM conda environment."
        return 1
    fi
    echo -e "  ${_GREEN}✓${_NC} Installed 'bloom' CLI command"
else
    echo -e "  ${_GREEN}✓${_NC} 'bloom' CLI already installed"
fi

if [[ "$-" == *i* ]]; then
    if [[ -n "${ZSH_VERSION:-}" ]]; then
        if eval "$(_BLOOM_COMPLETE=zsh_source bloom 2>/dev/null)" 2>/dev/null; then
            echo -e "  ${_GREEN}✓${_NC} Enabled tab completion for 'bloom' (zsh)"
        fi
    elif [[ -n "${BASH_VERSION:-}" ]]; then
        if eval "$(_BLOOM_COMPLETE=bash_source bloom 2>/dev/null)" 2>/dev/null; then
            echo -e "  ${_GREEN}✓${_NC} Enabled tab completion for 'bloom' (bash)"
        fi
    fi
fi

# TapDB/AWS runtime defaults for BLOOM
export TAPDB_ENV="${TAPDB_ENV:-dev}"
export TAPDB_CLIENT_ID="${TAPDB_CLIENT_ID:-bloom}"
export TAPDB_DATABASE_NAME="${TAPDB_DATABASE_NAME:-bloom}"
export TAPDB_STRICT_NAMESPACE="${TAPDB_STRICT_NAMESPACE:-1}"
export BLOOM_TAPDB_LOCAL_PG_PORT="${BLOOM_TAPDB_LOCAL_PG_PORT:-5566}"
export TAPDB_DEV_PORT="${TAPDB_DEV_PORT:-$BLOOM_TAPDB_LOCAL_PG_PORT}"
export TAPDB_TEST_PORT="${TAPDB_TEST_PORT:-$BLOOM_TAPDB_LOCAL_PG_PORT}"
_BLOOM_DEFAULT_TAPDB_CONFIG_PATH="$BLOOM_ROOT/config/tapdb-config-${TAPDB_DATABASE_NAME}.yaml"
if [[ -z "${TAPDB_CONFIG_PATH:-}" ]]; then
    if [[ -f "$_BLOOM_DEFAULT_TAPDB_CONFIG_PATH" ]]; then
        export TAPDB_CONFIG_PATH="$_BLOOM_DEFAULT_TAPDB_CONFIG_PATH"
    fi
fi
export BLOOM_COGNITO_APP_NAME="${BLOOM_COGNITO_APP_NAME:-bloom}"
export AWS_PROFILE="${AWS_PROFILE:-lsmc}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

echo -e "  ${_GREEN}✓${_NC} TAPDB_ENV=${TAPDB_ENV}"
echo -e "  ${_GREEN}✓${_NC} TAPDB_CLIENT_ID=${TAPDB_CLIENT_ID}"
echo -e "  ${_GREEN}✓${_NC} TAPDB_DATABASE_NAME=${TAPDB_DATABASE_NAME}"
echo -e "  ${_GREEN}✓${_NC} TAPDB_STRICT_NAMESPACE=${TAPDB_STRICT_NAMESPACE}"
if [[ -n "${TAPDB_CONFIG_PATH:-}" ]]; then
    echo -e "  ${_GREEN}✓${_NC} TAPDB_CONFIG_PATH=${TAPDB_CONFIG_PATH}"
else
    echo -e "  ${_YELLOW}⚠${_NC} TAPDB_CONFIG_PATH is not set"
fi
echo -e "  ${_GREEN}✓${_NC} TAPDB_DEV_PORT=${TAPDB_DEV_PORT}"
echo -e "  ${_GREEN}✓${_NC} TAPDB_TEST_PORT=${TAPDB_TEST_PORT}"
echo -e "  ${_GREEN}✓${_NC} BLOOM_COGNITO_APP_NAME=${BLOOM_COGNITO_APP_NAME}"
echo -e "  ${_GREEN}✓${_NC} AWS_PROFILE=${AWS_PROFILE}"
echo -e "  ${_GREEN}✓${_NC} AWS_REGION=${AWS_REGION}"

# Validate daylily-tapdb version policy
"${_BLOOM_PYTHON}" - <<'PY'
import importlib.metadata

try:
    from packaging.version import Version
except Exception:
    print("  \033[1;33m⚠\033[0m packaging not installed; skipping daylily-tapdb version range check")
    raise SystemExit(0)

try:
    v = Version(importlib.metadata.version("daylily-tapdb"))
except Exception:
    print("  \033[1;33m⚠\033[0m daylily-tapdb not installed")
    raise SystemExit(0)

if not (Version("3.0.3") <= v < Version("4.0.0")):
    print(f"  \033[1;33m⚠\033[0m daylily-tapdb version {v} outside supported range [3.0.3, 4.0.0)")
else:
    print(f"  \033[0;32m✓\033[0m daylily-tapdb version {v}")
PY

export BLOOM_ROOT

deactivate_bloom() {
    unset BLOOM_ROOT
    unset TAPDB_ENV
    unset TAPDB_CLIENT_ID
    unset TAPDB_DATABASE_NAME
    unset TAPDB_STRICT_NAMESPACE
    unset TAPDB_CONFIG_PATH
    unset BLOOM_TAPDB_LOCAL_PG_PORT
    unset TAPDB_DEV_PORT
    unset TAPDB_TEST_PORT
    unset BLOOM_COGNITO_APP_NAME
    if [[ "$CONDA_DEFAULT_ENV" == "BLOOM" ]]; then
        conda deactivate 2>/dev/null
    fi
    echo "BLOOM LIMS environment deactivated."
    unset -f deactivate_bloom
}

echo ""
echo -e "${_CYAN}BLOOM LIMS environment activated!${_NC}"
echo ""
echo "Command groups:"
echo ""
echo -e "  ${_CYAN}bloom server${_NC}    start, stop, status, logs"
echo -e "  ${_CYAN}bloom db${_NC}        init, start, stop, status, migrate, seed, shell, reset"
echo -e "  ${_CYAN}bloom config${_NC}    path, init, show, validate, edit, reset, shell, doctor, status"
echo -e "  ${_CYAN}bloom info${_NC}      Show environment information"
echo -e "  ${_CYAN}bloom version${_NC}   Show CLI version"
echo ""
echo -e "  ${_GREEN}bloom --help${_NC}          Show all available commands"
echo -e "  ${_GREEN}deactivate_bloom${_NC}      Deactivate this environment"
echo ""
