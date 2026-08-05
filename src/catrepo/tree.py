"""Tree view generator for catrepo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .walker import FileInfo


@dataclass
class TreeNode:
    """A node in the tree structure."""
    
    name: str
    path: Path
    is_dir: bool
    size: int = 0
    tokens: int = 0
    children: List['TreeNode'] = None
    
    def __post_init__(self):
        if self.children is None:
            self.children = []


def _format_size(size: int) -> str:
    """Format size in human-readable format."""
    if size < 1024:
        return f"{size}"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}K"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}M"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f}G"


def _format_tokens(tokens: int) -> str:
    """Format token count in human-readable format."""
    if tokens < 1000:
        return f"{tokens}"
    elif tokens < 1000 * 1000:
        return f"{tokens / 1000:.1f}K"
    elif tokens < 1000 * 1000 * 1000:
        return f"{tokens / (1000 * 1000):.1f}M"
    else:
        return f"{tokens / (1000 * 1000 * 1000):.1f}B"


def build_tree(
    files: List[FileInfo],
    root: Path,
    max_depth: Optional[int] = None,
    sort_by: str = "name",
    dirs_first: bool = True,
) -> TreeNode:
    """Build a tree structure from a list of files.
    
    Parameters
    ----------
    files:
        List of file info objects.
    root:
        Root directory of the tree.
    max_depth:
        Maximum depth to display (None for unlimited).
    sort_by:
        Sort criterion: "name", "size", "tokens".
    dirs_first:
        If True, list directories before files.
    
    Returns
    -------
    TreeNode:
        Root node of the tree structure.
    """
    # GUARDRAIL: the old build recursed per file and linearly scanned each level's
    # children to find the parent dir — O(files × depth × siblings). A path→node
    # dict gives O(files × depth) with byte-identical output; node.path stays
    # informational (rendering only uses name/size/tokens).
    root_node = TreeNode(
        name=root.name or str(root),
        path=root,
        is_dir=True,
    )
    dirs_by_path: Dict[Path, TreeNode] = {Path(): root_node}

    # Build tree structure
    for f in files:
        node = root_node
        rel = Path()
        for i, part in enumerate(f.path.parts):
            rel = rel / part
            is_file = i == len(f.path.parts) - 1
            if is_file:
                node.children.append(
                    TreeNode(
                        name=part,
                        path=rel,
                        is_dir=False,
                        size=f.size,
                        tokens=f.size // 4,  # Approximate — keep for parity
                    )
                )
            else:
                child = dirs_by_path.get(rel)
                if child is None:
                    child = TreeNode(
                        name=part,
                        path=rel,
                        is_dir=True,
                    )
                    dirs_by_path[rel] = child
                    node.children.append(child)
                node = child

    # Calculate directory sizes and tokens
    def calc_size(node: TreeNode) -> Tuple[int, int]:
        """Calculate total size and tokens for a directory."""
        if not node.is_dir:
            return node.size, node.tokens
        
        total_size = 0
        total_tokens = 0
        for child in node.children:
            s, t = calc_size(child)
            total_size += s
            total_tokens += t
        node.size = total_size
        node.tokens = total_tokens
        return total_size, total_tokens
    
    calc_size(root_node)
    
    # Sort children
    def sort_key(node: TreeNode):
        if sort_by == "size":
            return -node.size
        elif sort_by == "tokens":
            return -node.tokens
        else:  # name
            return node.name.lower()
    
    def sort_children(node: TreeNode):
        """Recursively sort children."""
        if dirs_first:
            dirs = [c for c in node.children if c.is_dir]
            files_list = [c for c in node.children if not c.is_dir]
            dirs.sort(key=sort_key)
            files_list.sort(key=sort_key)
            node.children = dirs + files_list
        else:
            node.children.sort(key=sort_key)
        
        for child in node.children:
            if child.is_dir:
                sort_children(child)
    
    sort_children(root_node)
    
    # Apply max depth
    if max_depth is not None:
        def trim_depth(node: TreeNode, depth: int):
            """Remove children beyond max depth."""
            if depth >= max_depth:
                node.children = []
            else:
                for child in node.children:
                    if child.is_dir:
                        trim_depth(child, depth + 1)
        
        trim_depth(root_node, 0)
    
    return root_node


def render_tree(
    root: TreeNode,
    prefix: str = "",
    is_last: bool = True,
    show_size: bool = False,
) -> List[str]:
    """Render a tree node to lines of text.
    
    Parameters
    ----------
    root:
        Root node to render.
    prefix:
        Current prefix string for indentation.
    is_last:
        Whether this is the last child.
    show_size:
        Whether to show file sizes.
    
    Returns
    -------
    List[str]:
        Lines of the tree representation.
    """
    lines = []
    
    # Connector
    connector = "└── " if is_last else "├── "
    
    # Build the line
    line_parts = [prefix + connector]
    
    # GUARDRAIL: the old code had two IDENTICAL if/elif size branches (one for dir,
    # one for file) — collapsed to one `if show_size`. Tree output is byte-identical.
    if show_size:
        line_parts.append(f"[{_format_size(root.size):>10}] ")
    
    # Name
    line_parts.append(root.name)
    
    # Token info for files (always shown — the --tree-tokens flag was removed;
    # GUARDRAIL: show_tokens param dropped, it was always True from the only caller)
    if not root.is_dir:
        line_parts.append(f" ({_format_tokens(root.tokens)} tok)")
    
    lines.append("".join(line_parts))
    
    # Render children
    if root.children:
        # Update prefix for children
        new_prefix = prefix + ("    " if is_last else "│   ")
        
        for i, child in enumerate(root.children):
            child_is_last = (i == len(root.children) - 1)
            child_lines = render_tree(
                child,
                prefix=new_prefix,
                is_last=child_is_last,
                show_size=show_size,
            )
            lines.extend(child_lines)
    
    return lines


def generate_tree_view(
    files: List[FileInfo],
    root: Path,
    max_depth: Optional[int] = None,
    show_size: bool = False,
    sort_by: str = "name",
    dirs_first: bool = True,
) -> str:
    """Generate a tree view of the file structure.

    Parameters
    ----------
    files:
        List of file info objects.
    root:
        Root directory.
    max_depth:
        Maximum depth to display.
    show_size:
        Whether to show file sizes.
    sort_by:
        Sort criterion.
    dirs_first:
        Whether to list directories first.

    Returns
    -------
    str:
        Tree view as a string.
    """
    tree = build_tree(
        files,
        root,
        max_depth=max_depth,
        sort_by=sort_by,
        dirs_first=dirs_first,
    )

    lines = render_tree(
        tree,
        is_last=True,
        show_size=show_size,
    )
    
    # Count directories and files
    def count_nodes(node: TreeNode) -> Tuple[int, int]:
        """Count directories and files in the tree."""
        if not node.is_dir:
            return 0, 1
        dirs = 1
        files = 0
        for child in node.children:
            d, f = count_nodes(child)
            dirs += d
            files += f
        return dirs, files
    
    num_dirs, num_files = count_nodes(tree)
    # Subtract 1 for root directory
    num_dirs = max(0, num_dirs - 1)
    
    lines.append("")
    lines.append(f"{num_dirs} directories, {num_files} files")

    return "\n".join(lines)
