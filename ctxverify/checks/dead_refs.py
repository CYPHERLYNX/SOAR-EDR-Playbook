"""Check 1: dead file references.

Extracts file paths mentioned in docs (markdown links, backticked paths,
quoted paths) and verifies each one exists in the repo. Missing targets are
ERROR findings with file:line.
"""

from __future__ import annotations

import re

from ..findings import Finding, ScanContext, Verdict
from ..paths import is_ignored, looks_like_path, strip_anchor

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
QUOTE_RE = re.compile(r'''(?:"([^"\n]+)"|'([^'\n]+)')''')


def _iter_candidates(text: str):
    """Yield (line_no, raw_target) for every path-like mention."""
    for i, line in enumerate(text.splitlines(), start=1):
        if is_ignored(line):
            continue
        for m in LINK_RE.finditer(line):
            yield i, strip_anchor(m.group(1).strip())
        for m in BACKTICK_RE.finditer(line):
            yield i, m.group(1).strip()
        for m in QUOTE_RE.finditer(line):
            yield i, (m.group(1) or m.group(2)).strip()


def run(ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    for rel in ctx.docs:
        try:
            text = (ctx.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, raw in _iter_candidates(text):
            if not looks_like_path(raw):
                continue
            # Resolve relative to the repo root; a leading ./ is harmless.
            if raw.startswith("/"):
                continue  # absolute path: out of scope
            if raw.startswith(".."):
                continue  # escapes the repo: out of scope
            target = raw[2:] if raw.startswith("./") else raw
            key = (str(rel), lineno, target)
            if key in seen:
                continue
            seen.add(key)
            if not (ctx.root / target).exists():
                findings.append(Finding(
                    check="dead-refs",
                    verdict=Verdict.ERROR,
                    path=str(rel),
                    line=lineno,
                    message=f"dead file reference: `{target}` does not exist",
                    detail=f"referenced as `{raw}`",
                ))
    return findings
