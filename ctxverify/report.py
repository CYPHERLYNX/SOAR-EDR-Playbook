"""Report rendering: human-readable text, JSON, and Markdown."""

from __future__ import annotations

import json

from .findings import Finding, Verdict

CHECK_ORDER = ("dead-refs", "symbols", "staleness", "manifest", "commands")


def summarize(findings: list[Finding]) -> dict:
    errors = sum(1 for f in findings if f.verdict == Verdict.ERROR)
    warns = sum(1 for f in findings if f.verdict == Verdict.WARN)
    return {
        "errors": errors,
        "warnings": warns,
        "total": len(findings),
        "verdict": "FAIL" if errors else ("WARN" if warns else "PASS"),
    }


def render_text(findings: list[Finding], root_name: str) -> str:
    summary = summarize(findings)
    lines = [f"ctxverify: {root_name}", ""]
    if not findings:
        lines.append("No discrepancies found. Docs match the code.")
    else:
        ordered = sorted(findings,
                         key=lambda f: (CHECK_ORDER.index(f.check)
                                        if f.check in CHECK_ORDER else 99,
                                        f.path, f.line))
        current_check = None
        for f in ordered:
            if f.check != current_check:
                current_check = f.check
                lines.append(f"[{current_check}]")
            lines.append(f"  {f.path}:{f.line} [{f.verdict}] {f.message}")
        lines.append("")
    lines.append(f"Summary: {summary['errors']} errors, "
                 f"{summary['warnings']} warnings -> {summary['verdict']}")
    return "\n".join(lines)


def render_json(findings: list[Finding]) -> str:
    return json.dumps(
        {"findings": [f.to_dict() for f in findings], "summary": summarize(findings)},
        indent=2,
    )


def render_markdown(findings: list[Finding], root_name: str) -> str:
    summary = summarize(findings)
    lines = [f"# ctxverify report: {root_name}", "",
             f"**{summary['errors']} errors, {summary['warnings']} warnings "
             f"-> {summary['verdict']}**", ""]
    if findings:
        lines += ["| Check | Location | Verdict | Finding |",
                  "|---|---|---|---|"]
        ordered = sorted(findings,
                         key=lambda f: (CHECK_ORDER.index(f.check)
                                        if f.check in CHECK_ORDER else 99,
                                        f.path, f.line))
        for f in ordered:
            msg = f.message.replace("|", "\\|")
            lines.append(f"| {f.check} | {f.path}:{f.line} | {f.verdict} | {msg} |")
    else:
        lines.append("No discrepancies found. Docs match the code.")
    return "\n".join(lines) + "\n"
