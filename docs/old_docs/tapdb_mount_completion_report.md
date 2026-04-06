# TapDB Mount Completion Report

## Where TapDB Is Mounted

- Mounted inside Bloom FastAPI app at `/admin/tapdb` (configurable via `BLOOM_TAPDB_MOUNT_PATH`).
- Mounted through Bloom app factory (`bloom_lims.app.create_app`) so one Bloom server process serves both Bloom and TapDB-mounted paths.

## How Admin Gating Works

- Bloom wraps the TapDB sub-app with a Bloom-side ASGI guard.
- Guard reads Bloom session `user_data` before forwarding to TapDB:
  - unauthenticated browser -> `303` redirect to `/login`
  - unauthenticated JSON/XHR -> `401` JSON
  - non-admin browser -> `303` redirect to `/user_home?admin_required=1`
  - non-admin JSON/XHR -> `403` JSON
  - admin -> request forwarded to TapDB app

## How TapDB-Local Auth Is Bypassed

- Bloom wires an explicit mounted-user resolver into the embedded TapDB app.
- This bypasses TapDB-local auth flow for mounted mode without injecting `TAPDB_ADMIN_*`.
- Result: Bloom auth/session is the sole gate for mounted TapDB access.

## Remaining Caveats

- If mount is enabled and TapDB admin app fails to import/initialize, Bloom startup fails fast.
- Mounted mode assumes Bloom session middleware is active for mounted requests.
- Standalone TapDB behavior is unchanged when run outside Bloom.
