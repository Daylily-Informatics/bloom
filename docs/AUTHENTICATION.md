# Bloom Authentication Setup

Bloom LIMS uses AWS Cognito for authentication via `daylily-cognito` and `daycog`.
Bloom stores only the Cognito User Pool ID in YAML; app client/callback/logout/domain
are resolved from `~/.config/daycog/*.env` files.

## Configuration

### YAML Configuration (Recommended)

Create `~/.config/bloom/bloom-config.yaml`:

```yaml
# Bloom LIMS Configuration
app_name: BLOOM LIMS
environment: development

# Authentication settings
auth:
  # Required: pool ID only
  cognito_user_pool_id: us-east-1_JcKx3p6YP

  # Email domain whitelist for authentication
  # Empty list blocks all domains. Use ["*"] to allow all domains.
  cognito_allowed_domains:
    - lsmc.bio
    - lsmc.com
    - lsmc.life
    - daylilyinformatics.com
    - dyly.bio
```

### daycog Files (Preferred)

daycog writes region/app-scoped files (v0.1.22+):

- `~/.config/daycog/<pool>.<region>.env`
- `~/.config/daycog/<pool>.<region>.<app>.env`
- `~/.config/daycog/default.env`

Bloom resolves the file matching `auth.cognito_user_pool_id`, then prefers the pool-scoped
file (`<pool>.<region>.env`) because `daycog add-app/edit-app --set-default` keeps that file
as the active app context. If multiple app files exist and you need to force one, set
`BLOOM_COGNITO_APP_NAME`.

For daylily-cognito `0.1.22`, preferred lifecycle commands include:

```bash
# Base pool + app setup for Bloom (port 8912, callback defaults to /auth/callback)
daycog setup --name <pool-name> --port 8912 --attach-domain \
  --domain-prefix <domain-prefix> --profile <profile> --region us-east-1

# Optional: one-shot pool/app + Google IdP setup
daycog setup-with-google --name <pool-name> --client-name <app-name> \
  --profile <profile> --region us-east-1

# Multi-app management
daycog list-apps --pool-name <pool-name> --profile <profile> --region us-east-1
daycog add-app --pool-name <pool-name> --app-name bloom-gui \
  --callback-url http://localhost:8912/auth/callback --logout-url http://localhost:8912/ \
  --set-default --profile <profile> --region us-east-1
```

Bloom accepts both callback routes:
- `http://localhost:8912/auth/callback` (daycog default path)
- `http://localhost:8912/oauth_callback` (legacy path)

### Environment Variables (Legacy fallback)

For backward compatibility, environment variables are still supported:

```bash
export COGNITO_USER_POOL_ID=us-west-2_pUqKyIM1N
export COGNITO_CLIENT_ID=1glmn93pg49bove54r48t48907
export COGNITO_CLIENT_SECRET=<your-client-secret>
export COGNITO_REGION=us-west-2
export COGNITO_DOMAIN=lsmc-shared-dev-puqkyim1n.auth.us-west-2.amazoncognito.com
export COGNITO_REDIRECT_URI=http://localhost:8912/auth/callback
export COGNITO_WHITELIST_DOMAINS=lsmc.bio,lsmc.com,lsmc.life,daylilyinformatics.com,dyly.bio
```

## Running the Server

```bash
# Start in foreground (default)
bloom gui

# Start in background
bloom gui --background

# Stop background server
bloom stop

# View logs
bloom logs
```

## Shared Cognito Pool

All three applications (lsmc-atlas, bloom, daylily-ursa) share a single Cognito User Pool:

- **Pool ID:** `us-west-2_pUqKyIM1N`
- **Region:** `us-west-2`
- **Domain:** `lsmc-shared-dev-puqkyim1n.auth.us-west-2.amazoncognito.com`

This ensures users can authenticate with the same credentials across all applications.

## Email Domain Whitelist

Authentication is restricted to the following email domains:
- lsmc.bio
- lsmc.com
- lsmc.life
- daylilyinformatics.com
- dyly.bio

To change the allowed domains, update the `cognito_allowed_domains` list in the
YAML config file or the `COGNITO_WHITELIST_DOMAINS` environment variable.

## See Also

- [daylily-cognito](https://github.com/Daylily-Informatics/daylily-cognito) - Shared auth library
- [lsmc-atlas](https://github.com/lsmc-bio/lsmc-atlas) - Atlas configuration
- [daylily-ursa](https://github.com/Daylily-Informatics/daylily-ursa) - URSA configuration
