# Catrepo

Flatten a repository into one text dump with a tree view showing file structure and token counts.

## Example

```bash
catrepo . --exclude node_modules
```

Output:

```
# Catrepo dump – my-project – 2026-02-20T23:22:13.772781+00:00
# ≈ 100681 tokens

## File Structure

└── .
    ├── src
    │   ├── utils.ts (1.2K tok)
    │   ├── main.ts (3.5K tok)
    │   └── types.ts (890 tok)
    ├── tests
    │   └── main.test.ts (1.1K tok)
    ├── package.json (150 tok)
    └── README.md (500 tok)

2 directories, 6 files

### src/utils.ts
export function hello() { ... }

### src/main.ts
import { hello } from './utils';
...
```

## Features

- **Tree View**: Always-on file structure at the top with token counts and optional file sizes
- **Gitignore Support**: Respects `.gitignore` from the repo root *and* nested directories, with subtree pruning so ignored trees (e.g. `node_modules`) are never walked
- **Pareto Filter**: Opt-in (`--max-token-size N`, off by default); when enabled, excludes generated/noise files (lockfiles, changelogs, minified bundles, `.csv`/`.tsv`) whose token count exceeds N × the median — real source files are never removed
- **Contents Ordering**: File contents are listed newest-edited first (mtime, with a path tie-break) so recent work appears together; `--contents-sort path` gives deterministic alphabetical order
- **Multiple Formats**: Output as text, JSON, or HTML
- **Token Counting**: Approximate token counts for each file
- **Remote Repos**: Download and dump remote GitHub/GitLab/Bitbucket repos

## Installation

```bash
pip install -e .
```

Or install globally:

```bash
pip install .
```

## Usage

```bash
# Basic usage
catrepo .

# Exclude directories
catrepo . --exclude node_modules --exclude dist

# Tree options
catrepo . --tree-depth 3 --tree-size --tree-sort tokens --tree-dirs-first

# Contents order (default is newest-edited first)
catrepo . --contents-sort path   # alphabetical instead

# Opt-in noise filter (off by default): drop generated files over N × median tokens
catrepo . --max-token-size 20

# Hard token cap (truncates largest files first)
catrepo . --max-tokens 50000

# Output formats
catrepo . --format text
catrepo . --format json
catrepo . --format html

# Output to file
catrepo . --outfile dump.txt

# Remote repository
catrepo --remote-url https://github.com/user/repo
```

## Options

```
--remote-url TEXT          Git repo URL to download
--private-token TEXT       Token for private repos
--include TEXT             Glob(s) to include; trailing '/' expands recursively
--exclude TEXT             Glob(s) to exclude; '.git/' is excluded by default
--max-size INTEGER         Skip files larger than this many bytes
--max-tokens INTEGER       Hard cap; truncate largest files first
--max-token-size FLOAT     Opt-in filter (0 = off, default): drop generated/noise files over N × median tokens
--format [text|json|html]  Output format
--binary-strict / --no-binary-strict  Strict binary detection
--tree-depth INTEGER       Maximum tree depth
--tree-size / --no-tree-size  Show file sizes in tree (default: off)
--tree-sort [name|size|tokens]  Sort order for tree (default: name)
--tree-dirs-first / --tree-files-first  Directories first in tree (default: dirs first)
--contents-sort [mtime|path]   Order file contents: newest-first (default) or alphabetical
--stdout / --no-stdout     Print to STDOUT
--outfile PATH             Write to file
--encoding TEXT            Output encoding (default: utf-8)
```

Gitignore handling is always on and cannot be disabled: skipping it leaks build
artifacts (`dist/`, `.next/`, `__pycache__/`) into the dump.

## License

MIT
