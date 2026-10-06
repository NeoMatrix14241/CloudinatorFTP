#!/usr/bin/env python3
"""
Record the PRISTINE state of app.py that every phase test compares against.

    python tests/refactor/snapshot_baseline.py            # static baseline (safe, no import)
    python tests/refactor/snapshot_baseline.py --runtime   # ALSO import app.py and record
                                                           # Quart's real url_map + hook order
                                                           # (scratch copy only, see below)

When to run it
  * ONCE, before Phase 1 starts, on the unmodified tree. If `app.py` changed since
    2026-10-06 (any bugfix), re-run it first and commit the new baseline_routes.json.
  * NEVER after a phase has started: it would bless whatever the move broke. The
    script refuses if core.py / middleware.py / routes/ already exist (use --force
    only if you know why).

--runtime imports app.py for real, which starts the file monitor, the search
crawler and the cleanup threads. Do it in a COPY of the project whose storage /
db / cache folders are throwaway, with CLOUDINATOR_REFACTOR_SCRATCH=1.
"""

import json
import sys

from common import (
    ROOT,
    BASELINE_FILE,
    RUNTIME_BASELINE_FILE,
    NEW_DIRS,
    NEW_TOP,
    build_baseline_from_tree,
    runtime_collect,
    sha_normalized,
)


def main(argv):
    started = [n for n in NEW_TOP if (ROOT / n).exists()] + [
        d for d in NEW_DIRS if (ROOT / d).exists()
    ]
    if started and "--force" not in argv:
        print("Refusing: a phase already started (found: " + ", ".join(started) + ").")
        print(
            "The baseline must describe the PRISTINE app.py. Use --force only if you are sure."
        )
        return 1
    if "--runtime" in argv:
        data = runtime_collect()
        RUNTIME_BASELINE_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(
            f"wrote {RUNTIME_BASELINE_FILE.name}: {len(data['rules'])} url rules, "
            f"{len(data['before_request'])} before_request, {len(data['after_request'])} after_request"
        )
        return 0
    data = build_baseline_from_tree()
    BASELINE_FILE.write_text(
        json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(f"wrote {BASELINE_FILE.name}")
    print(
        f"  app.py sha256 (newline-normalised): {sha_normalized(ROOT / 'app.py')[:16]}...  lines: {data['meta']['app_py_lines']}"
    )
    print(
        f"  {len(data['routes'])} route endpoints, "
        f"{sum(len(v) for v in data['hooks'].values())} hooks, "
        f"{len(data['endpoint_refs']['url_for'])} url_for names, "
        f"{len(data['endpoint_refs']['request_endpoint'])} request.endpoint names"
    )
    print(f"  side-effect order: {data['side_effect_order']}")
    print(f"  pyflakes known findings: {len(data['pyflakes_known'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
