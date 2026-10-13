#!/usr/bin/env python3
"""
tests/codeql_sarif_parser.py - turn CodeQL SARIF results into CSV (CLAUDE.md 4.88).

CodeQL results are SARIF files (one per language, e.g. python.sarif and javascript.sarif).
GitHub shows them as alerts but cannot export CSV unless you are on Enterprise, so this script
does it locally or inside the CodeQL workflow. Standard library only (no pandas needed).

    python tests/codeql_sarif_parser.py                    # every *.sarif / *.zip next to this script
    python tests/codeql_sarif_parser.py PATH [PATH ...]    # files, folders, or downloaded artifact zips
    python tests/codeql_sarif_parser.py sarif-results --out codeql-csv      (what the workflow does)

PATH can be
    a .sarif file                                   python.sarif
    a downloaded artifact .zip (no need to unzip)   sarif-artifact-python.zip
    a folder (searched recursively)                 sarif-results/

Manual download (repo > Actions > the latest "CodeQL" run > Artifacts): put the zips or the
extracted .sarif files into tests/ (or anywhere) and run the command above.

Output (in --out, default: the folder of this script):
    codeql_<language>_findings.csv      one file per language
    codeql_findings_all.csv             everything in one file, sorted by security severity
plus a short summary on the console. Files open directly in Excel (UTF-8 with BOM).

Options
    --out DIR             where the CSV files go
    --include-vendored    also report findings in vendored third-party files (pdf.js, video.js,
                          Font Awesome, ...; they are marked in the "Vendored" column either way)
    --exclude PATTERN     extra path pattern to treat as vendored/ignored (fnmatch, repeatable)
    --fail-on LEVEL       exit 1 if a non-vendored finding at or above LEVEL exists
                          (none | note | warning | error; default none = never fail)
    --no-combined         skip codeql_findings_all.csv
    -q, --quiet           no console summary

Note: the "Code Snippet" column is filled only when the SARIF itself contains snippets; recent
CodeQL versions often leave them out (the analyze action's `add-snippets` input was removed in v4).
File, line and column are always there, so open the file at that line.
"""

import argparse
import csv
import fnmatch
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

# Third-party files that live inside the repository (CLAUDE.md: "vendored files are not touched").
# Keep in step with paths-ignore in .github/codeql/codeql-config.yml.
VENDORED = [
    "static/js/pdf.mjs",
    "static/js/pdf.worker.mjs",
    "static/js/viewer.mjs",
    "static/js/video.js",
    "static/js/cmaps/*",
    "static/js/iccs/*",
    "static/js/locale/*",
    "static/js/standard_fonts/*",
    "static/js/wasm/*",
    "static/css/all.min.css",
    "static/css/viewer.css",
    "static/css/video.css",
    "static/webfonts/*",
]

LEVELS = {"none": 0, "note": 1, "warning": 2, "error": 3}
COLUMNS = [
    "Language",
    "Rule ID",
    "Rule Name",
    "Level",
    "Problem Severity",
    "Security Severity",
    "Severity Band",
    "Precision",
    "File Path",
    "Start Line",
    "End Line",
    "Start Column",
    "End Column",
    "Message",
    "Short Description",
    "CWE",
    "CWE / Tags",
    "Code Snippet",
    "Path Steps",
    "Suppressed",
    "Baseline State",
    "Fingerprint",
    "Vendored",
    "Source File",
]


# ------------------------------------------------------------------ reading
def guess_language(label, default=None):
    """python.sarif -> python, javascript.sarif / sarif-artifact-javascript-typescript.zip -> javascript."""
    low = label.lower()
    for key in (
        "python",
        "javascript",
        "typescript",
        "actions",
        "java",
        "csharp",
        "go",
        "ruby",
        "swift",
        "rust",
    ):
        if key in low:
            return "javascript" if key == "typescript" else key
    return default or Path(label).stem


def iter_sarif(paths):
    """Yield (label, language, parsed SARIF dict) for every SARIF document found in `paths`."""
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files = sorted(p.rglob("*.sarif")) + sorted(p.rglob("*.zip"))
        elif p.is_file():
            files = [p]
        else:
            print(f"warning: {raw} does not exist, skipped", file=sys.stderr)
            continue
        for f in files:
            if f.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(f) as z:
                        for name in sorted(z.namelist()):
                            if name.lower().endswith(".sarif"):
                                label = f"{f.name}:{name}"
                                lang = guess_language(
                                    Path(name).name, default=guess_language(f.stem)
                                )
                                yield label, lang, json.loads(
                                    z.read(name).decode("utf-8")
                                )
                except zipfile.BadZipFile:
                    print(f"warning: {f} is not a valid zip, skipped", file=sys.stderr)
            elif f.suffix.lower() == ".sarif":
                with open(f, "r", encoding="utf-8") as fh:
                    yield f.name, guess_language(f.stem), json.load(fh)


# ------------------------------------------------------------------ SARIF -> rows
def norm_uri(uri):
    uri = re.sub(r"^file:/+", "", unquote(uri or "")).replace("\\", "/")
    while uri.startswith("./"):
        uri = uri[2:]
    return uri


def clean_message(text):
    # CodeQL writes related locations as "[name](1)"; keep just the name
    return re.sub(r"\[([^\]]*)\]\(\d+\)", r"\1", text or "")


def band(sec):
    try:
        v = float(sec)
    except (TypeError, ValueError):
        return ""
    return (
        "critical"
        if v >= 9
        else "high" if v >= 7 else "medium" if v >= 4 else "low" if v > 0 else ""
    )


def is_vendored(path, patterns):
    p = path.replace("\\", "/")
    return any(fnmatch.fnmatch(p, pat) for pat in patterns)


def collect_rules(run):
    by_id, ordered = {}, []
    tool = run.get("tool", {})
    for comp in [tool.get("driver", {})] + list(tool.get("extensions", [])):
        for r in comp.get("rules", []) or []:
            if "id" in r:
                by_id[r["id"]] = r
        if comp is tool.get("driver", {}):
            ordered = list(comp.get("rules", []) or [])
    return by_id, ordered


def rows_from(run, language, source, patterns):
    by_id, ordered = collect_rules(run)
    for res in run.get("results", []) or []:
        rule_id = res.get("ruleId") or (res.get("rule") or {}).get("id") or ""
        if (
            not rule_id
            and isinstance(res.get("ruleIndex"), int)
            and res["ruleIndex"] < len(ordered)
        ):
            rule_id = ordered[res["ruleIndex"]].get("id", "")
        rule = by_id.get(rule_id, {})
        props = rule.get("properties", {}) or {}
        tags = [str(t) for t in props.get("tags", []) or []]
        cwes = sorted(
            {
                f"CWE-{m.group(1)}"
                for t in tags
                for m in [re.search(r"cwe-(\d+)", t, re.I)]
                if m
            }
        )
        level = (
            res.get("level")
            or (rule.get("defaultConfiguration") or {}).get("level")
            or "warning"
        )

        uri = start_line = end_line = start_col = end_col = snippet = ""
        locs = res.get("locations") or []
        if locs:
            phys = locs[0].get("physicalLocation", {}) or {}
            uri = norm_uri((phys.get("artifactLocation") or {}).get("uri", ""))
            region = phys.get("region", {}) or {}
            start_line = region.get("startLine", "")
            end_line = region.get("endLine", start_line)
            start_col = region.get("startColumn", "")
            end_col = region.get("endColumn", "")
            snippet = (region.get("snippet") or {}).get("text") or (
                (phys.get("contextRegion") or {}).get("snippet") or {}
            ).get("text", "")

        steps = ""
        flows = res.get("codeFlows") or []
        if flows and flows[0].get("threadFlows"):
            steps = len(flows[0]["threadFlows"][0].get("locations", []))

        msg = res.get("message") or {}
        yield {
            "Language": language,
            "Rule ID": rule_id,
            "Rule Name": rule.get("name", ""),
            "Level": level,
            "Problem Severity": props.get("problem.severity", ""),
            "Security Severity": props.get("security-severity", ""),
            "Severity Band": band(props.get("security-severity")),
            "Precision": props.get("precision", ""),
            "File Path": uri,
            "Start Line": start_line,
            "End Line": end_line,
            "Start Column": start_col,
            "End Column": end_col,
            "Message": clean_message(msg.get("text") or msg.get("markdown", "")),
            "Short Description": (rule.get("shortDescription") or {}).get("text", ""),
            "CWE": ", ".join(cwes),
            "CWE / Tags": ", ".join(tags),
            "Code Snippet": snippet,
            "Path Steps": steps,
            "Suppressed": "yes" if res.get("suppressions") else "",
            "Baseline State": res.get("baselineState", ""),
            "Fingerprint": (res.get("partialFingerprints") or {}).get(
                "primaryLocationLineHash", ""
            ),
            "Vendored": "yes" if is_vendored(uri, patterns) else "",
            "Source File": source,
        }


def sort_key(row):
    try:
        sec = float(row["Security Severity"])
    except (TypeError, ValueError):
        sec = -1.0
    return (
        -sec,
        -LEVELS.get(row["Level"], 0),
        row["File Path"],
        str(row["Start Line"]).zfill(8),
    )


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------ main
def main(argv=None):
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(
        description="CodeQL SARIF -> CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "paths",
        nargs="*",
        help=".sarif files, artifact .zip files or folders (default: the folder of this script)",
    )
    ap.add_argument(
        "--out",
        default=str(here),
        help="output folder (default: the folder of this script)",
    )
    ap.add_argument("--include-vendored", action="store_true")
    ap.add_argument("--exclude", action="append", default=[], metavar="PATTERN")
    ap.add_argument("--fail-on", choices=list(LEVELS), default="none")
    ap.add_argument("--no-combined", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    patterns = VENDORED + args.exclude
    inputs = args.paths or [str(here)]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    per_lang, found_docs = {}, 0
    for label, lang, doc in iter_sarif(inputs):
        found_docs += 1
        for run in doc.get("runs", []) or []:
            per_lang.setdefault(lang, []).extend(rows_from(run, lang, label, patterns))
    if not found_docs:
        print("no .sarif file found in: " + ", ".join(inputs))
        print(
            "download the artifact (repo > Actions > CodeQL run > Artifacts) and put the zip/.sarif there"
        )
        return 2

    all_rows, kept_all, skipped_vendor = [], [], 0
    for lang in sorted(per_lang):
        rows = per_lang[lang]
        skipped_vendor += sum(1 for r in rows if r["Vendored"])
        kept = rows if args.include_vendored else [r for r in rows if not r["Vendored"]]
        kept.sort(key=sort_key)
        write_csv(out_dir / f"codeql_{lang}_findings.csv", kept)
        all_rows += kept
    all_rows.sort(key=sort_key)
    if not args.no_combined:
        write_csv(out_dir / "codeql_findings_all.csv", all_rows)

    if not args.quiet:
        print(f"parsed {found_docs} SARIF file(s) -> {out_dir}")
        for lang in sorted(per_lang):
            n_all = len(per_lang[lang])
            n_kept = sum(1 for r in all_rows if r["Language"] == lang)
            lv = Counter(r["Level"] for r in all_rows if r["Language"] == lang)
            print(
                f"  {lang:<12} {n_kept:>5} finding(s) [{', '.join(f'{k} {v}' for k, v in sorted(lv.items(), key=lambda kv: -LEVELS.get(kv[0], 0))) or 'none'}]"
                + (
                    f"   ({n_all - n_kept} in vendored files hidden)"
                    if n_all != n_kept
                    else ""
                )
            )
        if skipped_vendor and not args.include_vendored:
            print(
                f"  vendored files are excluded (use --include-vendored to see {skipped_vendor} more)"
            )
        bands = Counter(r["Severity Band"] for r in all_rows if r["Severity Band"])
        if bands:
            print(
                "  security severity: "
                + ", ".join(
                    f"{b} {bands[b]}"
                    for b in ("critical", "high", "medium", "low")
                    if bands.get(b)
                )
            )
        for title, key in (("top rules", "Rule ID"), ("top files", "File Path")):
            top = Counter(r[key] for r in all_rows if r[key]).most_common(5)
            if top:
                print(f"  {title}: " + "; ".join(f"{k} ({v})" for k, v in top))

    if args.fail_on != "none":
        limit = LEVELS[args.fail_on]
        bad = [
            r
            for r in all_rows
            if LEVELS.get(r["Level"], 0) >= limit and not r["Suppressed"]
        ]
        if bad:
            print(f"FAILED: {len(bad)} finding(s) at level '{args.fail_on}' or above")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
