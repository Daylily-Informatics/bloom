# Bloom PR disposition after phase-2 deployment

Status: SUCCESS — all six previously open PRs assessed and updated; four closed, two retained. No PR creation, rebase, update-branch, merge, dependency installation, tests or further deployment.

Assessment began only after Bloom 10.0.3 deployment and authenticated access were accepted. Its exact release commit is `84af628dcd6b135ba0785cfcf9081cbc64b3d399`. Every assessed diff changes only one dependency block in `uv.lock`; none of the six proposed versions is already installed in that release.

The user authorized closing obsolete PRs. Closures below use definite exact-version supersession, not the ambiguous phrase about features being absent. Useful upgrade needs remain explicit below; no missing feature was silently discarded or claimed implemented.

| PR | Dependency | Installed | PR target | Current PyPI release | Disposition |
|---|---|---|---|---|---|
| [#10](https://github.com/lsmc-bio/bloom/pull/10) | cryptography | 48.0.0 | 50.0.0 | 50.0.1 | CLOSED: exact target superseded |
| [#9](https://github.com/lsmc-bio/bloom/pull/9) | pyasn1 | 0.6.3 | 0.6.4 | 0.6.4 | KEEP OPEN |
| [#8](https://github.com/lsmc-bio/bloom/pull/8) | pillow | 12.2.0 | 12.3.0 | 12.3.0 | KEEP OPEN |
| [#6](https://github.com/lsmc-bio/bloom/pull/6) | starlette | 1.1.0 | 1.3.1 | 1.6.0 | CLOSED: exact target superseded |
| [#5](https://github.com/lsmc-bio/bloom/pull/5) | pydantic-settings | 2.14.1 | 2.14.2 | 2.15.0 | CLOSED: exact target superseded |
| [#4](https://github.com/lsmc-bio/bloom/pull/4) | python-multipart | 0.0.29 | 0.0.31 | 0.0.32 | CLOSED: exact target superseded |

## Remaining PRs worth selecting

1. **#9 — pyasn1 0.6.4:** first priority among the remaining PRs; small transitive update in the python-jose/rsa chain, with upstream decoder resource-consumption fixes. Target is current and not yanked.
2. **#8 — Pillow 12.3.0:** worthwhile image/PDF parser maintenance in the matplotlib dependency chain. Target is current and not yanked. No direct use of removed non-image ImageCms modes was found in Bloom.

These are recommendations for separate selection, not permission to integrate or merge. Existing green mergeability metadata was not used as proof of compatibility with the new release, and no CI campaign was started. Refresh the accepted release lock if either is selected; preserve exact TapDB 10.1.3 and the working-branch tagged-release policy.

## Closed PR upgrade needs retained

Cryptography 50.0.1, Starlette 1.6.0, pydantic-settings 2.15.0 and python-multipart 0.0.32 are current upstream candidates requiring separate selection and compatibility review. Newer version availability does not prove runtime compatibility. FastAPI 0.136.3 declares starlette>=0.46.0; that is a constraint observation, not a runtime acceptance result. No replacement PR was created.

- **#10 / cryptography:** The exact 50.0.0 target is superseded by 50.0.1, whose upstream wheels use a newer OpenSSL. Carry the cryptography upgrade forward as a separate candidate against the accepted Bloom release. The lock currently brings cryptography through moto; this review does not establish an application PKCS7 decryption exposure. [Upstream source](https://github.com/pyca/cryptography/blob/main/CHANGELOG.rst).
- **#9 / pyasn1:** The target is still current and absent from Bloom 10.0.3. Upstream identifies 0.6.4 as a security release addressing decoder resource consumption. Bloom retains pyasn1 through python-jose and rsa. This is a worthwhile small dependency update; no claim is made that a particular attack is reachable in Bloom. [Upstream source](https://github.com/pyasn1/pyasn1/releases/tag/v0.6.4).
- **#8 / pillow:** The target is still current and absent from Bloom 10.0.3. Upstream documents image/PDF parsing and memory-safety fixes. The current lock includes Pillow through matplotlib. Retain as dependency maintenance; source review found no direct Bloom ImageCms usage requiring the removed non-image modes. [Upstream source](https://pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html).
- **#6 / starlette:** The exact 1.3.1 target is superseded by 1.6.0. Preserve the Starlette upgrade need as a future candidate with current FastAPI/TapDB compatibility reviewed before selection. Bloom uses Starlette for its HTTP request/session stack and form routes. Published FastAPI 0.136.3 metadata permits starlette>=0.46.0; that declared constraint alone is not runtime compatibility proof. [Upstream source](https://pypi.org/pypi/starlette/json).
- **#5 / pydantic-settings:** The exact 2.14.2 target is superseded by 2.15.0. Preserve the settings upgrade need as a future candidate. Bloom uses BaseSettings and custom settings-source ordering; the newer target requires deliberate configuration review. No direct NestedSecretsSettingsSource use was found in Bloom source, so this review does not claim exposure to the older advisory. [Upstream source](https://pypi.org/pypi/pydantic-settings/json).
- **#4 / python-multipart:** The exact 0.0.31 target is superseded by 0.0.32. Preserve the multipart-parser upgrade need as a future candidate with Starlette. Bloom has active Form/UploadFile routes, including container TSV and lab-action uploads. Closing the old version request does not mean these improvements are already installed. [Upstream source](https://pypi.org/pypi/python-multipart/json).

## Execution receipts

Assessment comments: [#10](https://github.com/lsmc-bio/bloom/pull/10#issuecomment-5648924917), [#9](https://github.com/lsmc-bio/bloom/pull/9#issuecomment-5648925061), [#8](https://github.com/lsmc-bio/bloom/pull/8#issuecomment-5648925138), [#6](https://github.com/lsmc-bio/bloom/pull/6#issuecomment-5648925214), [#5](https://github.com/lsmc-bio/bloom/pull/5#issuecomment-5648925366), [#4](https://github.com/lsmc-bio/bloom/pull/4#issuecomment-5648925517). Native close commands succeeded for #10/#6/#5/#4; the final open-PR query returned only #9 and #8. Branches were not deleted.

Full local diff and package metadata receipts: `/Users/jmajor/.codex/artifacts/bloom-phase2-20260912/`. Closed/unmerged historical PR #2 was already closed and was not reopened or selected.
