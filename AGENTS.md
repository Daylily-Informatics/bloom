# Shell Session Defaults

- Default to an interactive shell for shell work. On this Mac, use the user's default shell unless the user explicitly asks for another shell.
- For AWS EC2, ParallelCluster, and other remote Linux hosts, default to an interactive `bash` login shell as `ubuntu`. Do not use `root` unless the user explicitly grants permission for that specific work; use targeted `sudo` from `ubuntu` when escalation is required.
- For Daylily/DayOA/DAY-EC headnode workflow work, use an interactive `ubuntu` tmux/login-shell pane for controllers and workflow commands. Run setup as separate commands in that pane (`source dyoainit`, then `dy-a ...`, then `dy-r ...`) so aliases/functions are defined before use.
- SSM Run Command is for simple inspection or for writing helper scripts through the supported helpers. Do not launch workflow controllers or rely on `dy-*` aliases from non-interactive SSM scripts.

# Bloom CLI Policy

## Session Setup

Always start by activating the repo environment:

```bash
source ./activate <deploy-name>
```

## Activate Contract

- `activate` must stay env-only: create the conda env if missing, activate it, and run exactly one `python -m pip install -e <repo-root>` on first create.
- Do not add config copying, TapDB env exports, loader-path mutation, pre-commit installs, Playwright installs, shell tool checks, or DB/bootstrap work back into `activate`.
- If Bloom needs runtime configuration or TapDB namespace setup, move that logic into `bloom config init`, `bloom db build`, or Dayhoff-generated bootstrap scripts instead of `activate`.
- Every service config, TapDB config, and TapDB registry path must be passed explicitly as a full absolute file path.
- Do not guess TapDB config or registry paths from deployment code, `~/.config`, or repo-local defaults during runtime startup.
- If Bloom is missing an explicit path, fail hard and fix the caller or config source instead of synthesizing a fallback path.

## Dependency Boundary

- `environment.yaml` is only for Python/bootstrap/system packages.
- All Python libraries needed by the repo belong in `pyproject.toml` under `[project.dependencies]`.
- Do not reintroduce `pip:` blocks or Python package installs into `environment.yaml`.
- Do not add any secondary install set such as `.[dev]`, `.[test]`, `requirements-dev.txt`, or `[project.optional-dependencies]`.

## CLI Contract

- `bloom` and every declared console script must resolve from the activated conda env `bin/` directory.
- `bloom db build` must keep an explicit `--target` argument, and repo-solo local bootstrap examples should use `bloom db build --target local`.
- Bloom runtime and bootstrap commands must consume explicit absolute config file paths.
- Do not reintroduce service-config, TapDB config, or registry-path guessing from deployment names, `HOME`, `~/.config`, or silent fallback helpers.
- If Bloom is invoked by Dayhoff or another orchestrator, that caller must pass the full absolute `--config` path plus the full absolute TapDB config and registry paths Bloom needs.
- `bloom config init` may materialize the deployment-scoped YAML, but every later runtime/bootstrap path must fail hard when required explicit file paths are missing or non-absolute.

## Command Ownership

- Use `bloom ...` as the primary interface for normal Bloom work.
- MUST use Bloom's supported API/CLI surface for Bloom operations.
- Use `tapdb ...` only when Bloom explicitly delegates low-level DB/runtime lifecycle to TapDB.
- Use `daycog ...` only when Bloom explicitly delegates shared Cognito lifecycle to Daycog.

## No Circumvention Policy

- Do not bypass `bloom`, `tapdb`, or `daycog` with raw tools just because something is missing or broken.
- Do not treat direct `python -m ...`, raw `postgres`, raw AWS CLI mutations, or direct config-file edits as automatic fallbacks.
- Do not use temporary auth/runtime override hacks such as `BLOOM_OAUTH=no` or ad hoc `BLOOM_AUTH__*` values to force startup unless the user explicitly asks for that exact workaround.
- If the intended CLI path is broken or incomplete, stop, diagnose, and ask for permission before circumventing it.
- Prefer patience and repair of the intended CLI workflow over inventing a shortcut.

## Dayhoff Service Exposure Security

- Bloom is an LSMC-internal only Dayhoff service. Do not configure it as an approved-network customer/collaborator service.
- Do not add globally public Bloom ingress, wildcard/fallback vhosts, old callback aliases, inferred return URLs, or service-side host discovery.
- Bloom should consume explicit broker/service claims and explicit Dayhoff-generated service config. Do not infer customer network or tenant access locally.
- `kahlo`, `bloom`, and `zebra_day` are LSMC-internal only; `login`, `atlas`, `dewey`, and `ursa` are approved-network customer/collaborator services.
- Service-host certs use DNS-01 renewal; do not depend on HTTP-01 public reachability for Bloom service hosts.
- Future dev, test, and stage deployments must use their own approved-source lists, credentials, certificates, TapDB schemas, and tenant data, separate from production.

## Version Tags

- Use non-v semver tags for package releases, e.g. `2.0.19` or `5.0.21`, not `v2.0.19`.
- Commit first, then tag the exact clean release commit.
- Use annotated tags for release provenance: `git tag -a 2.0.19 -m "Release 2.0.19"`.
- Lightweight tags are acceptable only for scratch/internal marks, not package releases.
- Do not move or overwrite pushed version tags. If a pushed tag is wrong, cut the next patch version.
- If signing is configured and expected, use signed annotated tags: `git tag -s 2.0.19 -m "Release 2.0.19"`.
- Verify tag type with `git cat-file -t 2.0.18`; `tag` means annotated and `commit` means lightweight.

## Bloom Examples

- Start with `source ./activate <deploy-name>`
- Use `bloom db build`
- Use `bloom db seed`
- Use `bloom server start --port 8912`
- Use `tapdb ...` and `daycog ...` only where Bloom docs or Bloom CLI explicitly delegate to them
