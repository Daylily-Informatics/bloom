# BLOOM Repo Map

## Table of Contents

- Quick start commands
- Key directories
- High-value docs
- Test focus map

## Quick start commands

```bash
source bloom_activate.sh
bloom info
bloom status
bloom db status
pytest -q
```

## Key directories

- `bloom_lims/api/`: FastAPI route layers, request handling, API integrations.
- `bloom_lims/schemas/`: Pydantic schema definitions and contracts.
- `bloom_lims/core/`: Core services, business rules, and orchestration helpers.
- `bloom_lims/domain/`: Domain-level models and logic.
- `bloom_lims/auth/`: AuthN/AuthZ, token and identity integration.
- `bloom_lims/security/`: Security middleware, policies, and helpers.
- `bloom_lims/cli/`: `bloom` command groups (`db`, `gui`, `status`, `doctor`, etc.).
- `bloom_lims/gui/`, `templates/`, `static/`: UI endpoints/assets/templates.
- `tests/`: Pytest suites covering API, auth, Atlas bridge, GUI, and CLI.
- `dags/`: DAG-related definitions and test assets.

## High-value docs

- `AGENTS.md`: Mandatory terminal activation rule (`source bloom_activate.sh`).
- `README.md`: System architecture, install, startup, and testing sections.
- `ARCHITECTURE_GUIDANCE.md`: Queue-first architecture constraint.
- `ATLAS_BLOOM_API_GUIDANCE.md`: Atlas integration endpoints and payload rules.
- `pyproject.toml`: Project metadata, pytest config, coverage options.

## Test focus map

- API behavior and contracts:
  - `tests/test_api_v1.py`
  - `tests/test_api_actions_execute.py`
  - `tests/test_api_atlas_bridge.py`
- Security and auth:
  - `tests/test_api_auth_rbac.py`
  - `tests/test_https_enforcement.py`
  - `tests/test_tool_api_users.py`
- UI and route coverage:
  - `tests/test_gui_endpoints.py`
  - `tests/test_route_coverage_gaps_api.py`
  - `tests/test_route_coverage_gaps_gui.py`
- CLI/runtime checks:
  - `tests/test_cli.py`
  - `tests/test_route_smoke_matrix.py`
