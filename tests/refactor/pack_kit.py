#!/usr/bin/env python3
"""
pack_kit.py - pack the whole tests/refactor/ folder into ONE self-extracting file.

Why: a chat can only take a handful of attachments, and tests/refactor/ has ~20 files.
The kit is a single .py file (compressed + base64 inside) that recreates every file, with
checksums, when run:

    python tests/refactor/pack_kit.py                 # writes ./refactor_kit.py (project root)
    python tests/refactor/pack_kit.py --out some.py   # write somewhere else

    python refactor_kit.py                            # (in the other chat/sandbox) extracts to ./tests/refactor/
    python refactor_kit.py --list                     # show what is inside, no extraction
    python refactor_kit.py --out DIR [--force]        # extract elsewhere / overwrite existing files

Re-pack after every phase (the folder changes: phases.py, baseline files, new tests), so the
kit you attach is current. Left out: __pycache__, last_handoff.md, before*/after* recordings
and any previous refactor_kit.py. refactor_kit.py is a generated file: do not commit it
(add it to .gitignore).
"""

import base64
import hashlib
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_NAMES = {"last_handoff.md", "refactor_kit.py"}
EXCLUDE_PREFIXES = ("before", "after")

TEMPLATE = '''#!/usr/bin/env python3
"""
refactor_kit.py - self-extracting kit: the tests/refactor/ harness of the CloudinatorFTP
app.py split, packed by tests/refactor/pack_kit.py ({n} files, {size_kb} KB unpacked).

    python refactor_kit.py                    # extract to ./tests/refactor/
    python refactor_kit.py --list             # list the files, extract nothing
    python refactor_kit.py --out DIR [--force]

Run it from the PROJECT ROOT (the folder that holds app.py), then use the scripts as
described in CLAUDE.md section "app.py SPLIT MAP" / TESTS. Every file is checksum-verified.
"""
import base64
import hashlib
import sys
import zlib
from pathlib import Path

FILES = {files_literal}


def main(argv):
    if "--list" in argv:
        for name, (sha, _b64) in FILES.items():
            print(f"{{sha[:12]}}  {{name}}")
        print(f"{{len(FILES)}} files")
        return 0
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("tests") / "refactor"
    force = "--force" in argv
    written = skipped = 0
    for name, (sha, b64) in FILES.items():
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            print("refusing unsafe path:", name)
            return 1
        data = zlib.decompress(base64.b64decode("".join(b64)))
        if hashlib.sha256(data).hexdigest() != sha:
            print("CHECKSUM MISMATCH:", name)
            return 1
        dest = out / rel
        if dest.exists() and not force:
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written += 1
    print(f"extracted {{written}} file(s) to {{out}}" + (f"; skipped {{skipped}} existing (use --force to overwrite)" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''


def collect():
    files = {}
    for p in sorted(HERE.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(HERE)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if (
            p.name in EXCLUDE_NAMES
            or p.name.startswith(EXCLUDE_PREFIXES)
            and p.suffix == ".json"
        ):
            continue
        data = p.read_bytes()
        b64 = base64.b64encode(zlib.compress(data, 9)).decode("ascii")
        chunks = [b64[i : i + 100] for i in range(0, len(b64), 100)]
        files[rel.as_posix()] = (hashlib.sha256(data).hexdigest(), chunks)
    return files


def main(argv):
    out = (
        Path(argv[argv.index("--out") + 1])
        if "--out" in argv
        else Path.cwd() / "refactor_kit.py"
    )
    files = collect()
    size_kb = (
        sum(
            len(zlib.decompress(base64.b64decode("".join(c))))
            for _s, c in files.values()
        )
        // 1024
    )
    literal = (
        "{\n"
        + "".join(
            f"    {name!r}: ({sha!r}, [\n"
            + "".join(f"        {c!r},\n" for c in chunks)
            + "    ]),\n"
            for name, (sha, chunks) in files.items()
        )
        + "}"
    )
    text = TEMPLATE.format(n=len(files), size_kb=size_kb, files_literal=literal)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(
        f"wrote {out}  ({len(files)} files, {size_kb} KB unpacked, {out.stat().st_size // 1024} KB packed)"
    )
    print(
        "Attach this ONE file instead of tests/refactor/*. Re-pack after every phase."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
