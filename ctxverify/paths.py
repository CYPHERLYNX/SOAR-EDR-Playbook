"""Shared heuristics for spotting file-path mentions in prose."""

from __future__ import annotations

import re

PATH_EXTS = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".md", ".markdown", ".rst", ".txt", ".json", ".toml", ".yaml",
    ".yml", ".cfg", ".ini", ".env", ".sh", ".bash", ".zsh", ".sql",
    ".html", ".css", ".scss", ".rs", ".go", ".java", ".rb", ".php",
    ".c", ".h", ".hpp", ".cpp", ".cs", ".swift", ".kt", ".lock",
})

_SKIP_PREFIXES = ("http://", "https://", "mailto:", "ftp://", "file://",
                  "~/", "$", "<", ">", "#")

_REMOTE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def looks_like_path(text: str) -> bool:
    """Conservative heuristic: does this string look like a repo file path?"""
    s = text.strip().rstrip(",.;:!?")
    if not s or " " in s or "\t" in s:
        return False
    if "\n" in s:
        return False
    low = s.lower()
    if low.startswith(_SKIP_PREFIXES) or "://" in s:
        return False
    if s in {".", "..", "...", "-", "--"}:
        return False
    # Glob patterns are not concrete paths.
    if any(c in s for c in "*?[]{}"):
        return False
    # Windows drive paths and UNC paths are out of scope for repo checks.
    if len(s) > 2 and s[1] == ":":
        return False
    parts = [p for p in re.split(r"[/\\]", s) if p not in ("", ".")]
    if not parts:
        return False
    # `j/k` — keyboard shortcut, not a path.
    if all(len(p) == 1 for p in parts):
        return False
    # `owner/repo[/path]` — a reference to another repository, not a
    # local file. No dots in any segment distinguishes it from real
    # relative paths (which virtually always carry an extension, and
    # dot-directories like `.github` keep their leading dot).
    if len(parts) >= 2 and all(_REMOTE_SEGMENT_RE.match(p) for p in parts):
        return False
    if "/" in s or "\\" in s:
        # Something like src/foo.py, ./run.sh.
        return True
    # Bare filename: only with a recognised extension.
    dot = s.rfind(".")
    if dot > 0 and s[dot:].lower() in PATH_EXTS:
        return True
    return False


def strip_anchor(target: str) -> str:
    """Remove a #fragment from a markdown link target."""
    return target.split("#", 1)[0]


IGNORE_RE = re.compile(r"ctxverify\s*:\s*ignore")


def is_ignored(line: str) -> bool:
    """True if the line carries a ctxverify ignore marker.

    Add ``<!-- ctxverify: ignore -->`` anywhere on a line to skip all
    checks for that line — for illustrative examples, sample output, etc.
    """
    return bool(IGNORE_RE.search(line))
