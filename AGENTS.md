# Bloom CLI Policy

## Session Setup

Always start by activating the repo environment:

```bash
source ./activate <deploy-name>
```

## Command Ownership

- Use `bloom ...` as the primary interface for normal Bloom work.
- Use `tapdb ...` only when Bloom explicitly delegates low-level DB/runtime lifecycle to TapDB.
- Use `daycog ...` only when Bloom explicitly delegates shared Cognito lifecycle to Daycog.

## No Circumvention Policy

- Do not bypass `bloom`, `tapdb`, or `daycog` with raw tools just because something is missing or broken.
- Do not treat direct `python -m ...`, raw `postgres`, raw AWS CLI mutations, or direct config-file edits as automatic fallbacks.
- If the intended CLI path is broken or incomplete, stop, diagnose, and ask for permission before circumventing it.
- Prefer patience and repair of the intended CLI workflow over inventing a shortcut.

## Bloom Examples

- Start with `source ./activate <deploy-name>`
- Use `bloom db init`
- Use `bloom db seed`
- Use `bloom server start --port 8912`
- Use `tapdb ...` and `daycog ...` only where Bloom docs or Bloom CLI explicitly delegate to them
