# Bloom and Dewey

This note describes the current Bloom-to-Dewey relationship.

## Current State

Bloom is not the artifact registry. Dewey owns artifact identity, artifact sets,
share references, and artifact-resolution metadata.

Bloom can act as an artifact producer for wet-lab run outputs. When Dewey
integration is enabled, Bloom registers run artifacts with the Dewey service at
run creation time.

## Bloom Responsibilities

- produce run-linked artifacts from wet-lab execution
- send Dewey-authenticated registration requests when enabled
- keep Bloom-side lineage and Atlas context separate from artifact-registry authority

## Dewey Responsibilities

- issue and resolve artifact EUIDs
- store canonical artifact metadata
- manage artifact-set membership
- maintain external object links for artifact records

## Required Bloom Config

When Dewey registration is enabled in Bloom, the following settings must be
present:

- `BLOOM_DEWEY__ENABLED=true`
- `BLOOM_DEWEY__BASE_URL=https://dewey.example.org`
- `BLOOM_DEWEY__TOKEN=<dewey-bearer-token>`

Optional settings:

- `BLOOM_DEWEY__TIMEOUT_SECONDS`
- `BLOOM_DEWEY__VERIFY_SSL`

## Authoritative Docs

- Bloom overview: [../../README.md](../../README.md)
- Bloom docs index: [../../docs/README.md](../../docs/README.md)
- Dewey repo overview: [../../../dewey/README.md](../../../dewey/README.md)
