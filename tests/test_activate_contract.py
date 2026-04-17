from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_fake_conda(tmp_path: Path) -> Path:
    fake_root = tmp_path / "conda-root"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    conda_script = fake_bin / "conda"
    conda_script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

fake_root="{fake_root}"

if [[ "${{1:-}}" == "shell.bash" && "${{2:-}}" == "hook" ]]; then
  cat <<'EOF'
conda() {{
  if [[ "${{1:-}}" == "info" && "${{2:-}}" == "--envs" ]]; then
    printf '# conda environments:\\n'
    if [[ -d "{fake_root}/envs/BLOOM-smoke" ]]; then
      printf '%s\\n' "BLOOM-smoke               {fake_root}/envs/BLOOM-smoke"
    fi
    return 0
  fi

  if [[ "${{1:-}}" == "info" && "${{2:-}}" == "--base" ]]; then
    printf '%s\\n' "{fake_root}"
    return 0
  fi

  if [[ "${{1:-}}" == "env" && "${{2:-}}" == "create" ]]; then
    local env_name=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        -n)
          shift
          env_name="${{1:-}}"
          ;;
      esac
      shift || true
    done

    local env_dir="{fake_root}/envs/$env_name"
    mkdir -p "$env_dir/bin"
    cat >"$env_dir/bin/python" <<'PYEOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "pip" && "${{3:-}}" == "install" && "${{4:-}}" == "-e" ]]; then
  printf '%s\\n' "${{5:-}}" >> "${{FAKE_CONDA_ROOT}}/pip-install.log"
  cat >"${{CONDA_PREFIX}}/bin/bloom" <<'BLOOMEOF'
#!/usr/bin/env bash
printf 'bloom cli ok\\n'
BLOOMEOF
  chmod +x "${{CONDA_PREFIX}}/bin/bloom"
  exit 0
fi
exec /usr/bin/env python3 "$@"
PYEOF
    chmod +x "$env_dir/bin/python"
    return 0
  fi

  if [[ "${{1:-}}" == "activate" ]]; then
    export CONDA_DEFAULT_ENV="${{2:-}}"
    export CONDA_PREFIX="{fake_root}/envs/${{2:-}}"
    export PATH="${{CONDA_PREFIX}}/bin:${{PATH}}"
    return 0
  fi

  return 0
}}
EOF
  exit 0
fi

exit 0
""",
        encoding="utf-8",
    )
    conda_script.chmod(0o755)
    return fake_bin


def test_activate_creates_env_and_puts_cli_on_path(tmp_path: Path) -> None:
    activate = (PROJECT_ROOT / "activate").read_text(encoding="utf-8")
    assert '"${CONDA_PREFIX}/bin/python" -m pip install -e' in activate
    assert "python -m pip install -e" not in activate.replace(
        '"${CONDA_PREFIX}/bin/python" -m pip install -e', ""
    )

    fake_bin = _write_fake_conda(tmp_path)
    fake_root = tmp_path / "conda-root"
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "FAKE_CONDA_ROOT": str(fake_root),
    }
    script = (
        f"set -euo pipefail\n"
        f'source "{PROJECT_ROOT / "activate"}" smoke\n'
        f"command -v bloom\n"
        f"bloom --help\n"
        f'source "{PROJECT_ROOT / "activate"}" smoke\n'
        f"command -v bloom\n"
    )

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    install_lines = (
        (fake_root / "pip-install.log").read_text(encoding="utf-8").splitlines()
    )
    assert install_lines
    assert set(install_lines) == {str(PROJECT_ROOT)}
    assert (
        result.stdout.count("Installing editable Bloom package into BLOOM-smoke...")
        == 1
    )
    assert "bloom cli ok" in result.stdout
