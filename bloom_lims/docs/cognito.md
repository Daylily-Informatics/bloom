# AWS Cognito Authentication

Bloom now uses [AWS Cognito](https://aws.amazon.com/cognito/) for single sign-on via the hosted UI. This replaces the previous Supabase integration and drives all login and logout flows in the application.

## Required environment variables

Set the following values in your `.env` file (or deployment environment):

```bash
# Cognito Hosted UI + User Pool
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_CLIENT_ID=your_app_client_id
COGNITO_DOMAIN=your-custom-domain.auth.us-east-1.amazoncognito.com

# Redirects
COGNITO_REDIRECT_URI=http://127.0.0.1:8000/
COGNITO_LOGOUT_REDIRECT_URI=http://127.0.0.1:8000/

# Optional
COGNITO_SCOPES="openid email profile"
COGNITO_WHITELIST_DOMAINS=daylilyinformatics.com,rcrf.org   # "all" allows every domain
```

> Ensure the `COGNITO_REDIRECT_URI` matches the callback URL configured on your app client. Bloom uses the implicit flow and expects `id_token`/`access_token` fragments returned to that URL.

## Cognito hosted UI configuration

1. **Create a User Pool** in the AWS console.
2. **Create an App Client** with the following settings:
   - Enable the hosted UI and the **Implicit grant** with `id_token` and `access_token`.
   - Allowed callback URL(s): your `COGNITO_REDIRECT_URI`.
   - Allowed sign-out URL(s): your `COGNITO_LOGOUT_REDIRECT_URI`.
   - Scopes: include `email` and `openid` so Bloom can read the user's address.
3. **Choose identity providers** (e.g., Google) and connect them to the User Pool.
4. **Assign a domain** (e.g., `your-custom-domain.auth.us-east-1.amazoncognito.com`) and set it as `COGNITO_DOMAIN`.

## How Bloom uses Cognito

* The login page redirects users to the Cognito hosted UI using the configured domain, client ID, scopes, and redirect URI.
* After authentication Cognito returns `id_token` and `access_token` fragments to `COGNITO_REDIRECT_URI`. Bloom forwards these tokens to `/oauth_callback`, validates them against the Cognito JWKS, and stores the session.
* Optional domain whitelisting is controlled via `COGNITO_WHITELIST_DOMAINS` (comma-separated). Setting it to `all` disables filtering.
* Logout clears the Bloom session and redirects to the Cognito hosted logout page using `COGNITO_LOGOUT_REDIRECT_URI`.

## Local development tips

* Use `http://127.0.0.1:8000/` or `http://localhost:8000/` for both redirect URIs.
* If you test from another device, add that IP/host to the Cognito callback and logout URL lists.
* Keep `COGNITO_SCOPES` including `email` so Bloom can enforce domain restrictions and display user information.
