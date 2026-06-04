# Bloom Access Logging And AI-Agent Read Access Gap

Created: 2026-06-04T11:07:00Z

## Status

Bloom needs a follow-up implementation pass before Kahlo-issued AI-agent tokens can safely read Bloom search endpoints directly.

## Required Contract

- Validate Kahlo-issued AI-agent bearer tokens against an explicit Dayhoff-generated allowlist.
- Accept only read-only endpoint IDs approved for Bloom search/detail APIs.
- Record every endpoint access with request ID, correlation ID, route template, status, duration, client IP, auth mode, human user, service ID, AI-agent ID, authorizing human, token ID prefix/hash, scopes, and denial reason.
- Never log bearer tokens, cookies, raw presigned URLs, PHI-bearing query strings, object keys, or raw request/response bodies.

## Current Gap

Current source does not prove uniform all-endpoint structured access logs with actor/IP/AI-agent provenance, and it does not validate Kahlo-issued AI-agent tokens on Bloom search/read APIs.

## Acceptance

- Focused tests prove allowed AI-agent tokens can read only approved Bloom search/detail endpoints.
- Mutating endpoints and non-allowlisted reads reject AI-agent tokens.
- Access-log tests prove actor/IP/request/token provenance is present and sensitive values are redacted.
