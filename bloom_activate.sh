#!/usr/bin/env bash
# =============================================================================
# BLOOM LIMS - Environment Activation Script
# =============================================================================
#
# This script sets up the development environment for BLOOM LIMS.
# It must be SOURCED, not executed:
#
#   source bloom_activate.sh      # from the repo directory
#   source ./bloom_activate.sh    # explicit path
#   . bloom_activate.sh           # shorthand
#
# What it does:
#   1. Activates the BLOOM conda environment (creates if missing)
#   2. Installs CLI in editable mode if needed
#   3. Enables tab completion for 'bloom' command
#   4. Sets DATABASE_URL if PostgreSQL data exists
#
# To deactivate, run: deactivate_bloom
# =============================================================================

# Detect if script is being sourced or executed
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Error: This script must be sourced, not executed."
    echo ""
    echo "Usage:"
    echo "  source bloom_activate.sh"
    echo "  source ./bloom_activate.sh"
    echo "  . bloom_activate.sh"
    exit 1
fi

# Get the directory where this script lives
BLOOM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
_GREEN='\033[0;32m'
_YELLOW='\033[1;33m'
_BLUE='\033[0;34m'
_CYAN='\033[0;36m'
_NC='\033[0m'

echo -e "${_BLUE}Activating BLOOM LIMS environment...${_NC}"

# 1. Activate conda environment (install if needed)
if command -v conda &> /dev/null; then
    # Ensure conda is properly initialized for this shell
    # Use eval with shell hook (works reliably in VS Code terminals)
    if [[ -n "$ZSH_VERSION" ]]; then
        eval "$(conda shell.zsh hook)" 2>/dev/null || true
    elif [[ -n "$BASH_VERSION" ]]; then
        eval "$(conda shell.bash hook)" 2>/dev/null || true
    else
        source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    fi

    if conda info --envs | grep -q "^BLOOM "; then
        echo -e "  ${_GREEN}✓${_NC} Activating conda environment: BLOOM"
        conda activate BLOOM
        # Workaround: VS Code terminals may not update PATH correctly after conda activate
        # Explicitly prepend the conda env bin directory to PATH
        if [[ -n "$CONDA_PREFIX" ]] && [[ ":$PATH:" != *":$CONDA_PREFIX/bin:"* ]]; then
            export PATH="$CONDA_PREFIX/bin:$PATH"
        fi
    else
        echo -e "  ${_YELLOW}⚠${_NC} Conda environment 'BLOOM' not found."

        # Check if bloom_env.yaml exists
        if [[ -f "$BLOOM_ROOT/bloom_env.yaml" ]]; then
            echo -e "  ${_CYAN}→${_NC} Installing conda environment from bloom_env.yaml..."
            echo ""

            if conda env create -f "$BLOOM_ROOT/bloom_env.yaml"; then
                echo ""
                echo -e "  ${_GREEN}✓${_NC} Conda environment created successfully"
                echo -e "  ${_GREEN}✓${_NC} Activating conda environment: BLOOM"
                conda activate BLOOM
            else
                echo ""
                echo -e "  ${_YELLOW}⚠${_NC} Failed to create conda environment. Check bloom_env.yaml"
            fi
        else
            echo -e "  ${_YELLOW}⚠${_NC} bloom_env.yaml not found. Cannot auto-install environment."
        fi
    fi
else
    echo -e "  ${_YELLOW}⚠${_NC} Conda not found. Make sure Python dependencies are installed."
fi

# 2. Install CLI in editable mode if not already installed
if ! command -v bloom &> /dev/null || ! pip show bloom_lims &> /dev/null 2>&1; then
    echo -e "  ${_CYAN}→${_NC} Installing bloom CLI..."
    pip install -e "$BLOOM_ROOT" -q
    echo -e "  ${_GREEN}✓${_NC} Installed 'bloom' CLI command"
else
    echo -e "  ${_GREEN}✓${_NC} 'bloom' CLI already installed"
fi

# 3. Enable tab completion
if [[ -n "$ZSH_VERSION" ]]; then
    # For zsh
    eval "$(_BLOOM_COMPLETE=zsh_source bloom 2>/dev/null)" 2>/dev/null
    echo -e "  ${_GREEN}✓${_NC} Enabled tab completion for 'bloom' (zsh)"
elif [[ -n "$BASH_VERSION" ]]; then
    # For bash
    eval "$(_BLOOM_COMPLETE=bash_source bloom 2>/dev/null)" 2>/dev/null
    echo -e "  ${_GREEN}✓${_NC} Enabled tab completion for 'bloom' (bash)"
fi

# 4. Set DATABASE_URL if PostgreSQL data directory exists
PGDATA="$BLOOM_ROOT/bloom_lims/database"
PGPORT="${PGPORT:-5445}"
PGHOST="${PGHOST:-localhost}"
PGDATABASE="${PGDATABASE:-bloom}"
PGUSER="${PGUSER:-bloom}"

if [[ -d "$PGDATA" ]]; then
    export DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE}"
    echo -e "  ${_GREEN}✓${_NC} Set DATABASE_URL"
    
    # Check if PostgreSQL is running
    if pg_ctl -D "$PGDATA" status &>/dev/null; then
        echo -e "  ${_GREEN}✓${_NC} PostgreSQL is running on port $PGPORT"
    else
        echo -e "  ${_YELLOW}⚠${_NC} PostgreSQL is not running. Start with: bloom db start"
    fi
else
    echo -e "  ${_YELLOW}⚠${_NC} PostgreSQL not initialized. Run: source bloom_lims/env/install_postgres.sh"
fi

# 5. Export BLOOM_ROOT for convenience
export BLOOM_ROOT

# 6. Create deactivate function
deactivate_bloom() {
    # Unset variables
    unset BLOOM_ROOT
    unset DATABASE_URL

    # Deactivate conda if it was activated
    if [[ "$CONDA_DEFAULT_ENV" == "BLOOM" ]]; then
        conda deactivate 2>/dev/null
    fi

    echo "BLOOM LIMS environment deactivated."
    unset -f deactivate_bloom
}

echo ""
echo -e "${_CYAN}BLOOM LIMS environment activated!${_NC}"
echo ""

# Display command groups
echo "Command groups:"
echo ""
echo -e "  ${_CYAN}bloom db${_NC}        start, stop, status, migrate, seed, shell, reset"
echo -e "  ${_CYAN}bloom gui${_NC}       Start the BLOOM web UI"
echo -e "  ${_CYAN}bloom config${_NC}    Show or edit configuration"
echo -e "  ${_CYAN}bloom info${_NC}      Show environment information"
echo -e "  ${_CYAN}bloom status${_NC}    Check service status"
echo -e "  ${_CYAN}bloom doctor${_NC}    Verify environment health"
echo -e "  ${_CYAN}bloom shell${_NC}     Interactive Python shell"
echo -e "  ${_CYAN}bloom logs${_NC}      View service logs"
echo ""
echo -e "  ${_GREEN}bloom --help${_NC}          Show all available commands"
echo -e "  ${_GREEN}deactivate_bloom${_NC}      Deactivate this environment"
echo ""

