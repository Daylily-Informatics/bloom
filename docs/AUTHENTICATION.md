# Bloom Authentication (Cognito + daycog)

Bloom authentication is Cognito-backed and should be managed through TapDB/`tapdb cognito ...` flows.

## Key Policy

- Bloom stores only the Cognito pool binding (`auth.cognito_user_pool_id`) in Bloom config.
- App/domain/client/callback details are resolved from daycog-managed env files.
- Use pool-scoped daycog env files to avoid cross-app collisions under one OS user.

Daycog file pattern:
- `~/.config/daycog/<pool>.<region>.env`
- `~/.config/daycog/<pool>.<region>.<app>.env`

## Recommended Runtime Context

```bash
export AWS_PROFILE=lsmc
export AWS_REGION=us-west-2
export AWS_DEFAULT_REGION=us-west-2
export TAPDB_ENV=dev
export TAPDB_DATABASE_NAME=bloom
```

## Configure Cognito (via TapDB)

```bash
# Show current TapDB context
python -m daylily_tapdb.cli info

# Bind/setup Cognito for active env/namespace.
# Bloom requires Cognito app client name: bloom
python -m daylily_tapdb.cli cognito setup dev --client-name bloom
# Equivalent Bloom wrapper:
bloom db auth-setup --port 8912 --region us-east-1
python -m daylily_tapdb.cli cognito status dev
```

## Callback URL Convention

For Bloom GUI, use:
- `https://localhost:8912/auth/callback`

Logout URL:
- `https://localhost:8912/`

## Bloom Config

Example `~/.config/bloom/bloom-config.yaml`:

```yaml
auth:
  cognito_user_pool_id: us-east-1_XXXXXXXXX

tapdb:
  env: dev
  database_name: bloom
```

## Start Bloom

```bash
source bloom_activate.sh
bloom gui
```
