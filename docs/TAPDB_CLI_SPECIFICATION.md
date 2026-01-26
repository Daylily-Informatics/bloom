# TAPDB Admin CLI Specification

## Overview

The `tapdb` CLI provides administrative commands for database management, environment setup, and AWS resource management. It is installed via a bash script that handles conda environment activation and tab completion.

## Installation & Activation

```bash
# Source the activation script (installs conda env if missing, enables tab completion)
source tapdb_activate.sh

# After sourcing, the CLI is available with tab completion
tapdb <TAB><TAB>  # Shows available commands
```

## Command Groups

### Database Management

| Command | Description |
|---------|-------------|
| `tapdb db init` | Create initial database and apply schema |
| `tapdb db migrate` | Run pending migrations |
| `tapdb db seed` | Seed database with initial templates |
| `tapdb db reset` | Drop and recreate database (destructive) |
| `tapdb db status` | Show migration status and connection info |

### User Management

| Command | Description |
|---------|-------------|
| `tapdb user create-superuser` | Create a superuser account |
| `tapdb user list` | List all users |
| `tapdb user deactivate <username>` | Deactivate a user |

### AWS Resources

| Command | Description |
|---------|-------------|
| `tapdb aws create` | Create all required AWS artifacts |
| `tapdb aws delete` | Delete all AWS artifacts (destructive) |
| `tapdb aws status` | Show AWS resource status |

### Template Management

| Command | Description |
|---------|-------------|
| `tapdb template load <path>` | Load templates from JSON file(s) |
| `tapdb template validate <path>` | Validate template file(s) without loading |
| `tapdb template export <output>` | Export templates to JSON |
| `tapdb template list` | List loaded templates |

### Utility

| Command | Description |
|---------|-------------|
| `tapdb version` | Show version information |
| `tapdb doctor` | Check environment and dependencies |
| `tapdb shell` | Open interactive Python shell with TAPDB loaded |

## Activation Script Behavior

The `tapdb_activate.sh` script:

1. Checks if `TAPDB` conda environment exists
2. Creates environment from `tapdb_env.yaml` if missing
3. Activates the `TAPDB` conda environment
4. Registers bash tab completion for `tapdb` command
5. Prints available commands dynamically extracted from CLI

```bash
#!/usr/bin/env bash
# tapdb_activate.sh

TAPDB_ENV_NAME="TAPDB"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check and create conda env if needed
if ! conda env list | grep -q "^${TAPDB_ENV_NAME} "; then
    echo "Creating ${TAPDB_ENV_NAME} conda environment..."
    conda env create -f "${SCRIPT_DIR}/tapdb_env.yaml"
fi

# Activate environment
conda activate "${TAPDB_ENV_NAME}"

# Enable tab completion
eval "$(_TAPDB_COMPLETE=bash_source tapdb)"

# Print available commands
echo "TAPDB CLI activated. Available commands:"
tapdb --help | grep -E "^  [a-z]" | head -20
```

## Implementation Notes

- CLI built with Click (for tab completion support)
- Colorized stdout/stderr logging (minimal, not overdone)
- All destructive commands require `--yes` flag or interactive confirmation
- Commands are POSIX-portable where possible
- Structured logging with timestamps and levels

## Configuration

CLI reads configuration from (in order of precedence):
1. Command-line flags
2. Environment variables (`TAPDB_*`)
3. Config file (`~/.tapdb/config.yaml` or `./tapdb.yaml`)

```yaml
# tapdb.yaml example
database:
  host: localhost
  port: 5432
  name: tapdb
  user: tapdb_admin

aws:
  region: us-west-2
  profile: default
```

---

*Part of the daylily-tapdb library specification*

