from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_PYTHON = sys.executable


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _make_shell_stubs(
    tmp_path: Path,
    *,
    repo_local_version: str = "",
    scm_version: str = "",
    fail_install: bool = False,
    fail_runtime_ready: bool = False,
    preexisting_env: str | None = None,
) -> tuple[Path, Path]:
    stub_root = tmp_path / "stubs"
    conda_root = stub_root / "conda-root"
    envs_root = conda_root / "envs"
    stub_root.mkdir(parents=True, exist_ok=True)
    envs_root.mkdir(parents=True, exist_ok=True)
    log_file = stub_root / "conda.log"

    host_python = textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -e
        if [[ "${1:-}" == "-c" ]]; then
            case "${2:-}" in
                *DEFAULT_BLOOM_WEB_PORT*)
                    printf '8912\n'
                    exit 0
                    ;;
                *DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT*)
                    printf '5566\n'
                    exit 0
                    ;;
            esac
        fi
        if [[ "${1:-}" == "-" ]]; then
            script="$(cat)"
            case "$script" in
                *'importlib.import_module'*)
                    if [[ "${BLOOM_FAIL_RUNTIME_READY:-0}" == "1" ]]; then
                        exit 1
                    fi
                    exit 0
                    ;;
                *'from bloom_lims._version import get_version'*)
                    if [[ -n "${BLOOM_REPO_LOCAL_VERSION:-}" ]]; then
                        printf '%s\n' "$BLOOM_REPO_LOCAL_VERSION"
                        exit 0
                    fi
                    exit 1
                    ;;
                *'from setuptools_scm import get_version'*)
                    if [[ -n "${BLOOM_SCM_VERSION:-}" ]]; then
                        printf '%s\n' "$BLOOM_SCM_VERSION"
                        exit 0
                    fi
                    exit 1
                    ;;
                *tomllib*)
                    exit 1
                    ;;
            esac
        fi
        exit 1
        """
    ).strip()
    _write_executable(stub_root / "python", host_python + "\n")

    env_python = textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -e
        if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
            case "${3:-}" in
                install)
                    printf '%s\n' "pip install $*" >> "__LOG_FILE__"
                    if [[ "${BLOOM_FAIL_INSTALL:-0}" == "1" ]]; then
                        exit 1
                    fi
                    exit 0
                    ;;
                show)
                    if [[ "${4:-}" == "bloom_lims" ]]; then
                        printf 'Name: bloom_lims\nEditable project location: __PROJECT_ROOT__\n'
                        exit 0
                    fi
                    exit 1
                    ;;
            esac
        fi
        if [[ "${1:-}" == "-c" ]]; then
            case "${2:-}" in
                *DEFAULT_BLOOM_WEB_PORT*)
                    printf '8912\n'
                    exit 0
                    ;;
                *DEFAULT_BLOOM_TAPDB_LOCAL_PG_PORT*)
                    printf '5566\n'
                    exit 0
                    ;;
            esac
        fi
        if [[ "${1:-}" == "-" ]]; then
            script="$(cat)"
            case "$script" in
                *'importlib.import_module'*)
                    if [[ "${BLOOM_FAIL_RUNTIME_READY:-0}" == "1" ]]; then
                        exit 1
                    fi
                    exit 0
                    ;;
                *'from bloom_lims._version import get_version'*)
                    if [[ -n "${BLOOM_REPO_LOCAL_VERSION:-}" ]]; then
                        printf '%s\n' "$BLOOM_REPO_LOCAL_VERSION"
                        exit 0
                    fi
                    exit 1
                    ;;
                *'from setuptools_scm import get_version'*)
                    if [[ -n "${BLOOM_SCM_VERSION:-}" ]]; then
                        printf '%s\n' "$BLOOM_SCM_VERSION"
                        exit 0
                    fi
                    exit 1
                    ;;
            esac
        fi
        exit 1
        """
    ).strip()
    env_python = env_python.replace("__LOG_FILE__", str(log_file)).replace(
        "__PROJECT_ROOT__", str(PROJECT_ROOT)
    )
    _write_executable(stub_root / "env-python", env_python + "\n")

    conda_stub = textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -e
        root="__STUB_ROOT__"
        env_root="$root/conda-root/envs"
        log_file="__LOG_FILE__"
        if [[ "${1:-}" == "shell.bash" || "${1:-}" == "shell.zsh" ]]; then
            printf '%s\n' 'conda() {'
            printf '%s\n' '  local cmd="${1:-}"'
            printf '%s\n' '  shift || true'
            printf '%s\n' '  case "$cmd" in'
            printf '%s\n' '    activate)'
            printf '%s\n' '      printf "%s %s\n" activate "${1:-}" >> "'"$log_file"'"'
            printf '%s\n' '      export __BLOOM_PREV_CONDA_DEFAULT_ENV="${CONDA_DEFAULT_ENV:-}"'
            printf '%s\n' '      export __BLOOM_PREV_CONDA_PREFIX="${CONDA_PREFIX:-}"'
            printf '%s\n' '      export __BLOOM_PREV_PATH="${PATH:-}"'
            printf '%s\n' '      export CONDA_DEFAULT_ENV="${1:-}"'
            printf '%s\n' '      export CONDA_PREFIX="'"$env_root"'/${1:-}"'
            printf '%s\n' '      export PATH="$CONDA_PREFIX/bin:$PATH"'
            printf '%s\n' '      ;;'
            printf '%s\n' '    deactivate)'
            printf '%s\n' '      printf "%s\n" deactivate >> "'"$log_file"'"'
            printf '%s\n' '      if [[ -n "${__BLOOM_PREV_PATH:-}" ]]; then'
            printf '%s\n' '        if [[ -n "${__BLOOM_PREV_CONDA_DEFAULT_ENV:-}" ]]; then'
            printf '%s\n' '          export CONDA_DEFAULT_ENV="${__BLOOM_PREV_CONDA_DEFAULT_ENV}"'
            printf '%s\n' '        else'
            printf '%s\n' '          unset CONDA_DEFAULT_ENV'
            printf '%s\n' '        fi'
            printf '%s\n' '        if [[ -n "${__BLOOM_PREV_CONDA_PREFIX:-}" ]]; then'
            printf '%s\n' '          export CONDA_PREFIX="${__BLOOM_PREV_CONDA_PREFIX}"'
            printf '%s\n' '        else'
            printf '%s\n' '          unset CONDA_PREFIX'
            printf '%s\n' '        fi'
            printf '%s\n' '        export PATH="${__BLOOM_PREV_PATH}"'
            printf '%s\n' '        unset __BLOOM_PREV_CONDA_DEFAULT_ENV __BLOOM_PREV_CONDA_PREFIX __BLOOM_PREV_PATH'
            printf '%s\n' '      fi'
            printf '%s\n' '      ;;'
            printf '%s\n' '    info)'
            printf '%s\n' '      command "'"$root"'/conda" info "$@"'
            printf '%s\n' '      ;;'
            printf '%s\n' '    env)'
            printf '%s\n' '      command "'"$root"'/conda" env "$@"'
            printf '%s\n' '      ;;'
            printf '%s\n' '    *)'
            printf '%s\n' '      command "'"$root"'/conda" "$cmd" "$@"'
            printf '%s\n' '      ;;'
            printf '%s\n' '  esac'
            printf '%s\n' '}'
            exit 0
        fi
        case "${1:-}" in
            info)
                if [[ "${2:-}" == "--envs" ]]; then
                    printf '# conda environments:\n'
                    for env_dir in "$env_root"/*; do
                        [[ -d "$env_dir" ]] || continue
                        printf '%s\n' "$(basename "$env_dir")"
                    done
                    exit 0
                fi
                exit 0
                ;;
            env)
                case "${2:-}" in
                    create)
                        env_name="${4:-}"
                        mkdir -p "$env_root/$env_name/bin"
                        cp "$root/env-python" "$env_root/$env_name/bin/python"
                        chmod 755 "$env_root/$env_name/bin/python"
                        printf '%s %s\n' "env create" "$env_name" >> "$log_file"
                        exit 0
                        ;;
                    remove)
                        env_name="${4:-}"
                        printf '%s %s\n' "env remove" "$env_name" >> "$log_file"
                        rm -rf "$env_root/$env_name"
                        exit 0
                        ;;
                esac
                exit 0
                ;;
        esac
        if [[ "${1:-}" == "tag" && "${2:-}" == "--points-at" && "${3:-}" == "HEAD" && -n "__GIT_TAG__" ]]; then
            printf '%s\n' "__GIT_TAG__"
            exit 0
        fi
        exit 1
        """
    ).strip()
    conda_stub = conda_stub.replace("__STUB_ROOT__", str(stub_root)).replace(
        "__LOG_FILE__", str(log_file)
    ).replace("__GIT_TAG__", "")
    _write_executable(stub_root / "conda", conda_stub + "\n")

    if preexisting_env:
        preexisting_dir = envs_root / preexisting_env / "bin"
        preexisting_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stub_root / "env-python", preexisting_dir / "python")

    return stub_root, log_file


def _run_activate(
    shell_name: str,
    tmp_path: Path,
    *,
    args: list[str] | None = None,
    repo_local_version: str = "",
    scm_version: str = "",
    fail_install: bool = False,
    fail_runtime_ready: bool = False,
    preexisting_env: str | None = None,
    active_env: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if shutil.which(shell_name) is None:
        pytest.skip(f"{shell_name} is not available")

    stub_root, log_file = _make_shell_stubs(
        tmp_path,
        repo_local_version=repo_local_version,
        scm_version=scm_version,
        fail_install=fail_install,
        fail_runtime_ready=fail_runtime_ready,
        preexisting_env=preexisting_env,
    )

    env = os.environ.copy()
    env["PATH"] = f"{stub_root}:{env.get('PATH', '')}"
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    env["BLOOM_FAIL_INSTALL"] = "1" if fail_install else "0"
    env["BLOOM_FAIL_RUNTIME_READY"] = "1" if fail_runtime_ready else "0"
    env["BLOOM_REPO_LOCAL_VERSION"] = repo_local_version
    env["BLOOM_SCM_VERSION"] = scm_version
    env["BLOOM_ROOT"] = str(PROJECT_ROOT)
    if active_env:
        env["CONDA_DEFAULT_ENV"] = active_env
        env["CONDA_PREFIX"] = str(stub_root / "conda-root" / "envs" / active_env)
        (stub_root / "conda-root" / "envs" / active_env / "bin").mkdir(
            parents=True, exist_ok=True
        )
        shutil.copy2(
            stub_root / "env-python",
            stub_root / "conda-root" / "envs" / active_env / "bin" / "python",
        )
    else:
        env.pop("CONDA_DEFAULT_ENV", None)
        env.pop("CONDA_PREFIX", None)

    activate_args = " ".join(shlex.quote(arg) for arg in (args or []))
    activate_path = shlex.quote(str(PROJECT_ROOT / "activate"))
    script = textwrap.dedent(
        f"""\
        source {activate_path} {activate_args}
        rc=$?
        printf 'STATUS=%s\n' "$rc"
        printf 'CONDA_DEFAULT_ENV=%s\n' "${{CONDA_DEFAULT_ENV:-}}"
        printf 'CONDA_PREFIX=%s\n' "${{CONDA_PREFIX:-}}"
        printf 'BLOOM_DEPLOYMENT_CODE=%s\n' "${{BLOOM_DEPLOYMENT_CODE:-}}"
        printf 'LOG=%s\n' "$(cat {shlex.quote(str(log_file))} 2>/dev/null || true)"
        exit "$rc"
        """
    )
    shell_args = [shell_name, "-f", "-c", script] if shell_name == "zsh" else [
        shell_name,
        "--noprofile",
        "--norc",
        "-c",
        script,
    ]
    return subprocess.run(
        shell_args,
        capture_output=True,
        text=True,
        env=env,
        cwd=PROJECT_ROOT,
        check=False,
    )


@pytest.mark.parametrize("shell_name", ["bash", "zsh"])
def test_activate_defaults_to_normalized_version_name(
    tmp_path: Path, shell_name: str
) -> None:
    result = _run_activate(
        shell_name,
        tmp_path,
        repo_local_version="abc.def/ghij",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "BLOOM-abc-def-g" in result.stdout
    assert "CONDA_DEFAULT_ENV=BLOOM-abc-def-g" in result.stdout
    assert "BLOOM_DEPLOYMENT_CODE=abc-def-g" in result.stdout
    assert "env create BLOOM-abc-def-g" in result.stdout
    assert (tmp_path / "stubs" / "conda-root" / "envs" / "BLOOM-abc-def-g").is_dir()


@pytest.mark.parametrize("shell_name", ["bash", "zsh"])
def test_activate_rejects_too_short_deploy_name(
    tmp_path: Path, shell_name: str
) -> None:
    result = _run_activate(
        shell_name,
        tmp_path,
        args=["ab"],
    )

    assert result.returncode != 0
    assert "deploy-name must match ^[A-Za-z0-9-]{3,9}$" in result.stdout


@pytest.mark.parametrize("shell_name", ["bash", "zsh"])
def test_activate_accepts_three_character_deploy_name(
    tmp_path: Path, shell_name: str
) -> None:
    result = _run_activate(
        shell_name,
        tmp_path,
        args=["abc"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "BLOOM-abc" in result.stdout
    assert "BLOOM_DEPLOYMENT_CODE=abc" in result.stdout


@pytest.mark.parametrize("shell_name", ["bash", "zsh"])
def test_activate_cleans_up_created_env_on_failure(
    tmp_path: Path, shell_name: str
) -> None:
    result = _run_activate(
        shell_name,
        tmp_path,
        repo_local_version="abc.def/ghij",
        fail_install=True,
        active_env="LEGACY",
    )

    assert result.returncode != 0
    assert "BLOOM activation failed" in result.stdout
    assert "deploy-name: BLOOM-abc-def-g" in result.stdout
    assert "debug: 0" in result.stdout
    assert "CONDA_DEFAULT_ENV=LEGACY" in result.stdout
    assert "env create BLOOM-abc-def-g" in result.stdout
    assert "env remove BLOOM-abc-def-g" in result.stdout
    assert not (tmp_path / "stubs" / "conda-root" / "envs" / "BLOOM-abc-def-g").exists()


def test_activate_preserves_preexisting_env_on_failure(tmp_path: Path) -> None:
    result = _run_activate(
        "bash",
        tmp_path,
        repo_local_version="abc.def/ghij",
        fail_runtime_ready=True,
        preexisting_env="BLOOM-abc-def-g",
        active_env="LEGACY",
    )

    assert result.returncode != 0
    assert "env create BLOOM-abc-def-g" not in result.stdout
    assert "env remove BLOOM-abc-def-g" not in result.stdout
    assert (tmp_path / "stubs" / "conda-root" / "envs" / "BLOOM-abc-def-g").is_dir()


def test_activate_debug_skips_created_env_cleanup(tmp_path: Path) -> None:
    result = _run_activate(
        "bash",
        tmp_path,
        args=["--debug"],
        repo_local_version="abc.def/ghij",
        fail_install=True,
        active_env="LEGACY",
    )

    assert result.returncode != 0
    assert "debug: 1" in result.stdout
    assert "env create BLOOM-abc-def-g" in result.stdout
    assert "env remove BLOOM-abc-def-g" not in result.stdout
    assert (tmp_path / "stubs" / "conda-root" / "envs" / "BLOOM-abc-def-g").is_dir()
