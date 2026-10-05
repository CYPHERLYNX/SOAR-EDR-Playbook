"""Core data types: findings, verdicts, and the shared scan context."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class Verdict:
    ERROR = "ERROR"
    WARN = "WARN"


@dataclass
class Finding:
    """One docs-vs-code discrepancy."""

    check: str  # e.g. "dead-refs", "symbols", "staleness", "manifest", "commands"
    verdict: str  # Verdict.ERROR or Verdict.WARN
    path: str  # doc file, relative to repo root
    line: int  # 1-based line number in the doc
    message: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "check": self.check,
            "verdict": self.verdict,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class ScanContext:
    """Shared state handed to every check."""

    root: Path  # absolute repo root
    docs: list[Path] = field(default_factory=list)  # doc files, relative to root
    exclude: tuple[str, ...] = ()

    def doc_lines(self, rel: Path) -> list[str]:
        return (self.root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
