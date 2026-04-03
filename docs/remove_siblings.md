# Multi-Agent Rollout: Remove Sibling Repo Installs From Active-Service Activation

## Summary

- Remove sibling-repo rebinding from activation flows across the active service repo set: `bloom`, `lsmc-atlas`, `daylily-ursa`, `dewey`, and `zebra_day`.
- Keep self-install behavior in `activate` where it exists today so each repo can still put its own CLI on `PATH`.
- Standardize the policy: activation uses packaged dependencies only; it never installs `../daylily-tapdb`, `../daylily-cognito`, `../cli-core-yo`, or `../lims_repos/*`.
- Make old sibling-rebinding env vars a hard error, not a silent fallback.
- Update Dayhoff service metadata so it no longer advertises sibling bootstrap behavior for the active repos.
- Prerequisite: fix packaged dependency coherence first, especially `zebra_day`, because removing sibling installs will expose current version mismatches immediately.

## Agent Topology

1. `Agent 0 — Coordinator`
   Owns sequencing, policy consistency, merge order, and final verification. No repo code changes.

2. `Agent 1 — zebra_day + Dependency Alignment`
   Owns `/Users/jmajor/projects/daylily/zebra_day`.
   Responsibilities:
   - Remove unconditional sibling installs from `activate`.
   - Keep only zebra_day self-install.
   - Update packaged dependency pins so the repo is solvable without sibling rebinding.
   - Release a new packaged version before downstream repos rely on it.
   Reason: `zebra_day==3.5.0` still pins `daylily-tapdb==3.2.0`, which currently breaks a clean packaged Bloom env.

3. `Agent 2 — Bloom`
   Owns `/Users/jmajor/projects/daylily/bloom`.
   Responsibilities:
   - Remove sibling path resolution and sibling install logic from `activate`.
   - Remove the stale Dayhoff-artifact rebinding escape hatch.
   - Keep Bloom self-install.
   - Replace sibling fallback with packaged-dependency validation and hard failure on legacy `USE_LOCAL_*`.

4. `Agent 3 — Atlas`
   Owns `/Users/jmajor/projects/lsmc/lsmc-atlas`.
   Responsibilities:
   - Remove `USE_LOCAL_DAYLILY_TAPDB`, `USE_LOCAL_DAYLILY_COGNITO`, and `USE_LOCAL_CLI_CORE_YO` rebinding from `activate`.
   - Keep Atlas self-install.
   - Add explicit packaged-dependency validation and hard failure on legacy env vars.

5. `Agent 4 — Ursa`
   Owns `/Users/jmajor/projects/daylily/daylily-ursa`.
   Responsibilities:
   - Remove sibling repo resolution/install paths from `activate`.
   - Keep Ursa self-install.
   - Convert `USE_LOCAL_*` sibling-rebinding flow into hard failure with a clear message.

6. `Agent 5 — Dewey`
   Owns `/Users/jmajor/projects/daylily/dewey`.
   Responsibilities:
   - Remove sibling repo resolution/install paths from `activate`.
   - Keep Dewey self-install.
   - Convert `USE_LOCAL_*` sibling-rebinding flow into hard failure with a clear message.

7. `Agent 6 — Kahlo Audit`
   Owns `/Users/jmajor/projects/lsmc/kahlo`.
   Responsibilities:
   - Confirm Kahlo has no sibling install logic beyond self-install.
   - Make no code change unless hidden sibling rebinding is found elsewhere in its operator/bootstrap flow.

8. `Agent 7 — Dayhoff Metadata`
   Owns `/Users/jmajor/projects/dayhoff`.
   Responsibilities:
   - Update active-service metadata so it no longer suggests sibling bootstrap behavior.
   - Remove or neutralize `bootstrap_repos` for `atlas`, `bloom`, `ursa`, `dewey`, and `kahlo` in service catalog/config.
   - Keep service-directory ownership and repo catalog intact.

## Key Changes

### Activation Contract
- `activate` must not inspect or install sibling repos from:
  - `../daylily-tapdb`
  - `../daylily-cognito`
  - `../cli-core-yo`
  - `../lims_repos/*`
- `activate` may continue to install the current repo editable so the repo’s own CLI works.
- Legacy sibling-rebinding env vars become unsupported operator inputs:
  - `USE_LOCAL_DAYLILY_TAPDB`
  - `USE_LOCAL_DAYLILY_COGNITO`
  - `USE_LOCAL_CLI_CORE_YO`
- New default when any of those vars are set: hard fail activation with a clear message that sibling rebinding is no longer supported from `activate` and packaged dependencies must be installed instead.

### Packaged Dependency Validation
- After env activation and self-install, each repo validates required packaged deps by import or distribution lookup.
- Missing packaged deps must fail clearly and name the package, not offer a sibling checkout fallback.
- `zebra_day` must be released first with compatible packaged pins so downstream repos can activate cleanly without sibling installs.

### Dayhoff Metadata
- Remove/update active-service `bootstrap_repos` metadata so it matches the new packaged-deps-only activation policy.
- Do not change Dayhoff auth logic; this is metadata/policy cleanup only.

## Execution Waves

### Wave 1 — Dependency Coherence
- Agent 1 updates `zebra_day` so its published package no longer pins stale shared-lib versions.
- Agent 0 verifies that packaged active-service envs can resolve current shared versions without local sibling repos.

### Wave 2 — Parallel Activation Cleanup
- Agents 2 through 5 remove sibling-install logic from `bloom`, `atlas`, `ursa`, and `dewey` in parallel.
- Agent 6 audits `kahlo`; only edits if hidden sibling rebinding exists.
- Agent 7 updates Dayhoff service metadata in parallel.

### Wave 3 — Verification and Convergence
- Agent 0 verifies all active repos now have the same activation policy:
  - self-install allowed
  - sibling installs removed
  - legacy `USE_LOCAL_*` values hard fail
  - packaged deps validated explicitly
- Only after that, cut repo-specific releases/tags where shipped activation behavior changed.

## Test Plan

- For each changed service repo:
  - Fresh shell `source ./activate <deploy-name>` succeeds without any sibling checkout present.
  - The repo’s own CLI is on `PATH`.
  - No `pip install -e ../...` or sibling path probing occurs during activation.
  - Setting any legacy `USE_LOCAL_*` var causes activation to fail with the new explicit error.
  - Required packaged deps import successfully from the activated env.
- Repo-specific smoke:
  - Bloom: existing GUI/auth callback test slice still passes under packaged deps.
  - Atlas: existing Cognito/auth test slice still passes.
  - Ursa: existing deployment/auth smoke still passes.
  - Dewey: existing UI session auth slice still passes.
  - zebra_day: activation and packaged import smoke pass without sibling repos.
- Dayhoff:
  - Metadata tests or config assertions confirm active services no longer declare sibling bootstrap repos.

## Assumptions and Defaults

- Keep self-editable install behavior in `activate`; only sibling installs are removed.
- Legacy sibling-rebinding env vars are removed as supported behavior and become hard errors.
- `kahlo` is audit-only unless new sibling-rebinding logic is discovered.
- `daylily-tapdb` and `daylily-cognito` are not changed for this rollout beyond audit; they do not install sibling repos today.
- `zebra_day` dependency alignment is a required prerequisite, not optional cleanup, because current packaged pins still hide behind sibling rebinding.
