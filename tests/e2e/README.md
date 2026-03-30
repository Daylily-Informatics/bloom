## Bloom Playwright Auth E2E

Run:

```bash
E2E_USER_PASSWORD=... pytest tests/e2e/test_auth_e2e.py -m e2e
```

Defaults:
- `E2E_USER_EMAIL=johnm+test@lsmc.com`
- `BLOOM_BASE_URL=https://localhost:18912`

These tests cover only the Bloom GUI login/logout browser flow.
