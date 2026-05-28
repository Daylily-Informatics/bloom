# Bloom Sequencing Run Prefix Templates Ledger

## Summary

Update Bloom sequencing-run templates so the semantic template codes remain under
`data/sequencing_run/*/1.0`, while new instances mint platform-specific Bloom
run EUID prefixes:

| Platform | Semantic template code | Instance prefix |
|---|---|---|
| ILMN / Illumina | `data/sequencing_run/illumina/1.0` | `BRM` |
| ONT | `data/sequencing_run/ont/1.0` | `BRN` |
| Ultima | `data/sequencing_run/ultima/1.0` | `BRT` |
| PacBio | `data/sequencing_run/pacbio/1.0` | `BRP` |
| CompleteGenomics | `data/sequencing_run/completegenomics/1.0` | `BRC` |

## Gate 0 Inventory

- Local worktree: `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom-seqrun-prefix-20260528`
- Base ref: Bloom tag `5.0.34` (`f8ba262d4d75ce01b67d4604cb586c45dc13525d`)
- Branch: `codex/bloom-seqrun-prefix-20260528`
- Source checkout note: parent checkout `/Users/jmajor/projects/mega_dayhoff/repos_work/bloom` was dirty and ahead of `origin/main`, so this work uses a clean release worktree.
- Production target: AWS `lsmcok1`, us-west-2, profile `lsmc`, instance `i-09126000eb19643b0`, Bloom service `https://bloom.day.lsmc.bio`
- Current shipped sequencing-run templates at Gate 0: `illumina`, `ont`, `novaseq`, all using instance prefix `BDT`.
- Crockford/Meridian validation: `BRM`, `BRN`, `BRT`, `BRP`, and `BRC` match `^[0-9A-HJ-KMNP-TV-Z]{1,4}$`.
- Release tag check: `git ls-remote --tags origin refs/tags/5.0.35` returned no tag before release.
- Local functional test evidence:
  - `python -m json.tool config/tapdb_templates/bloom/templates.json >/dev/null` passed.
  - `python3 -m json.tool bloom_lims/etc/prefix_ownership_registry.json >/dev/null` passed.
  - `source ./activate codex && python -m pytest tests/test_sequencing_run_contract.py tests/test_api_v1.py tests/test_route_coverage_gaps_api.py tests/test_cli_db_command_paths.py -q --no-cov` -> `172 passed, 23 skipped`.
  - Same focused suite without `--no-cov` had all functional tests pass but exited nonzero because repo-wide coverage was `34.55%`, below the configured `39%` focused-run threshold.
  - `source ./activate codex && python -m build` passed after installing the local packaging helper module `build` into `BLOOM-codex`.
- Release evidence:
  - Commit: `b51b00d362bb7a159e1822a168dfa5380210e940` (`Add sequencing run platform prefixes`)
  - Push: `origin/main` fast-forwarded from `37f4b0d` to `b51b00d`.
  - Tag: annotated Bloom tag `5.0.35`, tag object `76edae01209415788f8cb9ff1cc43859cbd8eb1d`, pushed to origin.
- Production evidence:
  - AWS Bloom running checkout `/home/ubuntu/.cache/dayhoff/local/lsmcok1/repos/bloom` was fast-forwarded to `5.0.35`.
  - Live config validation initially failed because `auth.external_broker.service_token` was empty; it was populated from the existing Dayhoff runtime secret file without printing the secret.
  - `BLOOM_DEPLOYMENT_CODE=lsmcok1 XDG_CONFIG_HOME=/home/ubuntu/.config bloom config validate` passed.
  - `BLOOM_DEPLOYMENT_CODE=lsmcok1 XDG_CONFIG_HOME=/home/ubuntu/.config bloom db refresh-templates` completed and reported `Retired obsolete Bloom sequencing-run templates: 3`.
  - Production API subtype listing returned `completegenomics,illumina,ont,pacbio,ultima`.
  - Production API create verification minted: `M-BRM-15`, `M-BRN-14`, `M-BRT-1Z`, `M-BRC-1D`, and `M-BRP-13`.
  - After updating the Bloom conda env from the `5.0.35` checkout, runtime packages are `bloom-lims 5.0.35` and `daylily-tapdb 7.0.8`.
  - Restart evidence: PID `481061`; `curl -sk https://localhost:8912/healthz` returned `health_http=200`; checkout reports `git describe --tags --always --dirty` -> `5.0.35`.

## Ledger Rows

| ID | Agent | Requirement | Status | Gate | Evidence | Terminal Note |
|---|---:|---|---|---|---|---|
| LEDGER-001 | 1 | Create ledger with local Bloom, current tags, dirty files, template inventory, and AWS production inventory | SUCCESS | Gate 0 | This file; Gate 0 inventory above | Ledger created and updated in the release worktree. |
| PREFIX-001 | 2 | Validate `BRM/BRN/BRT/BRP/BRC` are Crockford-safe and Bloom-owned prefixes | SUCCESS | Gate 1 | `bloom_lims/etc/prefix_ownership_registry.json`; JSON validation passed | Prefixes are Crockford-safe and registered as Bloom-owned in the packaged registry. |
| TEMPLATE-001 | 3 | Update Illumina and ONT templates to `BRM` and `BRN` prefix categories | SUCCESS | Gate 1 | `config/tapdb_templates/bloom/templates.json`; `tests/test_sequencing_run_contract.py` | Illumina and ONT active template definitions now use `BRM` and `BRN`. |
| TEMPLATE-002 | 3 | Add Ultima, PacBio, and CompleteGenomics sequencing-run templates | SUCCESS | Gate 1 | `config/tapdb_templates/bloom/templates.json`; `tests/test_sequencing_run_contract.py` | Added `ultima`, `pacbio`, and `completegenomics` semantic templates. |
| CODE-001 | 4 | Update allowed platform/subtype validation and template-code mapping for all five runs | SUCCESS | Gate 2 | `bloom_lims/schemas/beta_lab.py`, `bloom_lims/domain/beta_lab.py` | Beta run creation accepts the five explicit platform/subtype pairs and rejects mismatches. |
| GUI-001 | 5 | Verify create GUI lists all five under data/sequencing_run | SUCCESS | Gate 2 | `tests/test_route_coverage_gaps_api.py`; focused suite `172 passed, 23 skipped` | Object creation subtype endpoint returns exactly the five requested sequencing-run subtypes after template refresh. |
| API-001 | 6 | Verify API create flow can create all five template-backed run objects | SUCCESS | Gate 2 | `tests/test_route_coverage_gaps_api.py`; focused suite `172 passed, 23 skipped` | API creation mints `Z-BRM`, `Z-BRN`, `Z-BRT`, `Z-BRC`, and `Z-BRP` in local DB-backed tests. |
| TEST-001 | 7 | Add/update contract tests for template codes, prefixes, platform properties, and schema validation | SUCCESS | Gate 3 | `tests/test_sequencing_run_contract.py`, `tests/test_route_coverage_gaps_api.py`, `tests/test_cli_db_command_paths.py`, `tests/support/runtime.py` | Tests cover template content, beta schema validation, refresh command behavior, stale-template retirement, and API minting. |
| RELEASE-001 | 8 | Commit, push, tag next Bloom version, and push tag | SUCCESS | Gate 4 | Commit `b51b00d362bb7a159e1822a168dfa5380210e940`; annotated tag `5.0.35` / tag object `76edae01209415788f8cb9ff1cc43859cbd8eb1d`; `origin/main` updated | Bloom `5.0.35` released from the clean release worktree. |
| AWS-001 | 9 | Load templates into production Bloom using supported Bloom CLI/API, no raw DB edits | SUCCESS | Gate 5 | `bloom db refresh-templates`; `Retired obsolete Bloom sequencing-run templates: 3` | Production templates were loaded through the Bloom CLI. No raw DB edits were used. |
| AWS-002 | 9 | Verify production GUI/API creation and actual minted prefixes for all five | SUCCESS | Gate 5 | API listing returned all five subtypes; production API create minted `M-BRM-15`, `M-BRN-14`, `M-BRT-1Z`, `M-BRC-1D`, `M-BRP-13` | Verified actual production minting for every requested sequencing-run platform prefix. |
| FINAL-001 | 1 | Record commit, tag, production evidence, tests, and any blocked Dayhoff pin follow-up | SUCCESS | Gate 6 | This ledger; local tests/build; AWS `health_http=200`; runtime package check `bloom-lims 5.0.35`, `daylily-tapdb 7.0.8` | All rows terminal. Dayhoff pin/release-train follow-up remains out of scope for this Bloom-only plan. |
