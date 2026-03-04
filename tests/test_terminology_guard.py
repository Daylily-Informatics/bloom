"""
Guardrail tests enforcing TapDB canonical terminology in runtime code.
"""

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]

SCAN_TARGETS = [
    REPO_ROOT / "main.py",
    REPO_ROOT / "README.md",
    REPO_ROOT / "bloom_lims",
    REPO_ROOT / "static" / "js",
    REPO_ROOT / "templates" / "modern",
]

SKIP_PATH_PARTS = {
    "__pycache__",
    "docs",
    "legacy",
}

SCAN_SUFFIXES = {
    ".py",
    ".js",
    ".html",
    ".json",
    ".yaml",
    ".yml",
}

BANNED_PATTERNS = {
    "btype": re.compile(r"\bbtype\b"),
    "b_sub_type": re.compile(r"\bb_sub_type\b"),
    "super_type": re.compile(r"\bsuper_type\b"),
    "sub_type": re.compile(r"\bsub_type\b"),
}


def _iter_scan_files():
    for target in SCAN_TARGETS:
        if target.is_file():
            yield target
            continue

        for path in target.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            if any(part in SKIP_PATH_PARTS for part in path.parts):
                continue
            yield path


def test_runtime_uses_tapdb_canonical_terminology():
    findings = []

    for file_path in _iter_scan_files():
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for lineno, line in enumerate(content.splitlines(), start=1):
            for label, pattern in BANNED_PATTERNS.items():
                if pattern.search(line):
                    findings.append(
                        f"{file_path.relative_to(REPO_ROOT)}:{lineno}: banned '{label}' -> {line.strip()}"
                    )

    assert not findings, "Found banned legacy terminology:\n" + "\n".join(findings[:50])
