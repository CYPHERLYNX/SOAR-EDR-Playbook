"""Check 3: staleness.

For files that docs reference (and that exist), look at the last git commit
touching each file. Files untouched for longer than ``--stale-days``
(default 180) are flagged STALE (WARN): the docs describe them as current,
but the code has not moved in a long time.

Repos without git are skipped silently.
"""

from __future__ import annotations

import re
import subprocess
import time

from ..findings import Finding, ScanContext, Verdict
from ..paths import is_ignored, looks_like_path, strip_anchor

BACKTICK_RE = re.compile(r"`([^`\n]+)`")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _referenced_files(ctx: ScanContext) -> set[str]:
    refs: set[str] = set()
    for rel in ctx.docs:
        try:
            lines = (ctx.root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if is_ignored(line):
                continue
            candidates: list[str] = []
            for m in LINK_RE.finditer(line):
                candidates.append(strip_anchor(m.group(1).strip()))
            for m in BACKTICK_RE.finditer(line):
                candidates.append(m.group(1).strip())
            for raw in candidates:
                if not looks_like_path(raw):
                    continue
                if raw.startswith("/") or raw.startswith(".."):
                    continue
                target = raw[2:] if raw.startswith("./") else raw
                if (ctx.root / target).is_file():
                    refs.add(target)
    return refs


def _last_commit_ts(root, relpath: str) -> int | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%ct", "--", relpath],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if not out or not out.lstrip("-").isdigit():
        return None
    return int(out)


def _git_available(root) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=15,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run(ctx: ScanContext, stale_days: int = 180) -> list[Finding]:
    findings: list[Finding] = []
    if not _git_available(ctx.root):
        return findings
    now = int(time.time())
    for target in sorted(_referenced_files(ctx)):
        ts = _last_commit_ts(ctx.root, target)
        if ts is None:
            continue
        age_days = (now - ts) // 86400
        if age_days > stale_days:
            doc = _first_doc_mention(ctx, target) or (str(ctx.docs[0]) if ctx.docs else "")
            findings.append(Finding(
                check="staleness",
                verdict=Verdict.WARN,
                path=doc,
                line=_first_doc_line(ctx, target),
                message=f"stale reference: `{target}` untouched for {age_days} days "
                        f"(threshold {stale_days})",
            ))
    return findings


def _first_doc_mention(ctx: ScanContext, target: str) -> str | None:
    for rel in ctx.docs:
        try:
            text = (ctx.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if target in text or target.lstrip("./") in text:
            return str(rel)
    return None


def _first_doc_line(ctx: ScanContext, target: str) -> int:
    for rel in ctx.docs:
        try:
            lines = (ctx.root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, start=1):
            if target in line or target.lstrip("./") in line:
                return i
    return 1
