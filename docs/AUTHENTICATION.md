# Bloom Authentication Setup

Bloom LIMS uses AWS Cognito for authentication, sharing a User Pool with lsmc-atlas
and daylily-ursa for consistent authentication across all three applications.

## Configuration

### YAML Configuration (Recommended)

Create `~/.config/bloom/bloom-config.yaml`:

```yaml
# Bloom LIMS Configuration
app_name: BLOOM LIMS
environment: development

# Authentication settings
auth:
  # Shared Cognito pool (same as lsmc-atlas and daylily-ursa)
  cognito_user_pool_id: us-west-2_pUqKyIM1N
  cognito_client_id: 1glmn93pg49bove54r48t48907
  cognito_client_secret: <your-client-secret>
  cognito_region: us-west-2
  cognito_domain: lsmc-shared-dev-puqkyim1n.auth.us-west-2.amazoncognito.com
  cognito_redirect_uri: http://localhost:8911/oauth_callback
  cognito_logout_redirect_uri: http://localhost:8911/
  cognito_scopes:
    - openid
    - email
    - profile

  # Email domain whitelist for authentication
  # Empty list blocks all domains. Use ["*"] to allow all domains.
  cognito_allowed_domains:
    - lsmc.bio
    - lsmc.com
    - lsmc.life
    - daylilyinformatics.com
    - dyly.bio
```

### Environment Variables (Legacy)

For backward compatibility, environment variables are still supported:

```bash
export COGNITO_USER_POOL_ID=us-west-2_pUqKyIM1N
export COGNITO_CLIENT_ID=1glmn93pg49bove54r48t48907
export COGNITO_CLIENT_SECRET=<your-client-secret>
export COGNITO_REGION=us-west-2
export COGNITO_DOMAIN=lsmc-shared-dev-puqkyim1n.auth.us-west-2.amazoncognito.com
export COGNITO_REDIRECT_URI=http://localhost:8911/oauth_callback
export COGNITO_WHITELIST_DOMAINS=lsmc.bio,lsmc.com,lsmc.life,daylilyinformatics.com,dyly.bio
```

## Running the Server

```bash
# Start in foreground (default)
bloom gui

# Start in background
bloom gui --background

# Stop background server
bloom gui stop

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
