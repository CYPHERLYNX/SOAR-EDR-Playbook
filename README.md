# ctxverify

**Your AI coding agent reads your docs. ctxverify checks whether they're lying.**

`CLAUDE.md`, `AGENTS.md`, and `docs/` are the instruction set your agent boots from — but they rot. They reference deleted files, phantom functions, and architectures refactored months ago, so every agent run starts from confidently wrong premises. ctxverify is a deterministic, dependency-free CLI that cross-checks agent-facing docs against the actual codebase and fails CI when docs lie. No LLM, no API key. <!-- ctxverify: ignore -->

## The five checks

| Check | What it does | Verdict |
|---|---|---|
| `dead-refs` | Extracts file paths from docs (markdown links, `` `backticked` `` paths, quoted paths) and verifies each exists | ERROR | <!-- ctxverify: ignore -->
| `symbols` | Extracts `` `function()` `` / `` `ClassName` `` / `` `module.symbol` `` mentions; verifies via AST over Python source, grep fallback otherwise | ERROR if confirmed missing in Python; WARN if unverifiable |
| `staleness` | `git log` recency for referenced files; flags files untouched longer than `--stale-days` (default 180) | WARN |
| `manifest` | Compares explicit claims ("requires Python 3.12", "uses Postgres", "uses Docker") against `pyproject.toml` / `package.json` / `requirements*.txt` | ERROR | <!-- ctxverify: ignore -->
| `commands` | Extracts commands from docs (`pytest tests/`, `` `npm test` ``); verifies referenced paths exist and runner binaries are on PATH | ERROR for missing paths; WARN for missing binaries |

## Installation

```bash
pip install ctxverify
# or run from source:
python3 -m ctxverify
```

Requires Python 3.10+. Standard library only — zero dependencies.

## Usage

```bash
# Scan the current repo
ctxverify

# Scan another repo, custom docs, JSON output
ctxverify /path/to/repo --docs CLAUDE.md docs/ --json

# Write a Markdown report (CI artifacts)
ctxverify --report ctxverify-report.md
```

Exit codes are CI-gatable: `0` clean, `1` warnings only, `2` errors.

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--docs PATH...` | `CLAUDE.md AGENTS.md README.md docs/ .claude/` | Doc files, dirs, or globs to check |
| `--exclude DIR...` | — | Extra dir names to skip in code scans |
| `--stale-days N` | `180` | Staleness threshold in days |
| `--json` | — | Print findings as JSON |
| `--report FILE` | — | Write a Markdown report to FILE |

### CI example (GitHub Actions)

```yaml
- name: Verify agent docs
  run: |
    pip install ctxverify
    ctxverify --stale-days 180
```

## Example output

``` <!-- ctxverify: ignore -->
ctxverify: myrepo <!-- ctxverify: ignore -->
 <!-- ctxverify: ignore -->
[dead-refs] <!-- ctxverify: ignore -->
  CLAUDE.md:12 [ERROR] dead file reference: `src/legacy/auth.py` does not exist <!-- ctxverify: ignore -->
[symbols] <!-- ctxverify: ignore -->
  CLAUDE.md:18 [ERROR] phantom symbol: `migrate_all()` is not defined in the Python codebase <!-- ctxverify: ignore -->
[staleness] <!-- ctxverify: ignore -->
  CLAUDE.md:24 [WARN] stale reference: `src/billing.py` untouched for 214 days (threshold 180) <!-- ctxverify: ignore -->
[manifest] <!-- ctxverify: ignore -->
  README.md:6 [ERROR] contradiction: docs require Python 3.12+ but pyproject allows >=3.10 <!-- ctxverify: ignore -->
 <!-- ctxverify: ignore -->
Summary: 3 errors, 1 warnings -> FAIL <!-- ctxverify: ignore -->
```

## Ignoring lines

Docs about tooling (like this README) legitimately mention files and symbols
that don't exist in the repo. Add `<!-- ctxverify: ignore -->` anywhere on a
line to skip all checks for that line:

```markdown
See `src/legacy/auth.py` for the historical design. <!-- ctxverify: ignore -->
```

## Limitations (honest)

- **Symbol extraction is heuristic for non-Python code.** Python repos get full AST verification; other languages fall back to textual search (`def name`, `class name`, ...), and unfound symbols are reported as WARN/unverifiable rather than missing — the tool will not claim a symbol is phantom when it cannot prove it.
- **Manifest claims must be explicit.** The tool matches patterns like "requires Python 3.12" or "uses Postgres"; vague prose ("we like new Pythons") is ignored rather than guessed at. <!-- ctxverify: ignore -->
- **Staleness needs git history** and uses the last-commit date of referenced files — a stable, finished file can look "stale" even when the docs are accurate. Treat STALE as a nudge to re-read, not proof of rot.
- Path extraction is conservative: only markdown links, backticked, and quoted paths are considered, so some mentions will be missed rather than misreported. <!-- ctxverify: ignore -->

## Why not an LLM?

An LLM re-reading your docs can absolutely find rot — but it costs tokens on every CI run, needs an API key in your pipeline, and is non-deterministic. ctxverify is the cheap deterministic gate: run it on every PR, and save the LLM for judgment calls.

## License

MIT — see [LICENSE](LICENSE).
