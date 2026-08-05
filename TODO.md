# TODO — Tree-sitter backend for importance ranking

**Context**: `analyzer.py` ranks files for LLM context (tier 0 entry → tier 1
reachable via imports → tier 2 unreachable → tier 3 non-source; within tier:
complexity desc, in-degree desc, path). Today Python = real AST (`ast` stdlib),
TS/JS = lexical proxy, **everything else ranks last with zero analysis**. This
list upgrades the parser layer to tree-sitter so any grammar language gets real
AST analysis — the ranking model stays exactly as-is (language-agnostic).

## Phase 0 — decisions & prerequisites (do first)

- [ ] Decide the license (LICENSE says TBD). **Blocks publishing**, not dev.
      GUARDRAIL: do not add a `license` field/classifier to pyproject until
      decided — it was removed deliberately to avoid claiming MIT.
- [ ] Decide if `--contents-sort ast` becomes the default. Currently `mtime`
      (parity constraint). Flip only with explicit approval.
- [ ] Pick the dependency strategy:
      - A: `tree-sitter` + `tree-sitter-language-pack` (one wheel, ~100 grammars)
      - B: `tree-sitter` + individual `tree-sitter-<lang>` wheels (smaller, per-lang)
      Either way it MUST be an optional extra (`catrepo[ts]`), never a hard dep —
      the zero-dependency path (Python ast + lexical proxy) stays the fallback.

## Phase 1 — parser plumbing (no ranking changes)

- [ ] Add `[project.optional-dependencies] ts = [...]` to pyproject.toml.
- [ ] New `parser.py` module: a thin `parse(path, source) -> Optional[Tree] | None`
      registry. Dispatch: `.py` → stdlib `ast` (unchanged, no native dep on the
      common path); `.ts/.tsx/.js/.jsx/.mjs/.cjs` → tree-sitter typescript/js
      grammars (replaces the lexical proxy); other supported extensions → their
      grammar; unsupported → `None` (tier 3, current behavior).
      GUARDRAIL: Python must stay stdlib `ast` — tree-sitter on Python buys
      nothing and adds a native dep to the most common path. Feature-parity bar:
      `--contents-sort ast` output for py/ts fixtures must be byte-identical
      before/after (timestamp-normalized diff, same as past parity checks).
- [ ] If `tree-sitter` is missing at runtime: degrade gracefully — warn once to
      stderr (`[catrepo] ts-parse: tree-sitter not installed, install with
      pip install 'catrepo[ts]'`) and fall back to the lexical proxy / tier 3.
      GUARDRAIL: fail-first is for OUR bugs — a missing optional dep is a user
      config choice, not an error; but never silently pretend a file was parsed.
- [ ] Wire `analyzer.rank_files` to the parser registry. Metrics shape stays
      `(complexity, is_entry, imports)` — no callers change.

## Phase 2 — per-language extraction tables

For each grammar added, three mappings (live in per-language dicts, NOT
if/elif sprawl — a registry keyed by extension):

- [ ] **Entry detection**:
      Python: `__main__` guard / entry basenames (exists).
      TS/JS: `require.main` / entry basenames (exists).
      Go: `func main()` in `package main`. Rust: `fn main()`. C/C++: `int main(`
      or `void main(`. Java: `public static void main`. Ruby: `$0 == __FILE__`.
      Generic fallback: basename heuristics (main/app/cli/server).
      GUARDRAIL: entry detection is a heuristic — document every rule in one
      table; a wrong guess only reorders the dump, never drops content.
- [ ] **Complexity**: per-language decision node-kind sets. tree-sitter exposes
      node type strings per grammar (e.g. TS `if_statement`, Go `if_stmt`,
      Rust `if_expr`). Table: node-type → +1. Keep the frozen, explicit pattern
      from `_PY_DECISION_NODES`; adding a grammar must be a table entry, not a
      code change.
      GUARDRAIL: never count tokens from raw source for a tree-sitter language —
      the whole point of the parser is that strings/comments are excluded by the
      tree. The lexical stripper stays only as the no-deps fallback.
- [ ] **Imports**: per-ecosystem resolution:
      Python: dotted modules + relative (exists).
      TS/JS: path specifiers + extension probing (exists).
      Go: `import "path"` → GOPATH-less resolution relative to module root —
      start with simple relative-to-root, accept misses.
      Rust: `use crate::a::b` / `mod a;` → path mapping.
      C/C++: `#include "local.h"` (relative) vs `<sysdep.h>` (skip).
      Java: `package`/`import` → classpath-less heuristic (package dirs).
      Keep the existing rule: edges only resolve to files present in the dump;
      unresolved references are ignored (they can't inflate anything real).

## Phase 3 — tests (one fixture repo per language)

- [ ] Fixtures under `tests/` (never /tmp) with: entry file, reachable complex
      module, reachable simple module, unreachable file, non-source file.
      Assert the same tier order as the py/ts tests.
- [ ] Golden tests: `--contents-sort ast` output identical with and without the
      `ts` extra installed (fallback path unchanged).
- [ ] Parse-error tests: broken file → stderr warning + tier 3, dump succeeds
      (mirror of the existing SyntaxError test).
- [ ] Determinism: same fixture, twice, byte-identical output (path tie-break).

## Phase 4 — packaging & release

- [ ] Rebuild wheel, verify the optional extra metadata
      (`pip install 'catrepo[ts]'` in a fresh venv, and `pip install catrepo`
      WITHOUT extras still works and still parses Python/TS via fallbacks).
- [ ] README: document `catrepo[ts]`, the supported-language table, and the
      fallback behavior.
- [ ] Bump `__version__` (single source, `__init__.py`).
- [ ] Publish: `twine upload dist/*` after the license decision (Phase 0).

## Nice-to-haves (later)

- [ ] Per-file "why this rank" debug output (`--contents-sort ast --verbose`
      printing tier, complexity, in-degree per file to stderr).
- [ ] Max-parse budget: cap total parsed bytes per run so a pathological repo
      can't stall the dump (warn when the budget is hit).
- [ ] Cache parsed trees keyed by (path, size, mtime) across `render_repo` calls
      in the same process (API users dumping many repos).
