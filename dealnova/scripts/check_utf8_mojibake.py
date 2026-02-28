#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT]
TEXT_EXTENSIONS = {
    ".py",
    ".html",
    ".jinja",
    ".j2",
    ".css",
    ".js",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
}
SKIP_DIR_NAMES = {"venv", ".venv", "__pycache__", "node_modules"}
MOJIBAKE_RE = re.compile(r"(Ã|Â|â€|â€™|â€œ|â€¦|ðŸ|�)")


def emit(line: str = "") -> None:
    sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="backslashreplace"))


def should_scan(path: Path) -> bool:
    if path.is_dir():
        return False
    if path.name == "check_utf8_mojibake.py":
        return False
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return False
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    return path.name == "run.py"


def iter_files() -> list[Path]:
    files: list[Path] = []
    for target in TARGETS:
        if target.is_file():
            if should_scan(target):
                files.append(target)
            continue
        if not target.exists():
            continue
        for path in target.rglob("*"):
            if should_scan(path):
                files.append(path)
    return files


def main() -> int:
    decode_errors: list[str] = []
    mojibake_hits: list[str] = []

    for path in iter_files():
        rel = path.relative_to(ROOT)
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            decode_errors.append(f"{rel}: not UTF-8 ({exc})")
            continue

        for line_no, line in enumerate(text.splitlines(), start=1):
            if MOJIBAKE_RE.search(line):
                mojibake_hits.append(f"{rel}:{line_no}: {line.strip()}")

    if decode_errors or mojibake_hits:
        emit("Encoding check failed.")
        if decode_errors:
            emit("")
            emit("[Non UTF-8 files]")
            for item in decode_errors:
                emit(f"- {item}")
        if mojibake_hits:
            emit("")
            emit("[Mojibake patterns]")
            for item in mojibake_hits:
                emit(f"- {item}")
        return 1

    emit("Encoding check passed: all scanned files are UTF-8 and mojibake-free.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
