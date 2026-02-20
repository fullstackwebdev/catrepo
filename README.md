# Catrepo

Flatten a repository into one text dump with an optional tree view showing file structure and token counts.

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

- **Tree View**: Shows file structure at the top with token counts and/or file sizes
- **Gitignore Support**: Respects `.gitignore` patterns by default
- **Exclude Patterns**: Fixed to properly match directory names anywhere in the path
- **Multiple Formats**: Output as text, JSON, or HTML
- **Token Counting**: Approximate token counts for each file
- **Remote Repos**: Support for downloading and dumping remote GitHub/GitLab/Bitbucket repos

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
catrepo . --tree-depth 3 --tree-size --no-tree-tokens
catrepo . --tree-sort tokens --tree-dirs-first

# Gitignore
catrepo . --gitignore          # default
catrepo . --no-gitignore       # ignore .gitignore

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
--include TEXT             Glob(s) to include
--exclude TEXT             Glob(s) to exclude
--max-size INTEGER         Skip files larger than this many bytes
--max-tokens INTEGER       Hard cap; truncate largest files first
--format [text|json|html]  Output format
--binary-strict / --no-binary-strict  Strict binary detection
--gitignore / --no-gitignore  Respect .gitignore patterns (default: on)
--tree / --no-tree         Show tree view (default: on)
--tree-depth INTEGER       Maximum tree depth
--tree-tokens / --no-tree-tokens  Show token counts in tree (default: on)
--tree-size / --no-tree-size  Show file sizes in tree (default: off)
--tree-sort [name|size|tokens]  Sort order for tree (default: name)
--tree-dirs-first / --tree-files-first  Directories first in tree (default: dirs first)
--stdout / --no-stdout     Print to STDOUT
--outfile PATH             Write to file
--encoding TEXT            Output encoding (default: utf-8)
```

## License

MIT
