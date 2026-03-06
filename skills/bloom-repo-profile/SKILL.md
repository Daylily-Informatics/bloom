---
name: bloom-repo-profile
description: Repository-specific execution profile for the Daylily BLOOM LIMS codebase. Use when working in this repo on API endpoints, CLI behavior, TapDB database lifecycle, Atlas integration flows, GUI/server startup paths, or BLOOM test/debug workflows that require project-specific commands, file locations, and architecture constraints.
---

# Bloom Repo Profile

## Objective

Execute changes in this repository quickly while honoring BLOOM-specific
environment rules, architecture constraints, and validation flow.

## Operating Rules

1. Start every terminal command with `source bloom_activate.sh`.
2. Use the `BLOOM` conda environment and existing `bloom` CLI workflows.
3. Preserve architecture guidance in `ARCHITECTURE_GUIDANCE.md`:
   do not introduce workflow engines or routing orchestration logic.
4. Prefer targeted tests before full-suite runs.

## Execution Workflow

1. Confirm local runtime state when needed:
   - `source bloom_activate.sh`
   - `bloom info`
   - `bloom status`
2. Locate the implementation area from the task type:
   - API routes/schemas: `bloom_lims/api`, `bloom_lims/schemas`
   - CLI/runtime bootstrap: `bloom_lims/cli`, `bloom_activate.sh`
   - Core/domain behavior: `bloom_lims/core`, `bloom_lims/domain`
   - Auth/security/token flows: `bloom_lims/auth`, `bloom_lims/security`
   - GUI/static/templates: `bloom_lims/gui`, `templates`, `static`
3. Implement minimal, style-consistent changes.
4. Run the smallest relevant test slice first, then expand only as needed.
5. Summarize what changed, what was verified, and what remains unverified.

## Validation Guidance

- Single test file:
  - `source bloom_activate.sh && pytest tests/test_<target>.py`
- Focused test pattern:
  - `source bloom_activate.sh && pytest -k "<keyword>"`
- Full test pass:
  - `source bloom_activate.sh && pytest`
- DB/service checks when behavior depends on runtime:
  - `source bloom_activate.sh && bloom db status`
  - `source bloom_activate.sh && bloom db init` (only when initialization is required)

## References

- Load `references/repo-map.md` for quick command and file navigation.
- Load `ATLAS_BLOOM_API_GUIDANCE.md` for Atlas integration behavior and API recipes.
- Load `README.md` sections 14-16 for deployment/startup/testing commands.
