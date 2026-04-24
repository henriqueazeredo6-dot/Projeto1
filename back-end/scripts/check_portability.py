from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

INCLUDE_EXTENSIONS = {
    ".py",
    ".ps1",
    ".html",
    ".css",
    ".js",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
    ".env.example",
    ".txt",
    ".sql",
}

IGNORE_DIRS = {
    ".git",
    ".venv",
    ".deps",
    "__pycache__",
    "node_modules",
}

ABSOLUTE_PATTERNS = [
    re.compile(r"[A-Za-z]:[\\/][^\\s\"'`]+"),
    re.compile(r"(?<!https:)(?<!http:)/(Users|home|var|etc|opt|tmp)/[^\s\"'`]+"),
]


def should_scan(path: Path) -> bool:
    if any(part in IGNORE_DIRS for part in path.parts):
        return False
    if path.name == ".env":
        return False
    if path.name.lower() == "readme.md":
        return False
    return path.suffix.lower() in INCLUDE_EXTENSIONS or path.name.endswith(".env.example")


def find_matches(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")

    matches: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "http://" in line or "https://" in line:
            continue
        if path.name == "check_portability.py" and ("re.compile(" in line or "caminhos absolutos" in line):
            continue
        for pattern in ABSOLUTE_PATTERNS:
            if pattern.search(line):
                matches.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")
                break
    return matches


def main() -> int:
    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if not should_scan(path):
            continue
        offenders.extend(find_matches(path))

    if offenders:
        print("Foram encontrados caminhos absolutos no projeto:\n")
        for offender in offenders:
            print(offender)
        print("\nUse caminhos relativos ou o helper de paths do projeto.")
        return 1

    print("Nenhum caminho absoluto encontrado. Projeto portavel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
