"""Check 2: phantom symbols.

Extracts symbol-like mentions (`` `train()` ``, `` `Trainer` ``,
`` `engine.train` ``) from docs and verifies them against the codebase.

* Python files are parsed with ``ast``: bare names match any module-level
  definition; dotted names match ``module.symbol``.
* If the repo has no Python source, a grep fallback searches for textual
  definitions (``def name``, ``class name``, ``name =``, ``function name``,
  ``const name`` ...). Anything still unfound is reported as UNVERIFIABLE
  (WARN) rather than missing, because the heuristic cannot prove absence.
* Confirmed-missing symbols in a parsed Python codebase are ERROR.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..findings import Finding, ScanContext, Verdict
from ..paths import is_ignored, looks_like_path

BACKTICK_RE = re.compile(r"`([^`\n]+)`")
IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
SYMBOL_RE = re.compile(rf"^{IDENT}(?:\.{IDENT})*\(\)?$")

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             ".tox", "dist", "build", ".eggs", "vendor"}


def _iter_symbol_mentions(text: str):
    for i, line in enumerate(text.splitlines(), start=1):
        if is_ignored(line):
            continue
        for m in BACKTICK_RE.finditer(line):
            raw = m.group(1).strip()
            if looks_like_path(raw):
                continue  # handled by dead-refs
            if SYMBOL_RE.match(raw):
                yield i, raw


def _iter_py_files(root: Path, exclude: tuple[str, ...]):
    skip = SKIP_DIRS | set(exclude)
    for p in root.rglob("*.py"):
        if any(part in skip for part in p.relative_to(root).parts):
            continue
        yield p


def _collect_python_defs(root: Path, exclude: tuple[str, ...]):
    """Return (bare_names, dotted_names)."""
    bare: set[str] = set()
    dotted: set[str] = set()
    parsed = 0
    for path in _iter_py_files(root, exclude):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"),
                             filename=str(path))
        except (SyntaxError, ValueError, OSError):
            continue
        parsed += 1
        mod = ".".join(path.relative_to(root).with_suffix("").parts)
        for node in tree.body:
            names: list[str] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.append(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.append(node.target.id)
            for name in names:
                bare.add(name)
                dotted.add(f"{mod}.{name}")
                # Also allow the trailing module segment: utils.helpers.train
                # matches a mention of `helpers.train`.
                parts = mod.split(".")
                for k in range(1, len(parts)):
                    dotted.add(".".join(parts[k:] + [name]))
    return bare, dotted, parsed


_GREP_PATTERNS = (
    r"\bdef\s+{name}\b",
    r"\bclass\s+{name}\b",
    r"\bfunction\s+{name}\b",
    r"\bconst\s+{name}\b",
    r"\blet\s+{name}\b",
    r"\bvar\s+{name}\b",
    r"\b{name}\s*=\s*function\b",
    r"\b{name}\s*=\s*\(",
)

_TEXT_EXTS = frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                        ".java", ".go", ".rs", ".rb", ".php", ".cs", ".swift",
                        ".kt", ".c", ".h", ".cpp", ".hpp", ".sh"})


def _grep_fallback(root: Path, name: str, exclude: tuple[str, ...]) -> bool:
    """True if any textual definition of ``name`` is found (non-Python repos)."""
    base = re.escape(name.split(".")[-1].rstrip("()"))
    patterns = [re.compile(p.format(name=base)) for p in _GREP_PATTERNS]
    skip = SKIP_DIRS | set(exclude)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in skip for part in rel_parts):
            continue
        if path.suffix.lower() not in _TEXT_EXTS:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(p.search(text) for p in patterns):
            return True
    return False


def run(ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    bare, dotted, parsed = _collect_python_defs(ctx.root, ctx.exclude)
    has_python = parsed > 0
    seen: set[tuple[str, int, str]] = set()

    for rel in ctx.docs:
        try:
            text = (ctx.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, raw in _iter_symbol_mentions(text):
            name = raw[:-2] if raw.endswith("()") else raw
            key = (str(rel), lineno, raw)
            if key in seen:
                continue
            seen.add(key)
            if "." in name:
                ok = name in dotted or name.split(".")[-1] in bare
            else:
                ok = name in bare
            if ok:
                continue
            if has_python:
                findings.append(Finding(
                    check="symbols",
                    verdict=Verdict.ERROR,
                    path=str(rel),
                    line=lineno,
                    message=f"phantom symbol: `{raw}` is not defined in the Python codebase",
                ))
            elif _grep_fallback(ctx.root, name, ctx.exclude):
                continue
            else:
                findings.append(Finding(
                    check="symbols",
                    verdict=Verdict.WARN,
                    path=str(rel),
                    line=lineno,
                    message=f"unverifiable symbol: `{raw}` (no Python source; textual search found nothing)",
                ))
    return findings
