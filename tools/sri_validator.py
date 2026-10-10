#!/usr/bin/env python3
"""
sri_validator.py - check (and optionally fix) Subresource Integrity hashes
in CloudinatorFTP's Jinja templates.

For every <script src=...> and <link href=...> tag in the templates that
points at a local file under static/, this computes the SHA-384 of the file
bytes as they are on disk and compares it with the tag's `integrity`
attribute.

    python tools/sri_validator.py                 # check only, exit 1 on any problem
    python tools/sri_validator.py --fix           # add missing / repair stale hashes
    python tools/sri_validator.py --templates templates --static static

Recognised URL forms inside href/src:
    {{ url_for('static', filename='js/index.js') }}
    /static/js/index.js

Not touched (listed in the report, never an error):
    - inline <script> blocks (no src) - they cannot carry an integrity hash
    - external URLs (http://, https://, //host/...)
    - anything that is not a static file reference

Notes
    - Templates are read and written as raw bytes, so CRLF/LF line endings
      and every other byte of the template stay exactly as they were.
    - Browsers only ENFORCE `integrity` on <script>, and on <link> with
      rel=stylesheet / preload / modulepreload. On other <link> rels
      (icon, resource, ...) the attribute is accepted but ignored; this tool
      still keeps those hashes correct and tags them in the report.
    - The hash must match the bytes the SERVER sends. If git converts line
      endings (core.autocrlf) the file on the server can differ from the
      file on your PC; run this on the deployed files, or pin line endings
      with .gitattributes.
    - Dynamically created tags (e.g. a <link> that index.js adds at runtime)
      are not in any template, so they are not seen here.
"""

import argparse
import base64
import hashlib
import os
import re
import sys

# A whole <script ...> or <link ...> start tag. Quoted attribute values may
# contain '>' or Jinja braces/quotes, so match quoted strings as units.
TAG_RE = re.compile(
    rb"<(?P<name>script|link)\b(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*)>",
    re.IGNORECASE | re.DOTALL,
)
ATTR_RE_T = r"(?<![\w-]){name}\s*=\s*(?P<q>[\"'])(?P<val>.*?)(?P=q)"
URL_FOR_RE = re.compile(
    rb"""url_for\(\s*['"]static['"]\s*,\s*filename\s*=\s*['"](?P<f>[^'"]+)['"]\s*\)"""
)
STATIC_PATH_RE = re.compile(rb"^/static/(?P<f>[^?#]+)")

ENFORCED_LINK_RELS = {b"stylesheet", b"preload", b"modulepreload"}


def get_attr(attrs: bytes, name: str):
    m = re.search(
        ATTR_RE_T.format(name=name).encode(), attrs, re.IGNORECASE | re.DOTALL
    )
    return m


def static_file_for(url: bytes):
    """Return the path relative to static/ for a href/src value, or None."""
    m = URL_FOR_RE.search(url)
    if m:
        return m.group("f").decode()
    m = STATIC_PATH_RE.match(url.strip())
    if m:
        return m.group("f").decode()
    return None


def sri_of(path: str) -> str:
    with open(path, "rb") as fh:
        digest = hashlib.sha384(fh.read()).digest()
    return "sha384-" + base64.b64encode(digest).decode()


def process_template(tpl_path: str, static_dir: str, fix: bool, results: list):
    with open(tpl_path, "rb") as fh:
        data = fh.read()

    out = bytearray()
    pos = 0
    changed = False
    tpl_name = os.path.basename(tpl_path)

    for m in TAG_RE.finditer(data):
        name = m.group("name").lower()
        attrs = m.group("attrs")
        out += data[pos : m.start()]
        pos = m.end()
        tag = m.group(0)

        url_attr = get_attr(attrs, "src" if name == b"script" else "href")
        if not url_attr:
            # inline <script>, or <link> with no href
            label = "inline <script>" if name == b"script" else "<link> without href"
            results.append((tpl_name, label, "skip", "no src/href"))
            out += tag
            continue

        url = url_attr.group("val")
        rel_file = static_file_for(url)
        if rel_file is None:
            results.append(
                (
                    tpl_name,
                    url.decode(errors="replace"),
                    "skip",
                    "not a local static file",
                )
            )
            out += tag
            continue

        fs_path = os.path.join(static_dir, *rel_file.split("/"))
        if not os.path.isfile(fs_path):
            results.append((tpl_name, rel_file, "missing-file", f"{fs_path} not found"))
            out += tag
            continue

        expected = sri_of(fs_path)

        note = ""
        if name == b"link":
            rel = get_attr(attrs, "rel")
            rels = set(rel.group("val").lower().split()) if rel else set()
            if not (rels & ENFORCED_LINK_RELS):
                note = " (browsers ignore integrity on this <link> rel)"

        integ = get_attr(attrs, "integrity")
        if integ and integ.group("val").decode() == expected:
            results.append((tpl_name, rel_file, "ok", expected + note))
            out += tag
            continue

        if integ:
            status, detail = (
                "stale",
                f"has {integ.group('val').decode()[:22]}..., file is {expected[:22]}...",
            )
        else:
            status, detail = "no-hash", "no integrity attribute"

        if not fix:
            results.append((tpl_name, rel_file, status, detail + note))
            out += tag
            continue

        # --fix: rewrite the value in place, or add the attribute
        if integ:
            s, e = integ.span("val")
            new_attrs = attrs[:s] + expected.encode() + attrs[e:]
        else:
            # insert before a trailing '/' or at the end of the attributes,
            # keeping the original whitespace style of the tag
            stripped = attrs.rstrip()
            tail = attrs[len(stripped) :]
            if stripped.endswith(b"/"):
                body, slash = stripped[:-1].rstrip(), b" /"
            else:
                body, slash = stripped, b""
            new_attrs = body + b' integrity="' + expected.encode() + b'"' + slash + tail
        out += b"<" + m.group(0)[1 : 1 + len(name)] + new_attrs + b">"
        changed = True
        results.append((tpl_name, rel_file, "fixed", expected + note))

    out += data[pos:]

    if fix and changed:
        with open(tpl_path, "wb") as fh:
            fh.write(bytes(out))


def main():
    ap = argparse.ArgumentParser(description="Validate / fix SRI hashes in templates")
    ap.add_argument(
        "--templates",
        default="templates",
        help="templates directory (default: templates)",
    )
    ap.add_argument(
        "--static", default="static", help="static directory (default: static)"
    )
    ap.add_argument(
        "--fix",
        action="store_true",
        help="write correct integrity attributes into the templates",
    )
    args = ap.parse_args()

    if not os.path.isdir(args.templates):
        print(f"templates directory not found: {args.templates}")
        return 2
    if not os.path.isdir(args.static):
        print(f"static directory not found: {args.static}")
        return 2

    results = []
    for fn in sorted(os.listdir(args.templates)):
        if fn.lower().endswith((".html", ".htm", ".jinja", ".j2")):
            process_template(
                os.path.join(args.templates, fn), args.static, args.fix, results
            )

    icon = {
        "ok": "OK   ",
        "fixed": "FIXED",
        "stale": "STALE",
        "no-hash": "NONE ",
        "missing-file": "MISS ",
        "skip": "skip ",
    }
    for tpl, what, status, detail in results:
        print(f"{icon[status]} {tpl:12} {what}  -- {detail}")

    counts = {}
    for _, _, s, _ in results:
        counts[s] = counts.get(s, 0) + 1
    print()
    print("Summary: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))

    bad = (
        counts.get("stale", 0)
        + counts.get("no-hash", 0)
        + counts.get("missing-file", 0)
    )
    if args.fix:
        return 1 if counts.get("missing-file", 0) else 0
    if bad:
        print("Problems found. Run again with --fix to repair stale/missing hashes.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
