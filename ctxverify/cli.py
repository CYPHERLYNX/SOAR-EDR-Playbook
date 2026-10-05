"""ctxverify CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .checks import commands, dead_refs, manifest, staleness, symbols
from .discovery import build_context
from .findings import Verdict
from .report import render_json, render_markdown, render_text, summarize


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ctxverify",
        description="Verify agent-facing docs (CLAUDE.md, AGENTS.md, docs/) "
                    "against the actual codebase.",
    )
    p.add_argument("root", nargs="?", default=".",
                   help="repo root to scan (default: current directory)")
    p.add_argument("--docs", nargs="+", default=None, metavar="PATH",
                   help="doc files/dirs/globs to check (default: CLAUDE.md, "
                        "AGENTS.md, README.md, docs/, .claude/)")
    p.add_argument("--exclude", nargs="+", default=[], metavar="DIR",
                   help="extra directory names to exclude from code scans")
    p.add_argument("--stale-days", type=int, default=180, metavar="N",
                   help="flag referenced files untouched longer than N days "
                        "(default: 180)")
    p.add_argument("--json", action="store_true",
                   help="print findings as JSON")
    p.add_argument("--report", metavar="FILE",
                   help="write a Markdown report to FILE")
    p.add_argument("--no-color", action="store_true",
                   help="disable ANSI colors (currently plain output)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def run_scan(root: Path, docs, exclude, stale_days):
    ctx = build_context(root, docs, exclude)
    findings = []
    findings += dead_refs.run(ctx)
    findings += symbols.run(ctx)
    findings += staleness.run(ctx, stale_days=stale_days)
    findings += manifest.run(ctx)
    findings += commands.run(ctx)
    return ctx, findings


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"ctxverify: not a directory: {root}", file=sys.stderr)
        return 2

    ctx, findings = run_scan(root, args.docs, args.exclude, args.stale_days)
    summary = summarize(findings)

    if not ctx.docs:
        print("ctxverify: no agent-facing docs found "
              "(looked for CLAUDE.md, AGENTS.md, README.md, docs/, .claude/); "
              "use --docs to specify files.", file=sys.stderr)

    if args.json:
        print(render_json(findings))
    else:
        print(render_text(findings, ctx.root.name))

    if args.report:
        Path(args.report).write_text(
            render_markdown(findings, ctx.root.name), encoding="utf-8")
        print(f"ctxverify: markdown report written to {args.report}")

    if summary["errors"]:
        return 2
    if summary["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
