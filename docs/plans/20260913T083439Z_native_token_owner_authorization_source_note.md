# Bloom native token-owner authorization consumer

Base: Bloom 10.0.5, commit `240c67d0711ff2ad0e0d899a0df19d3ad7418be5`. This extends the existing truthful 403 handling without changing the original token, owner, groups, roles, identity issuer or ordinary object permissions.

Changed source:

- `bloom_lims/auth/services/user_api_tokens.py`: after the existing token validation, require its persisted owner identifier to be an exact positive BIGINT and call public `daylily_tapdb.user_authorization.resolve_user_authorization`. Require an active identity and explicit canonical role; deny empty scope-constrained permissions. There is no email lookup, guessed owner, replacement principal or private SQL query.
- `bloom_lims/auth/rbac.py`: constrain authority by intersecting the owner's effective permissions with the existing scope's permission set. The prior rank filter removed ADMIN entirely for internal_ro; this now yields READ_ONLY authority without raising the scope ceiling.
- `bloom_lims/api/v1/dependencies.py`: use the resulting nonempty authorized role directly, removing the display-only READ_ONLY default that could misrepresent empty permissions. APIUser distinguishes absent permissions (`None`: derive from canonical role) from an explicit empty set (deny all), intersects supplied permissions with role authority, and makes has_permission/is_admin/can_write use that effective set. Existing Cognito-derived permission sets remain equivalent; existing 403 translation remains.

Native dependency source and production sequence: `/Users/jmajor/projects/mega_dayhoff/.codex-worktrees/ursa-bloom-identity-tapdb-20260913/docs/plans/20260913T083439Z_runtime_identity_authorization_source_note.md`.

The current `pyproject.toml`/`uv.lock` still reference TapDB 10.1.3. Lead must publish the new TapDB capability first, then update the exact Bloom dependency and regenerate the frozen lock from the real published artifact. This consumer must not be built/deployed with 10.1.3. Native schema migration and the reviewed exact `bloom_runtime_10`→UID `3364` / EUID `M-SYS-9SX2` authorization grant are separate required production steps. The original token remains internal_ro; no owner decision is missing.

Only source reads/edits/diff review were performed. No tests, imports/executable checks, publication, builds, deployments, DB/runtime/credential changes or delegation. Live read acceptance is not claimed.
