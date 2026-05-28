# Bloom Prefix Taxonomy, Wet-Lab Templates, Docs, And Ursa Runtime Ledger

## Summary

Apply Bloom's governed prefix taxonomy to active wet-lab templates, add missing
sequencing workflow templates, update README documentation, release Bloom, update
production Bloom on AWS `lsmcok1`, and update the Dayhoff-managed Ursa checkout
on the same EC2 host to `4.0.11`. Bloom and Ursa databases must remain as-is
except for Bloom's supported template refresh operation.

## Gate 0 Inventory

- Local dirty checkout avoided: `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom`
  is on `main`, ahead/behind `origin/main`, with an unrelated modified
  `AGENTS.md`.
- Release worktree: `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom-prefix-taxonomy-20260528`
- Release branch: `codex/bloom-prefix-taxonomy-20260528`
- Base: `origin/main` at `09d6d7d55742eefdd73fd9e8fbf17749349ccd75`
- Current max Bloom release tag at Gate 0: `5.0.36`
- `5.0.36` commit: `fdb533365867a1e34c544d16500e650178c631d9`
- Base reconciliation: merged tag `5.0.36` into the release branch with merge
  commit `f7c0b5f`, preserving both current `origin/main` ledger evidence and
  the latest released container/dependency changes.
- Ursa tag check: remote tag `4.0.11` exists at
  `61870ed0ca54f5c86ecf5bc3b2091ce331a7c146`.
- Current Bloom template pack has 163 templates and broad historical prefixes
  `BCN`, `BCT`, `BDT`, and `BGT` that must be reconciled with the new taxonomy.
- AWS instance: `i-09126000eb19643b0`, profile `lsmc`, region `us-west-2`.
- AWS Bloom running process: PID `481061`, uvicorn on port `8912`, health
  `https://localhost:8912/healthz` returned HTTP `200`.
- AWS Bloom running checkout: `/home/ubuntu/.cache/dayhoff/local/lsmcok1/repos/bloom`,
  branch `main`, tracking `origin/main`, clean by `git status --short`, current
  describe `5.0.35`.
- AWS Ursa running process: PID `391493`, `daylib_ursa.workset_api_cli` on port
  `8913`, health `https://localhost:8913/healthz` returned HTTP `200`.
- AWS Ursa running checkout:
  `/home/ubuntu/.cache/dayhoff/local/lsmcok1/repos/daylily-ursa`, detached HEAD,
  current describe `3.0.5`, with only untracked `.bak-*` files:
  `daylib_ursa/cli/server.py.bak-domain-code-20260523T124052Z`,
  `daylib_ursa/config.py.bak-allowed-hosts-20260523T123118Z`,
  `daylib_ursa/domain_access.py.bak-allowed-hosts-20260523T123118Z`,
  `daylib_ursa/ursa_config.py.bak-allowed-hosts-20260523T123118Z`, and
  `daylib_ursa/workset_api.py.bak-allowed-hosts-20260523T123118Z`.

## Ledger Rows

| ID | Agent | Requirement | Status | Gate | Evidence | Terminal Note |
|---|---:|---|---|---|---|---|
| LEDGER-001 | 1 | Create ledger with local Bloom, AWS Bloom, and AWS Ursa repo/runtime state | SUCCESS | Gate 0 | SSM command `207b8bae-2d3d-40ea-8f39-4819b439bc8b`; health checks HTTP `200` | Local Bloom, AWS Bloom, and AWS Ursa runtime state recorded. |
| BASE-001 | 1 | Reconcile Bloom release base with current max tag; stop on unmergeable tag/main divergence | SUCCESS | Gate 0 | Merge commit `f7c0b5f` | `origin/main` and `5.0.36` merged cleanly. |
| URSA-BASE-001 | 1 | Verify Ursa tag `4.0.11` exists and inspect AWS Ursa running root before changes | SUCCESS | Gate 0 | Remote tag `4.0.11` exists; AWS running checkout describes `3.0.5` | Proceed only after Bloom release; backup artifacts are recorded and not deleted. |
| PREFIX-001 | 2 | Add Bloom prefix taxonomy ownership/validation tests | SUCCESS | Gate 1 | `tests/test_bloom_prefix_taxonomy.py`; registry JSON validates | Tests cover family ownership, forbidden letters, generic reserves, concrete prefixes, sequencing-run prefixes, and README documentation. |
| EXISTING-001 | 3 | Update existing Bloom template prefixes for future minting | SUCCESS | Gate 2 | `config/tapdb_templates/bloom/templates.json`; 179 templates after update | Existing active templates now mint through the governed `BC*`, `BN*`, `BD*`, `BR*`, and `BG*` taxonomy; historical objects are untouched. |
| ADD-001 | 4 | Add missing Bloom content/container/data templates | SUCCESS | Gate 3 | Added saliva, sequencing-library plate/content/pool, index plate/reagent, flowcell/lane, operation/evidence, quant, transfer, and index-assignment templates | Missing wet-lab workflow objects are now template-backed. |
| DOC-001 | 5 | Update `README.md` with the Bloom prefix taxonomy and rules | SUCCESS | Gate 3 | `README.md` Prefix Taxonomy section | README records family meanings, invalid prefixes, historical-object rule, and governance/display-only semantics. |
| TEST-001 | 6 | Run Bloom template/API/docs-focused tests and build | SUCCESS | Gate 4 | `git diff --check`; JSON validation; focused pytest `240 passed, 23 skipped`; `python -m build` succeeded | Build emitted existing setuptools license deprecation warnings only. |
| RELEASE-001 | 7 | Commit Bloom changes, push, create annotated next version tag, and push tag | OPEN | Gate 5 |  |  |
| AWS-BLOOM-001 | 8 | Update AWS Bloom checkout/env to new Bloom tag | OPEN | Gate 6 |  |  |
| AWS-BLOOM-002 | 8 | Load Bloom templates with supported CLI and verify representative minted prefixes | OPEN | Gate 6 |  |  |
| AWS-BLOOM-003 | 8 | Restart only Bloom if required and verify `bloom.day.lsmc.bio` health | OPEN | Gate 6 |  |  |
| AWS-URSA-001 | 9 | Update AWS Dayhoff-managed Ursa checkout to `4.0.11` | OPEN | Gate 7 |  |  |
| AWS-URSA-002 | 9 | Restart only Ursa service GUI/runtime and verify health | OPEN | Gate 7 |  |  |
| FINAL-001 | 1 | Record commits, tags, tests, production evidence, restarts, and DB-no-change evidence | OPEN | Gate 8 |  |  |
