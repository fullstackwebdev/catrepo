"""Importance ranking of source files for LLM-oriented dumps.

Python files are parsed with the stdlib ``ast`` module (a real AST).
TypeScript/JavaScript files use a lightweight lexical pass — a true TS AST
would need tree-sitter (a compiled native dependency); the lexical proxy
(decision keywords + function/class counts over string/comment-stripped
source) correlates well enough for ranking. Everything else (docs, data,
config) ranks last.

Tiers:
  0. entry points (``if __name__ == "__main__"`` guard or conventional
     entry filenames like main.py / cli.ts / server.js)
  1. source files reachable from entry points via imports
  2. source files not reachable from any entry point (dead or standalone)
  3. everything else (non-source, or Python that fails to parse)

Within a tier: higher complexity first, then higher in-degree (imported by
more files), then path for a deterministic total order.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# GUARDRAIL: complexity is a crude, EXPLICIT proxy — 1 per function + 1 per
# decision node, with the node set frozen here on purpose. If Python grows new
# control-flow nodes they must be added deliberately; never let ranking change
# silently when a new Python version ships new syntax.
_PY_DECISION_NODES = (
    ast.If, ast.For, ast.While, ast.Try, ast.With, ast.ExceptHandler,
    ast.IfExp, ast.Assert, ast.BoolOp, ast.ListComp, ast.SetComp,
    ast.DictComp, ast.GeneratorExp,
)

# GUARDRAIL: entry detection is a heuristic — a static dump has no runtime
# info, so "execution starts here" is inferred from a __main__ guard (Python)
# or a conventional entry filename. Adding names here only affects ranking
# order, never which content ends up in the dump.
PY_ENTRY_BASENAMES = frozenset({"__main__.py", "main.py", "cli.py", "app.py"})
TS_ENTRY_BASENAMES = frozenset({
    "main.ts", "main.js", "cli.ts", "cli.js",
    "app.ts", "app.js", "index.ts", "index.js",
    "server.ts", "server.js",
})

_TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

# GUARDRAIL: import regexes run on RAW source (paths live inside string
# literals, which the stripper removes) — a stray 'from "x"' inside a comment
# can add a spurious edge, but that only inflates in-degree slightly and never
# changes which files appear in the dump.
_IMPORT_FROM_RE = re.compile(
    r"\b(?:import|export)\b[^;'\"]*?\bfrom\s*['\"]([^'\"]+)['\"]", re.S
)
_IMPORT_BARE_RE = re.compile(r"(?<![\w.'\"/])import\s+['\"]([^'\"]+)['\"]")
_REQUIRE_RE = re.compile(r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)")

_DECISION_RES = (
    re.compile(r"\bif\s*\("),
    re.compile(r"\bfor\s*\("),
    re.compile(r"\bwhile\s*\("),
    re.compile(r"\bswitch\s*\("),
    re.compile(r"\bcatch\s*\("),
    re.compile(r"&&"),
    re.compile(r"\|\|"),
    re.compile(r"\?\?"),
    re.compile(r"\?\s"),
)


class _Metrics:
    __slots__ = ("complexity", "is_entry", "imports")

    def __init__(
        self, complexity: int = 0, is_entry: bool = False, imports: Optional[Set[str]] = None
    ) -> None:
        self.complexity = complexity
        self.is_entry = is_entry
        self.imports = imports if imports is not None else set()


# --------------------------------------------------------------------------- #
# Python: real AST pass
# --------------------------------------------------------------------------- #

def _has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        ):
            return True
    return False


def _py_complexity(tree: ast.Module) -> int:
    """1 per function/class + 1 per decision node, summed over the whole tree."""
    funcs = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    decisions = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, _PY_DECISION_NODES)
    )
    return funcs + decisions


def _py_imports(tree: ast.Module) -> Set[str]:
    """Module references as dotted strings ('catrepo.walker', '.api', '..x')."""
    mods: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
                # GUARDRAIL: 'from catrepo import renderer' can be a submodule,
                # not just catrepo/__init__ — probe module.alias too or the
                # graph misses the real dependency.
                for alias in node.names:
                    mods.add(f"{node.module}.{alias.name}")
            else:
                # 'from . import api' → node.module is None; rebuild it from level
                prefix = "." * node.level
                for alias in node.names:
                    mods.add(f"{prefix}{alias.name}")
    return mods


def _py_metrics(source: str, basename: str) -> _Metrics:
    # GUARDRAIL: ast.parse raises SyntaxError on broken source — the CALLER
    # handles it (warn + rank last). Never swallow parse errors here: a repo
    # with one bad file must not silently drop ranking of the rest.
    tree = ast.parse(source)
    return _Metrics(
        complexity=_py_complexity(tree),
        is_entry=_has_main_guard(tree) or basename in PY_ENTRY_BASENAMES,
        imports=_py_imports(tree),
    )


def _resolve_py(module: str, from_path: str, available: Set[str]) -> Optional[str]:
    """Resolve a Python import reference to a relative file path in *available*.

    Handles relative imports ('.api' → sibling, '..x' → parent package),
    package modules ('catrepo.walker' → catrepo/walker.py or __init__.py),
    and bare names next to the importer (scripts doing 'import walker').
    """
    stripped = module.lstrip(".")
    level = len(module) - len(stripped)
    parts = stripped.split(".")

    def candidates(base: List[str]) -> Optional[str]:
        full = base + parts
        for cut in range(len(full), 0, -1):
            head = "/".join(full[:cut])
            for tail in (".py", "/__init__.py"):
                cand = head + tail
                if cand in available:
                    return cand
        return None

    if level:
        base = list(Path(from_path).parent.parts)
        for _ in range(level - 1):
            if base:
                base.pop()
        return candidates(base)
    hit = candidates([])  # root-relative package path first
    if hit:
        return hit
    return candidates(list(Path(from_path).parent.parts))


# --------------------------------------------------------------------------- #
# TypeScript / JavaScript: lexical proxy
# --------------------------------------------------------------------------- #

def _strip_strings_and_comments(source: str) -> str:
    """Remove string/template literals and comments so keyword counts stay honest.

    A branch written inside a comment or string must not count as complexity.
    Rough state machine; template-literal ``${...}`` interpolation is skipped
    wholesale (acceptable for a ranking proxy).
    """
    out: List[str] = []
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        if c in "\"'`":
            i = _skip_quoted(source, i, c)
            out.append(" ")
            continue
        if c == "/" and i + 1 < n and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and source[i + 1] == "*":
            i += 2
            while i + 1 < n and not (source[i] == "*" and source[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _skip_quoted(source: str, i: int, quote: str) -> int:
    i += 1
    n = len(source)
    while i < n:
        c = source[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        i += 1
    return n


def _ts_complexity(code: str) -> int:
    funcs = (
        len(re.findall(r"\bfunction\b", code))
        + len(re.findall(r"=>", code))
        + len(re.findall(r"\bclass\b", code))
    )
    decisions = sum(len(rx.findall(code)) for rx in _DECISION_RES)
    return funcs + decisions


def _ts_imports(source: str) -> Set[str]:
    return (
        set(_IMPORT_FROM_RE.findall(source))
        | set(_IMPORT_BARE_RE.findall(source))
        | set(_REQUIRE_RE.findall(source))
    )


def _ts_metrics(source: str, basename: str) -> _Metrics:
    code = _strip_strings_and_comments(source)
    return _Metrics(
        complexity=_ts_complexity(code),
        # GUARDRAIL: JS entry idiom — 'require.main === module' is the runtime
        # signal that this file was executed directly, not required.
        is_entry=basename in TS_ENTRY_BASENAMES or "require.main" in code,
        imports=_ts_imports(source),
    )


def _resolve_ts(spec: str, from_path: str, available: Set[str]) -> Optional[str]:
    """Resolve a TS/JS import specifier ('./util', '../types') to a dumped file.

    Probes extension variants and index files; also matches a '.js' specifier
    to an existing '.ts' source (TS compiles imports to .js, so this is common).
    """
    if not (spec.startswith("./") or spec.startswith("../")):
        return None  # bare package import ('react', 'lodash') — not local
    cand = (Path(from_path).parent / spec).as_posix()
    probes: List[str] = []
    if cand.endswith(_TS_EXTS):
        probes.append(cand)
        stripped = re.sub(r"\.(ts|tsx|js|jsx|mjs|cjs)$", "", cand)
        for ext in _TS_EXTS:
            probes.append(stripped + ext)
    else:
        for ext in _TS_EXTS:
            probes.append(cand + ext)
            probes.append(cand + "/index" + ext)
    for probe in probes:
        if probe in available:
            return probe
    return None


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #

def rank_files(contents: Dict[str, str]) -> Dict[str, int]:
    """Rank *contents* (relative path → source) by importance; lower = dumped first.

    Returns a mapping covering EVERY input path, so callers can sort without
    special-casing unranked files.
    """
    complexity: Dict[str, int] = {}
    entry: Set[str] = set()
    refs: Dict[str, Set[str]] = {}

    for path, source in contents.items():
        if path.endswith(".py"):
            try:
                m = _py_metrics(source, Path(path).name)
            except SyntaxError:
                # GUARDRAIL: a syntax-broken file in a third-party repo is DATA,
                # not our bug — warn and rank it last instead of failing the whole
                # dump. Our own bugs must raise, but parse errors on user repos
                # must not be fatal (fail-first applies to OUR code, not theirs).
                print(
                    f"[catrepo] ast-rank: cannot parse {path} — ranked last",
                    file=sys.stderr,
                )
                continue
        elif path.endswith(_TS_SUFFIXES):
            m = _ts_metrics(source, Path(path).name)
        else:
            continue  # non-source: tier 3 via the set-difference below

        complexity[path] = m.complexity
        if m.is_entry:
            entry.add(path)
        refs[path] = m.imports

    available = set(contents)
    edges: Dict[str, Set[str]] = {p: set() for p in refs}
    for importer, mods in refs.items():
        resolve = _resolve_py if importer.endswith(".py") else _resolve_ts
        for ref in mods:
            dep = resolve(ref, importer, available)
            if dep in complexity:  # only source files we ranked participate
                edges[importer].add(dep)

    in_degree: Dict[str, int] = {p: 0 for p in complexity}
    for deps in edges.values():
        for dep in deps:
            in_degree[dep] += 1

    # BFS over import edges from every entry point: tier 1 = the dependency
    # closure the LLM needs to understand how the entry points work.
    reachable: Set[str] = set()
    seen = set(entry)
    queue = deque(entry)
    while queue:
        cur = queue.popleft()
        for dep in edges.get(cur, ()):
            if dep not in seen:
                seen.add(dep)
                reachable.add(dep)
                queue.append(dep)

    def key(path: str) -> Tuple[int, int, str]:
        # GUARDRAIL: complexity desc, then in-degree desc, then path — the path
        # tie-break is MANDATORY or output order becomes nondeterministic for
        # same-complexity files (dict iteration order is insertion order).
        return (-complexity[path], -in_degree.get(path, 0), path)

    tier0 = sorted(entry, key=key)
    tier1 = sorted(reachable - entry, key=key)
    tier2 = sorted(set(complexity) - entry - reachable, key=key)
    tier3 = sorted(set(contents) - set(complexity))

    return {p: i for i, p in enumerate(tier0 + tier1 + tier2 + tier3)}
