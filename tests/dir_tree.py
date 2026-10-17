from pathlib import Path

EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    ".pytest_cache",
    ".manage_pids",
    "logs",
}

# Show the directory, skip its contents, and optionally explain why.
# Format: "directory_name": "comment"
EXCLUDE_DIR_WALK = {
    "images": "pdfjs dependency",
    "cmaps": "pdfjs dependency",
    "iccs": "pdfjs dependency",
    "locale": "pdfjs dependency",
    "standard_fonts": "pdfjs dependency",
    "wasm": "pdfjs dependency",
    "uploads": "chunked uploads directory",
    "webfonts": "fontawesome dependency",
}

# Optional comments for individual files.
# Format: "filename": "comment"
# Omit a file or use an empty string if no comment is needed.
FILE_COMMENTS = {
    # "app.py": "Main application",
    # "requirements.txt": "Python dependencies",
    # "README.md": "",
    "pdf.mjs": "pdfjs dependency",
    "pdf.worker.mjs": "pdfjs dependency",
    "viewer.mjs": "pdf.js dependency",
    "viewer.css": "pdf.js dependency",
    "video.js": "video.js dependency",
    "video.css": "video.js dependency",
    "all.min.js": "fontawesome dependency",
}

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR.parent / "docs" / "directory_tree.txt"


def collect_entries(base_path: Path):
    dirs = []
    files = []

    for child in sorted(base_path.iterdir(), key=lambda p: p.name.lower()):
        if child.resolve() == OUTPUT_FILE.resolve():
            continue

        if child.name in EXCLUDED_DIRS or child.name.startswith(".pytest_cache"):
            continue

        if child.is_dir():
            dirs.append(child)
        else:
            files.append(child)

    return dirs, files


def build_tree(base_path: Path, prefix: str = ""):
    lines = []
    dirs, files = collect_entries(base_path)
    entries = dirs + files

    for index, entry in enumerate(entries):
        is_last = index == len(entries) - 1
        connector = "└── " if is_last else "├── "

        # Append optional comments to files.
        display_name = entry.name

        if not entry.is_dir():
            comment = FILE_COMMENTS.get(entry.name, "").strip()

            if comment:
                display_name += f" ({comment})"

        lines.append(prefix + connector + display_name)

        if entry.is_dir():
            child_prefix = prefix + ("    " if is_last else "│   ")

            if entry.name in EXCLUDE_DIR_WALK:
                comment = EXCLUDE_DIR_WALK[entry.name].strip()
                suffix = f" ({comment})" if comment else ""

                lines.append(child_prefix + "└── ..." + suffix)
            else:
                lines.extend(build_tree(entry, child_prefix))

    return lines


if __name__ == "__main__":
    project_root = SCRIPT_DIR.parent

    # Generate the tree once for both terminal and file output.
    tree_lines = [project_root.name]
    tree_lines.extend(build_tree(project_root))
    tree_text = "\n".join(tree_lines) + "\n"

    # Print to terminal.
    print(tree_text, end="")

    # Save to docs/directory_tree.txt, creating docs if necessary.
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(tree_text, encoding="utf-8")

    print(f"\nDirectory tree saved to: {OUTPUT_FILE}")
