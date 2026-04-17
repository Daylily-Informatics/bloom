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

## Dependency Boundary

- `environment.yaml` is only for Python/bootstrap/system packages.
- All Python libraries needed by the repo belong in `pyproject.toml` under `[project.dependencies]`.
- Do not reintroduce `pip:` blocks or Python package installs into `environment.yaml`.
- Do not add any secondary install set such as `.[dev]`, `.[test]`, `requirements-dev.txt`, or `[project.optional-dependencies]`.

## CLI Contract

- `bloom` and every declared console script must resolve from the activated conda env `bin/` directory.
- `bloom db build` must keep an explicit `--target` argument, and repo-solo local bootstrap examples should use `bloom db build --target local`.

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

## Bloom Examples

- Start with `source ./activate <deploy-name>`
- Use `bloom db build`
- Use `bloom db seed`
- Use `bloom server start --port 8912`
- Use `tapdb ...` and `daycog ...` only where Bloom docs or Bloom CLI explicitly delegate to them
