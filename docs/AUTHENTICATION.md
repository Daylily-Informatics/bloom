# Bloom Authentication (Cognito + YAML)

Bloom authentication is Cognito-backed and should be managed through TapDB/`tapdb cognito ...` flows.

## Key Policy

- Bloom stores the full Cognito runtime contract in `~/.config/bloom/bloom-config.yaml`.
- Service startup should not depend on `COGNITO_*` or daycog env files.
- Use HTTPS callback and logout URLs everywhere.

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

Example `~/.config/bloom/config.yaml`:

```yaml
auth:
  cognito_user_pool_id: us-east-1_XXXXXXXXX
  cognito_client_id: 1abc2defgh3ijklmno4pqrst
  cognito_region: us-east-1
  cognito_domain: bloom-lims-yourorg.auth.us-east-1.amazoncognito.com
  cognito_redirect_uri: https://localhost:8912/auth/callback
  cognito_logout_redirect_uri: https://localhost:8912/

tapdb:
  env: dev
  database_name: bloom
```

## Start Bloom

```bash
source bloom_activate.sh
bloom gui
```
