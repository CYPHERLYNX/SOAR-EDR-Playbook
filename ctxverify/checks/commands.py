"""Check 5: test commands.

Extracts runnable commands from docs (fenced code blocks, ``$``-prefixed
lines, and backticked invocations of known runners) and verifies:

* every path-like argument exists in the repo (missing -> ERROR)
* the runner binary exists on PATH (missing -> WARN, environment-dependent)
"""

from __future__ import annotations

import re
import shlex
import shutil

from ..findings import Finding, ScanContext, Verdict
from ..paths import is_ignored, looks_like_path

RUNNERS = frozenset({
    "pytest", "python", "python3", "pip", "pip3", "uv",
    "npm", "npx", "node", "yarn", "pnpm",
    "make", "cargo", "go", "dotnet", "mvn", "gradle",
    "bundle", "rspec", "phpunit", "composer",
})

FENCE_RE = re.compile(r"^(\s*)```")
BACKTICK_CMD_RE = re.compile(r"`([^`\n]+)`")


def _command_lines(text: str):
    """Yield (line_no, command_text) for plausible command lines."""
    lines = text.splitlines()
    in_fence = False
    for i, line in enumerate(lines, start=1):
        if is_ignored(line):
            continue
        stripped = line.strip()
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            cmd = stripped[2:].strip() if stripped.startswith("$ ") else stripped
            if cmd and not cmd.startswith("#"):
                yield i, cmd
        elif stripped.startswith("$ "):
            yield i, stripped[2:].strip()
    # Backticked runner invocations outside code blocks, e.g. run `pytest tests/`
    if not in_fence:
        for i, line in enumerate(lines, start=1):
            if is_ignored(line):
                continue
            for m in BACKTICK_CMD_RE.finditer(line):
                cmd = m.group(1).strip()
                first = cmd.split()[0] if cmd.split() else ""
                if first in RUNNERS:
                    yield i, cmd


def _strip_flags(tokens: list[str]) -> list[str]:
    out: list[str] = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            # Flags that take a value: -m, -k, -o, --junitxml etc. We cannot
            # know which; treat -x (single short) as standalone and swallow
            # the next token only for a small known set.
            if tok in ("-m", "-k", "-o", "--junitxml", "--cov", "-c",
                       "--rootdir", "-p"):
                skip_next = True
            continue
        out.append(tok)
    return out


def run(ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    for rel in ctx.docs:
        try:
            text = (ctx.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, cmd in _command_lines(text):
            try:
                tokens = shlex.split(cmd, posix=True)
            except ValueError:
                continue
            if not tokens or tokens[0] not in RUNNERS:
                continue
            key = (str(rel), lineno, cmd)
            if key in seen:
                continue
            seen.add(key)
            runner = tokens[0]
            if shutil.which(runner) is None:
                findings.append(Finding(
                    check="commands", verdict=Verdict.WARN, path=str(rel), line=lineno,
                    message=f"command references `{runner}` which is not on PATH",
                    detail=f"`{cmd}`",
                ))
            for tok in _strip_flags(tokens[1:]):
                if not looks_like_path(tok):
                    continue
                if tok.startswith("/") or tok.startswith(".."):
                    continue
                target = tok[2:] if tok.startswith("./") else tok
                # Trailing slashes are fine; strip them for the exists check.
                if not (ctx.root / target.rstrip("/")).exists():
                    findings.append(Finding(
                        check="commands", verdict=Verdict.ERROR, path=str(rel), line=lineno,
                        message=f"command references missing path `{target}`",
                        detail=f"`{cmd}`",
                    ))
    return findings
