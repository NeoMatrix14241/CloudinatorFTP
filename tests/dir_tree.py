import os
from pathlib import Path

EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    ".pytest_cache",
    ".manage_pids",
    "images",
    "cmaps",
    "iccs",
    "images",
    "locale",
    "standard_fonts",
    "wasm",
    "tests"
}


def collect_entries(base_path: Path):
    dirs = []
    files = []

    for child in sorted(base_path.iterdir(), key=lambda p: p.name.lower()):
        if child.name in EXCLUDED_DIRS or child.name.startswith(".pytest_cache"):
            continue
        if child.is_dir():
            dirs.append(child)
        else:
            files.append(child)

    return dirs, files


def print_tree(base_path: Path, prefix: str = ""):
    dirs, files = collect_entries(base_path)
    entries = dirs + files

    for index, entry in enumerate(entries):
        is_last = index == len(entries) - 1
        connector = "└── " if is_last else "├── "
        print(prefix + connector + entry.name)

        if entry.is_dir():
            child_prefix = prefix + ("    " if is_last else "│   ")
            print_tree(entry, child_prefix)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    print(project_root.name)
    print_tree(project_root)
