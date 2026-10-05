"""Tests for ctxverify. Fixture repos are built in tmp_path (planted rot)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ctxverify import cli
from ctxverify.checks import commands, dead_refs, manifest, staleness, symbols
from ctxverify.discovery import build_context, discover_docs
from ctxverify.findings import Verdict
from ctxverify.report import summarize

DAY = 86400


def make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def git_commit(repo: Path, relpaths: list[str], days_ago: int) -> None:
    ts = int(time.time()) - days_ago * DAY
    env = {**os.environ,
           "GIT_AUTHOR_DATE": str(ts), "GIT_COMMITTER_DATE": str(ts)}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "add"] + relpaths, cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=repo, check=True,
                   capture_output=True, env=env)


def ctx_for(repo: Path, docs_arg=None):
    return build_context(repo, docs_arg, [])


# ---------------------------------------------------------------- discovery

def test_discovery_finds_defaults(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "# c", "AGENTS.md": "# a", "README.md": "# r",
        "docs/guide.md": "# g", "other.md": "# o",
    })
    docs = discover_docs(tmp_path, None)
    names = {d.name for d in docs}
    assert {"CLAUDE.md", "AGENTS.md", "README.md", "guide.md"} <= names
    assert "other.md" not in names


def test_discovery_explicit_docs(tmp_path):
    make_repo(tmp_path, {"CLAUDE.md": "# c", "notes.md": "# n"})
    docs = discover_docs(tmp_path, ["notes.md"])
    assert [d.name for d in docs] == ["notes.md"]


# --------------------------------------------------------------- dead-refs

def test_dead_ref_detected(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "See `src/gone.py` for details.\n",
        "src/real.py": "x = 1\n",
    })
    findings = dead_refs.run(ctx_for(tmp_path))
    assert len(findings) == 1
    f = findings[0]
    assert f.verdict == Verdict.ERROR and f.check == "dead-refs"
    assert f.path == "CLAUDE.md" and f.line == 1
    assert "src/gone.py" in f.message


def test_dead_ref_markdown_link_and_existing_ok(tmp_path):
    make_repo(tmp_path, {
        "docs/a.md": "[real](../src/real.py) and [gone](missing.md)\n",
        "src/real.py": "x = 1\n",
    })
    findings = dead_refs.run(ctx_for(tmp_path))
    assert len(findings) == 1
    assert "missing.md" in findings[0].message


def test_url_ignored(tmp_path):
    make_repo(tmp_path, {
        "README.md": "[site](https://example.com/lib.py) and `https://x.io/a.py`\n",
    })
    assert dead_refs.run(ctx_for(tmp_path)) == []


# ----------------------------------------------------------------- symbols

def test_phantom_symbol_is_error(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "Call `frobnicate()` to start.\n",
        "engine.py": "def train():\n    pass\n",
    })
    findings = symbols.run(ctx_for(tmp_path))
    assert len(findings) == 1
    f = findings[0]
    assert f.verdict == Verdict.ERROR and "frobnicate" in f.message


def test_real_and_dotted_symbols_ok(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "Call `train()` or `engine.train` or `Trainer`.\n",
        "engine.py": "def train():\n    pass\n\nclass Trainer:\n    pass\n",
    })
    assert symbols.run(ctx_for(tmp_path)) == []


def test_unverifiable_symbol_is_warn_in_non_python_repo(tmp_path):
    make_repo(tmp_path, {
        "AGENTS.md": "Run `blorple()` first.\n",
        "app.js": "function start() {}\n",
    })
    findings = symbols.run(ctx_for(tmp_path))
    assert len(findings) == 1
    assert findings[0].verdict == Verdict.WARN
    assert "unverifiable" in findings[0].message


def test_grep_fallback_finds_js_definition(tmp_path):
    make_repo(tmp_path, {
        "AGENTS.md": "Run `start()` first.\n",
        "app.js": "function start() {}\n",
    })
    assert symbols.run(ctx_for(tmp_path)) == []


# --------------------------------------------------------------- staleness

def test_stale_reference_flagged(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "The auth flow lives in `src/auth.py`.\n",
        "src/auth.py": "# old\n",
    })
    git_commit(tmp_path, ["CLAUDE.md", "src/auth.py"], days_ago=200)
    findings = staleness.run(ctx_for(tmp_path), stale_days=180)
    assert len(findings) == 1
    assert findings[0].verdict == Verdict.WARN
    assert "src/auth.py" in findings[0].message
    assert "200" in findings[0].message or "days" in findings[0].message


def test_fresh_reference_not_flagged(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "The auth flow lives in `src/auth.py`.\n",
        "src/auth.py": "# new\n",
    })
    git_commit(tmp_path, ["CLAUDE.md", "src/auth.py"], days_ago=3)
    assert staleness.run(ctx_for(tmp_path), stale_days=180) == []


def test_staleness_skipped_without_git(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "See `src/auth.py`.\n",
        "src/auth.py": "# x\n",
    })
    assert staleness.run(ctx_for(tmp_path), stale_days=0) == []


# ---------------------------------------------------------------- manifest

def test_manifest_python_contradiction(tmp_path):
    make_repo(tmp_path, {
        "README.md": "Requires Python 3.12+.\n",
        "pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.10"\n',
    })
    findings = manifest.run(ctx_for(tmp_path))
    assert len(findings) == 1
    assert findings[0].verdict == Verdict.ERROR
    assert "Python 3.12" in findings[0].message


def test_manifest_python_ok(tmp_path):
    make_repo(tmp_path, {
        "README.md": "Requires Python 3.10+.\n",
        "pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.10"\n',
    })
    assert manifest.run(ctx_for(tmp_path)) == []


def test_manifest_db_contradiction(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "The app uses Postgres for storage.\n",
        "pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests"]\n',
    })
    findings = manifest.run(ctx_for(tmp_path))
    assert len(findings) == 1
    assert findings[0].verdict == Verdict.ERROR
    assert "Postgres" in findings[0].message


def test_manifest_db_ok(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "The app uses Postgres for storage.\n",
        "pyproject.toml": '[project]\nname = "x"\ndependencies = ["psycopg[binary]"]\n',
    })
    assert manifest.run(ctx_for(tmp_path)) == []


def test_manifest_docker_contradiction(tmp_path):
    make_repo(tmp_path, {
        "README.md": "The service uses Docker in production.\n",
        "package.json": '{"name": "x"}\n',
    })
    findings = manifest.run(ctx_for(tmp_path))
    assert any("Docker" in f.message for f in findings)


# ---------------------------------------------------------------- commands

def test_command_missing_path_is_error(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "```\npytest tests/\n```\n",
    })
    findings = commands.run(ctx_for(tmp_path))
    assert any(f.verdict == Verdict.ERROR and "tests/" in f.message
               for f in findings)


def test_command_ok(tmp_path, monkeypatch):
    make_repo(tmp_path, {
        "CLAUDE.md": "```\npytest tests/\n```\n",
        "tests/test_x.py": "x = 1\n",
    })
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pytest")
    assert commands.run(ctx_for(tmp_path)) == []


def test_command_missing_binary_is_warn(tmp_path, monkeypatch):
    make_repo(tmp_path, {
        "CLAUDE.md": "Run `pytest tests/`.\n",
        "tests/test_x.py": "x = 1\n",
    })
    monkeypatch.setattr("shutil.which", lambda _: None)
    findings = commands.run(ctx_for(tmp_path))
    assert any(f.verdict == Verdict.WARN and "PATH" in f.message
               for f in findings)


# --------------------------------------------------------------------- cli

def _full_rotten_repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path, {
        "CLAUDE.md": (
            "See `src/gone.py` for the old flow.\n"
            "Call `frobnicate()` to start.\n"
            "Requires Python 3.12+.\n"
            "The app uses Postgres for storage.\n"
            "```\npytest tests/\n```\n"
        ),
        "src/real.py": "def train():\n    pass\n",
        "pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.10"\n',
    })


def test_exit_code_2_on_errors(tmp_path):
    repo = _full_rotten_repo(tmp_path)
    assert cli.main([str(repo), "--stale-days", "99999"]) == 2


def test_exit_code_1_on_warnings_only(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "The auth flow lives in `src/auth.py`.\n",
        "src/auth.py": "# old\n",
    })
    git_commit(tmp_path, ["CLAUDE.md", "src/auth.py"], days_ago=200)
    assert cli.main([str(tmp_path)]) == 1


def test_exit_code_0_when_clean(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "See `src/real.py`. Call `train()`.\n",
        "src/real.py": "def train():\n    pass\n",
    })
    assert cli.main([str(tmp_path), "--stale-days", "99999"]) == 0


def test_json_output(tmp_path, capsys):
    repo = _full_rotten_repo(tmp_path)
    assert cli.main([str(repo), "--json", "--stale-days", "99999"]) == 2
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "findings" in data and "summary" in data
    assert data["summary"]["errors"] >= 4
    assert data["summary"]["verdict"] == "FAIL"


def test_markdown_report(tmp_path):
    repo = _full_rotten_repo(tmp_path)
    report = tmp_path / "out.md"
    assert cli.main([str(repo), "--report", str(report),
                     "--stale-days", "99999"]) == 2
    text = report.read_text(encoding="utf-8")
    assert text.startswith("# ctxverify report")
    assert "| dead-refs |" in text


def test_no_docs_message(tmp_path, capsys):
    make_repo(tmp_path, {"src/real.py": "x = 1\n"})
    assert cli.main([str(tmp_path)]) == 0
    assert "no agent-facing docs found" in capsys.readouterr().err


# ---------------------------------------------------------- ignore marker

def test_ignore_marker_skips_dead_ref(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "See `src/gone.py`. <!-- ctxverify: ignore -->\n",
    })
    assert dead_refs.run(ctx_for(tmp_path)) == []


def test_ignore_marker_skips_symbol_and_manifest(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": (
            "Call `frobnicate()`. <!-- ctxverify: ignore -->\n"
            "Requires Python 3.12+. <!-- ctxverify: ignore -->\n"
        ),
        "engine.py": "def train():\n    pass\n",
        "pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.10"\n',
    })
    assert symbols.run(ctx_for(tmp_path)) == []
    assert manifest.run(ctx_for(tmp_path)) == []


def test_ignore_marker_skips_command(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "```\npytest tests/ <!-- ctxverify: ignore -->\n```\n",
    })
    assert commands.run(ctx_for(tmp_path)) == []


def test_glob_patterns_not_flagged(tmp_path):
    make_repo(tmp_path, {
        "CLAUDE.md": "Checkpoints land in `checkpoints/ckpt_*.pt`.\n",
    })
    assert dead_refs.run(ctx_for(tmp_path)) == []


def test_keyboard_shortcut_and_remote_refs_not_paths(tmp_path):
    make_repo(tmp_path, {
        "README.md": (
            "Press `j/k` then `Enter`.\n"
            "See also `gensecaihq/wazuh-autopilot`.\n"
            "And `wazuh/integrations/wazuh_decoder_rule_tool`.\n"
        ),
    })
    assert dead_refs.run(ctx_for(tmp_path)) == []


def test_dotted_dir_still_checked(tmp_path):
    make_repo(tmp_path, {
        "README.md": "CI lives in `.github/workflows`.\n",
    })
    findings = dead_refs.run(ctx_for(tmp_path))
    assert len(findings) == 1
    assert ".github/workflows" in findings[0].message
