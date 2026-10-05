"""Discovery of agent-facing documentation files."""

from __future__ import annotations

from pathlib import Path

from .findings import ScanContext

DEFAULT_DOC_NAMES = ("CLAUDE.md", "AGENTS.md", "README.md")
DEFAULT_DOC_DIRS = ("docs", ".claude")


def discover_docs(root: Path, explicit: list[str] | None = None) -> list[Path]:
    """Return doc files (relative to root). Explicit list replaces defaults.

    Explicit entries may be files, directories (scanned recursively for
    ``*.md``), or glob patterns relative to root.
    """
    root = root.resolve()
    found: list[Path] = []

    def add(p: Path) -> None:
        rel = p.relative_to(root)
        if rel not in found:
            found.append(rel)

    if explicit:
        for entry in explicit:
            entry = entry.strip()
            if not entry:
                continue
            matches = sorted(root.glob(entry))
            if not matches:
                # Treat a non-glob literal as a direct path even if missing;
                # callers report it, discovery stays silent.
                cand = root / entry
                if cand.is_file():
                    add(cand)
                continue
            for m in matches:
                if m.is_file():
                    add(m)
                elif m.is_dir():
                    for f in sorted(m.rglob("*.md")):
                        if f.is_file():
                            add(f)
        return found

    for name in DEFAULT_DOC_NAMES:
        cand = root / name
        if cand.is_file():
            add(cand)
    for dname in DEFAULT_DOC_DIRS:
        d = root / dname
        if d.is_dir():
            for f in sorted(d.rglob("*.md")):
                if f.is_file():
                    add(f)
    return found


def build_context(root: Path, docs_arg: list[str] | None,
                   exclude: list[str] | None) -> ScanContext:
    root = Path(root).resolve()
    docs = discover_docs(root, docs_arg)
    return ScanContext(root=root, docs=docs, exclude=tuple(exclude or ()))
