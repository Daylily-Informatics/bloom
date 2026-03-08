# Bloom Embedded TapDB Mount Execution Plan

## Objective

Embed TapDB Admin into Bloom's FastAPI process at `/admin/tapdb` with Bloom-only admin gating and no TapDB-local auth flow on mounted requests.

## Change Groups

1. Add a focused TapDB mount integration module in Bloom:
   - Resolve mount config from env.
   - Force mounted-mode TapDB auth disable flag before importing TapDB admin app.
   - Wrap TapDB sub-app with Bloom admin gate ASGI wrapper.
2. Wire mount into Bloom app factory startup:
   - Mount TapDB under `/admin/tapdb` by default.
   - Fail startup when mounted mode is enabled but TapDB app cannot be loaded.
3. Add tests for mounted route existence, admin-only behavior, and TapDB auth bypass behavior in mounted mode.
4. Update docs:
   - README and AUTH_INTEGRATION mounted-mode behavior and config.
   - Add completion report documenting mount path, gate, and auth boundary.

## Acceptance Checks

- Bloom starts as one FastAPI app and includes `/admin/tapdb`.
- Unauthenticated browser request to mounted path redirects to `/login`.
- Non-admin authenticated browser request redirects to `/user_home?admin_required=1`.
- API/XHR-style (`Accept: application/json`) denied requests receive JSON `401` or `403`.
- Admin request reaches TapDB sub-app.
- Admin request to `/admin/tapdb/login` is not forced through TapDB login in mounted mode.
- TapDB standalone usage remains unchanged.

## Breaking-Change Notes

- Bloom now defaults to mounting TapDB admin surface unless `BLOOM_TAPDB_MOUNT_ENABLED=0`.
- If mounted mode is enabled and TapDB admin app import/init fails, Bloom startup fails fast.

