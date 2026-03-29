# Bloom Release Tag Policy

Bloom's historical Git release tags use the legacy `v*` form, for example
`v0.11.12`.

This is a repository history convention, not a semantic difference in the
release itself. Downstream tooling that deploys or pins Bloom should use the
exact upstream tag that exists in the Bloom repo.

Current policy:

- Existing `v*` tags are legacy-format release tags and remain valid.
- Do not invent normalized bare-semver aliases in downstream deploy manifests
  unless those tags actually exist upstream.
- Deployment tooling should accept the exact upstream release tag format.

If Bloom adopts bare semver tags in a later release wave, that policy change
should be documented here and reflected in downstream pinning rules at the
same time.
