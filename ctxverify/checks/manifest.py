"""Check 4: manifest contradictions.

Compares explicit claims in docs against packaging manifests:

* "requires Python X.Y[+]" vs ``pyproject.toml`` ``requires-python``
* "requires Node X[+]" vs ``package.json`` ``engines.node``
* "uses Postgres/MySQL/Redis/MongoDB/..." vs declared dependencies
* "uses Docker" vs the presence of a Dockerfile

Contradictions are ERROR; claims that cannot be checked (no manifest at
all) are skipped silently.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..findings import Finding, ScanContext, Verdict
from ..paths import is_ignored

PY_REQ_RE = re.compile(
    r"[Rr]equires?\s+Python\s+([0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)\s*\+?")
NODE_REQ_RE = re.compile(
    r"[Rr]equires?\s+Node(?:\.js)?\s+([0-9]+(?:\.[0-9]+)?)\s*\+?")
USES_DB_RE = re.compile(
    r"\buses?\s+(PostgreSQL|Postgres|MySQL|MariaDB|Redis|MongoDB|SQLite|Elasticsearch)\b")
USES_DOCKER_RE = re.compile(r"\buses?\s+Docker\b")

# dependency name fragments that satisfy a "uses X" claim
DB_DEP_MAP = {
    "postgresql": ("psycopg", "asyncpg", "psycopg2", "sqlalchemy", "databases"),
    "postgres": ("psycopg", "asyncpg", "psycopg2", "sqlalchemy", "databases"),
    "mysql": ("pymysql", "mysql-connector", "aiomysql", "sqlalchemy"),
    "mariadb": ("pymysql", "mysql-connector", "aiomysql", "sqlalchemy"),
    "redis": ("redis", "aioredis", "fakeredis"),
    "mongodb": ("pymongo", "motor", "mongoengine", "beanie"),
    "sqlite": ("sqlite", "aiosqlite"),  # stdlib sqlite3 often undeclared; see below
    "elasticsearch": ("elasticsearch",),
}


def _load_pyproject(root: Path) -> dict:
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        import tomllib
        return tomllib.loads(text).get("project", {})
    except ImportError:
        pass
    except ValueError:
        return {}
    # Python 3.10 fallback: regex-extract requires-python only.
    m = re.search(r"requires-python\s*=\s*[\"']([^\"']+)[\"']", text)
    deps = re.findall(r"^\s*[\"']([A-Za-z0-9_.\-]+)", text, re.M)
    return {"requires-python": m.group(1) if m else None,
            "dependencies": deps}


def _load_package_json(root: Path) -> dict:
    path = root / "package.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        return {}


def _load_requirements(root: Path) -> list[str]:
    names: list[str] = []
    for path in root.glob("requirements*.txt"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-")):
                continue
            m = re.match(r"([A-Za-z0-9_.\-]+)", line)
            if m:
                names.append(m.group(1).lower())
    return names


def _min_version(spec: str | None) -> tuple[int, ...] | None:
    if not spec:
        return None
    m = re.search(r"(\d+(?:\.\d+)*)", spec)
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split("."))


def _all_dep_names(root: Path, pyproject: dict, package_json: dict) -> set[str]:
    names: set[str] = set()
    for dep in pyproject.get("dependencies") or []:
        m = re.match(r"([A-Za-z0-9_.\-]+)", str(dep))
        if m:
            names.add(m.group(1).lower().replace("_", "-"))
    for section in ("dependencies", "devDependencies",
                    "peerDependencies", "optionalDependencies"):
        for dep in (package_json.get(section) or {}):
            names.add(str(dep).lower())
    names.update(_load_requirements(root))
    return names


def run(ctx: ScanContext) -> list[Finding]:
    findings: list[Finding] = []
    root = ctx.root
    pyproject = _load_pyproject(root)
    package_json = _load_package_json(root)
    if not pyproject and not package_json:
        return findings  # nothing to check against
    dep_names = _all_dep_names(root, pyproject, package_json)
    has_dockerfile = (root / "Dockerfile").is_file() or (root / "docker-compose.yml").is_file() \
        or (root / "docker-compose.yaml").is_file()

    for rel in ctx.docs:
        try:
            lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, start=1):
            if is_ignored(line):
                continue
            m = PY_REQ_RE.search(line)
            if m and pyproject.get("requires-python"):
                doc_min = _min_version(m.group(1))
                man_min = _min_version(str(pyproject["requires-python"]))
                if doc_min and man_min and doc_min > man_min:
                    findings.append(Finding(
                        check="manifest", verdict=Verdict.ERROR, path=str(rel), line=i,
                        message=f"contradiction: docs require Python {m.group(1)}+ but "
                                f"pyproject allows {pyproject['requires-python']}",
                    ))
            m = NODE_REQ_RE.search(line)
            if m:
                engines = (package_json.get("engines") or {}).get("node")
                doc_min = _min_version(m.group(1))
                man_min = _min_version(str(engines)) if engines else None
                if doc_min and man_min and doc_min > man_min:
                    findings.append(Finding(
                        check="manifest", verdict=Verdict.ERROR, path=str(rel), line=i,
                        message=f"contradiction: docs require Node {m.group(1)}+ but "
                                f"package.json engines allow {engines}",
                    ))
            for dbm in USES_DB_RE.finditer(line):
                db = dbm.group(1).lower()
                if db == "sqlite":
                    continue  # stdlib; absence from manifests proves nothing
                frags = DB_DEP_MAP.get(db, ())
                if frags and not any(
                        f in dep for dep in dep_names for f in frags):
                    findings.append(Finding(
                        check="manifest", verdict=Verdict.ERROR, path=str(rel), line=i,
                        message=f"contradiction: docs say the project uses "
                                f"{dbm.group(1)} but no matching driver is declared "
                                f"in any manifest",
                    ))
            if USES_DOCKER_RE.search(line) and not has_dockerfile:
                findings.append(Finding(
                    check="manifest", verdict=Verdict.ERROR, path=str(rel), line=i,
                    message="contradiction: docs say the project uses Docker "
                            "but no Dockerfile or docker-compose file exists",
                ))
    return findings
