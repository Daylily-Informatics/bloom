# Bloom Access Logging And AI-Agent Read Access Gap

Created: 2026-06-04T11:07:00Z

## Status

SUPERSEDED for local `jem-dev` source by commit `2e53e0c` and release tag
`6.0.2`. Bloom now has the local source pieces for Kahlo-issued read-only
AI-agent validation, broker-backed theme preferences, and common access logging.

Remaining acceptance moved to the Dayhoff final beta ledger:
`/Users/jmajor/projects/mega_dayhoff/dayhoff/docs/plans/20260606T080000Z_final_beta_release_consolidation_ledger.md`.
That acceptance requires the future `jemdev` deployment and must not use
production `day` services.

## Required Contract

- Validate Kahlo-issued AI-agent bearer tokens against an explicit Dayhoff-generated allowlist.
- Accept only read-only endpoint IDs approved for Bloom search/detail APIs.
- Record every endpoint access with request ID, correlation ID, route template, status, duration, client IP, auth mode, human user, service ID, AI-agent ID, authorizing human, token ID prefix/hash, scopes, and denial reason.
- Never log bearer tokens, cookies, raw presigned URLs, PHI-bearing query strings, object keys, or raw request/response bodies.

## Historical Gap

At creation time, source did not prove uniform all-endpoint structured access
logs with actor/IP/AI-agent provenance, and it did not validate Kahlo-issued
AI-agent tokens on Bloom search/read APIs. That is no longer the current local
`jem-dev` source state.

## Acceptance

- Focused tests prove allowed AI-agent tokens can read only approved Bloom search/detail endpoints.
- Mutating endpoints and non-allowlisted reads reject AI-agent tokens.
- Access-log tests prove actor/IP/request/token provenance is present and sensitive values are redacted.
