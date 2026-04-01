# Bloom Authentication (Cognito + YAML)

Bloom authentication is Cognito-backed and should be managed through `daycog` for shared Cognito lifecycle plus `tapdb` for namespace-bound config.

## Key Policy

- Bloom stores the full Cognito runtime contract in `~/.config/bloom/config.yaml`.
- Service startup should not depend on `COGNITO_*` or daycog env files.
- Use HTTPS callback and logout URLs everywhere.

## Recommended Runtime Context

```bash
export AWS_PROFILE=lsmc
export AWS_REGION=us-west-2
export AWS_DEFAULT_REGION=us-west-2
```

## Configure Cognito (via TapDB)

```bash
# Show current TapDB context
python -m daylily_tapdb.cli --config ~/.config/tapdb/bloom/bloom/tapdb-config.yaml --env dev info

# Initialize the TapDB namespace config for Bloom
python -m daylily_tapdb.cli --config ~/.config/tapdb/bloom/bloom/tapdb-config.yaml --env dev config init \
  --env dev --db-port dev=5566 --ui-port dev=8912

# Update shared Cognito app/pool state through daycog
daycog config create-all --pool-name daylily-ursa-users --region us-west-2 --default-client atlas

# Bind the Bloom namespace to the shared Cognito app client
python -m daylily_tapdb.cli --config ~/.config/tapdb/bloom/bloom/tapdb-config.yaml --env dev config update \
  --env dev \
  --cognito-user-pool-id us-west-2_5r8gIqV5P \
  --cognito-app-client-id 6j2pa8nr9ve19aeuhnb1ocpl2r \
  --cognito-client-name bloom \
  --cognito-region us-west-2 \
  --cognito-domain daylily-ursa-5r8giqv5p.auth.us-west-2.amazoncognito.com \
  --cognito-callback-url https://localhost:8912/auth/callback \
  --cognito-logout-url https://localhost:8912/
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
  client_id: bloom
  database_name: bloom
  config_path: ~/.config/tapdb/bloom/bloom/tapdb-config.yaml
```

## Start Bloom

```bash
source ./activate <deploy-name>
bloom server start
```
