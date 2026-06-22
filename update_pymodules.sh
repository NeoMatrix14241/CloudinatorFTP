#!/bin/bash

REQ="requirements.txt"
CONSTRAINTS="constraints.txt"

# Single source of truth: every package this script touches, including the
# ones that need special handling on Termux. Exceptions are handled below
# via lookup tables, not by removing entries from this list -- so the list
# always reflects everything actually in use, on every platform.
packages=(
    Flask
    flask-cors
    bcrypt
    zipstream-new
    Werkzeug
    watchdog
    waitress
    cryptography
    mammoth
    openpyxl
    python-pptx
    rarfile
    pyzipper
    py7zr
    pyppmd
    psutil
    pynacl
    pyvips
    wsgidav
    paramiko
    pyftpdlib
    cheroot
)

# Exception case 1: Termux. Maps a pip package name -> its Termux apt
# package name. On Termux ONLY, these are upgraded via `pkg upgrade` (the
# patched, Android-correct build) and pip is locked to whatever version
# that lands on, via constraints.txt -- never pip-built directly, since
# PyPI has no Android wheel for these and a from-source build breaks them
# against bionic libc (same failure family as the pynacl/libsodium issue).
#
# Off Termux (Windows via Git Bash, regular Linux, etc.) this table is
# ignored entirely -- PyPI ships normal wheels for all of these there, so
# they're pip-managed exactly like everything else in `packages`.
#
# Leave the value empty ("") for anything with no Termux package that
# still needs locking -- e.g. pynacl, which termux_setup.sh builds once
# via `SODIUM_INSTALL=system pip install`.
declare -A SYSTEM_MANAGED=(
    [bcrypt]="python-bcrypt"
    [cryptography]="python-cryptography"
    [pyppmd]="python-pyppmd"   # py7zr dependency
    [psutil]="python-psutil"
    [pynacl]=""
)

# Exception case 2: known cross-package version conflicts, on any platform
# (e.g. wsgidav capping the bcrypt version it can use). Add entries as you
# discover new ones; the dry-run check further down catches ones you
# haven't added here yet too.
declare -A COMPAT_CEILING=(
    # [some-pkg]="<X.0"
)

# `pkg` is Termux's own wrapper -- it doesn't exist on Windows/regular Linux
# (and FreeBSD's unrelated `pkg` would false-positive a plain `command -v`
# check, hence checking Termux's own env vars instead).
if [ -n "$TERMUX_VERSION" ] || [[ "$PREFIX" == *com.termux* ]]; then
    IS_TERMUX=1
else
    IS_TERMUX=0
fi

touch "$REQ"
> "$CONSTRAINTS"

if [ "$IS_TERMUX" -eq 1 ]; then
    echo "==> Termux detected -- system-managed packages will be pkg-upgraded and locked, not pip-built."
    echo "==> Refreshing pkg index..."
    pkg update -y >/dev/null 2>&1
else
    echo "==> Not running in Termux -- every package below is pip-managed normally."
fi
echo

for pkg in "${packages[@]}"; do
    # --- Exception case: Termux + this package is system-managed ---
    if [ "$IS_TERMUX" -eq 1 ] && [ -n "${SYSTEM_MANAGED[$pkg]+x}" ]; then
        termux_name="${SYSTEM_MANAGED[$pkg]}"

        # Strip any stale direct entry from requirements.txt -- a leftover
        # version line here would force pip to manage it directly no
        # matter what constraints.txt says.
        sed -i -E "/^${pkg}([>=<~!].*)?$/d" "$REQ"

        if [ -n "$termux_name" ]; then
            echo "[PKG] pkg upgrade -y $termux_name"
            if ! pkg upgrade -y "$termux_name" >"/tmp/pkg_${pkg}.log" 2>&1; then
                echo "[WARN] pkg upgrade failed for $termux_name -- see /tmp/pkg_${pkg}.log, leaving existing install as-is."
            fi
        fi

        installed=$(pip show "$pkg" 2>/dev/null | awk -F': ' '/^Version/{print $2}')
        if [ -n "$installed" ]; then
            echo "${pkg}==${installed}" >> "$CONSTRAINTS"
            echo "[LOCK] $pkg -> $installed (Termux-managed, excluded from pip's direct list)"
        else
            echo "[WARN] $pkg not installed -- run termux_setup.sh first?"
        fi
        continue
    fi

    # --- Normal path: pip manages this package directly ---
    latest=$(pip index versions "$pkg" 2>/dev/null | grep -oP "(?<=Available versions: )[\d.]+" | head -n 1)

    if [ -z "$latest" ]; then
        echo "[WARN] Could not fetch version for $pkg, skipping..."
        continue
    fi

    if [ -n "${COMPAT_CEILING[$pkg]}" ]; then
        constraint="${COMPAT_CEILING[$pkg]}"
        echo "[FIX] Applying known compatibility ceiling for $pkg: $constraint"
    else
        # Extract the major version number (e.g., "4.3.4" -> "4")
        major_version=$(echo "$latest" | cut -d. -f1)
        next_major=$((major_version + 1))

        # Ceiling only -- not forcing ">=${latest}". Pinning the floor to
        # "newest available today" removes pip's only tool for resolving
        # a conflict: picking an older, mutually compatible version.
        constraint="<${next_major}"
    fi

    echo "Updating $pkg to $constraint"

    if grep -qE "^${pkg}([>=<~!]|$)" "$REQ"; then
        sed -i -E "s/^${pkg}([>=<~!].*)?/${pkg}${constraint}/" "$REQ"
    else
        echo "${pkg}${constraint}" >> "$REQ"
    fi
done

echo
echo "Done. Updated $REQ module constraints."
echo

# ==============================================================================
# CONFLICT CHECK -- resolve before installing, not after
# ==============================================================================
echo "==> Checking whether these constraints can actually be resolved together..."

DRYRUN_LOG="$(mktemp)"
if pip install -r "$REQ" -c "$CONSTRAINTS" --upgrade --dry-run >"$DRYRUN_LOG" 2>&1; then
    echo "[OK] No conflicts detected."
else
    echo "[CONFLICT] pip could not resolve a consistent set of versions:"
    echo "----------------------------------------------------------------"
    grep -E "Cannot install|conflicting dependencies|ERROR" "$DRYRUN_LOG"
    echo "----------------------------------------------------------------"
    echo "Full log: $DRYRUN_LOG"
    echo
    echo "If the conflict involves a Termux-locked package (bcrypt,"
    echo "cryptography, pyppmd, psutil, pynacl), pkg's current version is"
    echo "too old for something else in requirements.txt -- that's a real"
    echo "version wall, not something to work around by letting pip rebuild"
    echo "it. Otherwise, add the package to COMPAT_CEILING above."
    exit 1
fi

read -p "Do you want to install/update these packages now? (y/n): " choice

case "$choice" in
    y|Y )
        echo "Installing updated packages..."
        python -m pip install -r "$REQ" -c "$CONSTRAINTS" --upgrade --no-cache-dir

        echo
        echo "==> Verifying installed environment is internally consistent..."
        if pip check; then
            echo "[OK] pip check passed."
        else
            echo "[WARN] pip check found broken requirement sets above -- investigate before relying on this environment."
        fi

        read -p "Press any key to exit..."
    ;;
    * )
        echo "Skipped installation. You can run:"
        echo "pip install -r $REQ -c $CONSTRAINTS --upgrade --no-cache-dir"
        read -p "Press any key to exit..."
    ;;
esac