#!/bin/bash

REQ="requirements.txt"
CONSTRAINTS="constraints.txt"

# Always work next to this script, whatever directory it was launched from.
# (The Windows auto-elevation below re-opens a *login* shell that starts in the
# home folder -- without this, requirements.txt got written there instead.)
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

# ------------------------------------------------------------------------------
# Ctrl+C = STOP. Previously Ctrl+C only killed whichever single pip call was
# running; this script ignored it, printed "[WARN] Could not fetch version..."
# and carried on to the next package, the conflict check and the install
# prompt. Now Ctrl+C stops the whole script immediately.
#
# PHASE says how far along we are, so the abort message (and cleanup) is right:
#   init      before any file was touched            -> nothing to undo
#   generate  rewriting requirements/constraints     -> restore the old copies
#   prompt    files are done, waiting for "install?" -> keep them
#   install   pip install running                    -> keep them, warn
# ------------------------------------------------------------------------------
PHASE="init"
REQ_BACKUP=""
CONSTRAINTS_BACKUP=""
REQ_EXISTED=0
CONSTRAINTS_EXISTED=0
DRYRUN_LOG=""

_cleanup_backups() {
	[ -n "$REQ_BACKUP" ] && rm -f "$REQ_BACKUP"
	[ -n "$CONSTRAINTS_BACKUP" ] && rm -f "$CONSTRAINTS_BACKUP"
	return 0
}

_on_interrupt() {
	echo
	echo "[ABORTED] Ctrl+C received -- stopping."
	case "$PHASE" in
	generate)
		if [ "$REQ_EXISTED" -eq 1 ]; then cp -f "$REQ_BACKUP" "$REQ"; else rm -f "$REQ"; fi
		if [ "$CONSTRAINTS_EXISTED" -eq 1 ]; then cp -f "$CONSTRAINTS_BACKUP" "$CONSTRAINTS"; else rm -f "$CONSTRAINTS"; fi
		echo "[ABORTED] $REQ and $CONSTRAINTS restored to how they were -- nothing was changed."
		;;
	prompt)
		echo "[ABORTED] Nothing was installed. $REQ / $CONSTRAINTS were already regenerated;"
		echo "          install later with: pip install -r $REQ -c $CONSTRAINTS --upgrade --no-cache-dir"
		;;
	install)
		echo "[ABORTED] The install was interrupted part-way. Re-run this script, or run"
		echo "          'pip check' to see whether the environment is still consistent."
		;;
	esac
	[ -n "$DRYRUN_LOG" ] && rm -f "$DRYRUN_LOG"
	_cleanup_backups
	exit 130
}
trap _on_interrupt INT TERM
trap _cleanup_backups EXIT

# Single source of truth: every package this script touches, including the
# ones that need special handling on Termux. Exceptions are handled below
# via lookup tables, not by removing entries from this list -- so the list
# always reflects everything actually in use, on every platform.
#
# Post-ASGI-migration list (Quart + hypercorn[h3] instead of the old
# Flask/flask-cors/flask-wtf/waitress/cheroot WSGI stack; asgiref added).
# An entry with an extras marker like "hypercorn[h3]" is written to
# requirements.txt verbatim, but is regex-escaped and has its extras
# stripped wherever it's used as a pip query or a grep/sed pattern --
# see pkg_base/pkg_regex below. Square brackets are regex metacharacters,
# so treating $pkg as a literal string in a pattern would silently
# corrupt matching for any package using extras.
packages=(
	Quart
	bcrypt
	zipstream-new
	Werkzeug
	watchdog
	"hypercorn[h3]"
	cryptography
	mammoth
	openpyxl
	python-pptx
	rarfile
	pyzipper
	py7zr
	pyvips
	wsgidav
	asgiref
	paramiko
	pyftpdlib
	psutil
	pynacl
	pyppmd
	impacket
	pyOpenSSL
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
	[pyppmd]="python-pyppmd" # py7zr depends on this
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

# Regex-escapes a package name for safe use inside a grep/sed -E pattern.
# Needed because a couple of entries in `packages` carry a pip extras
# marker (e.g. "hypercorn[h3]"), and "[" / "]" are regex metacharacters --
# used unescaped, they'd be parsed as a character class instead of a
# literal package name, and could match or corrupt unrelated lines.
regex_escape() {
	printf '%s' "$1" | sed -E 's/[][(){}.*^$+?|\\]/\\&/g'
}

# `pkg` is Termux's own wrapper -- it doesn't exist on Windows/regular Linux
# (and FreeBSD's unrelated `pkg` would false-positive a plain `command -v`
# check, hence checking Termux's own env vars instead).
if [ -n "$TERMUX_VERSION" ] || [[ "$PREFIX" == *com.termux* ]]; then
	IS_TERMUX=1
else
	IS_TERMUX=0
fi

# We handle the Windows Auto-Elevation step BEFORE we try to call 'touch' or anything else,
# ensuring the environment variables are correctly inherited under the full login shell profile.
if [ "$IS_TERMUX" -eq 0 ]; then
	# --- Windows Defender & Auto-Elevation Handler ---
	if [ "$(uname -o 2>/dev/null)" == "Msys" ] || [[ "$OSTYPE" == "msys" ]]; then
		echo "==> Windows environment detected. Checking privileges..."

		# Check if running with Administrative rights via native PowerShell token inspection
		IS_ADMIN=$(powershell.exe -NoProfile -NonInteractive -Command "([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)" | tr -d '\r')

		if [ "$IS_ADMIN" != "True" ]; then
			echo "[UAC] Not running as Administrator. Requesting elevation..."

			# Use PowerShell to relaunch raw bash with login path parsing (--login) and interactivity (-i)
			powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process bash -ArgumentList '--login', '-i', '-c', '\"$0\"' -Verb RunAs"

			echo "[UAC] Relaunched in elevated interactive window. Exiting this session."
			exit 0
		fi

		echo "✅ Running with Administrator privileges."
		echo "==> Verifying Defender exclusions..."

		# Dynamically locate the ROOT Python installation directory (e.g., C:\Users\helpdesk\AppData\Local\Programs\Python\Python312)
		# by looking at the directory containing the python executable.
		PYTHON_ROOT_DIR=$(python -c "import os, sys; print(os.path.join(os.path.dirname(sys.executable)))" | tr -d '\r')

		if [ -d "$PYTHON_ROOT_DIR" ]; then
			echo "[INFO] Targeting entire Python directory: $PYTHON_ROOT_DIR"
			echo "[DEFENDER] Ensuring root exclusion path is set to protect site-packages..."
			powershell.exe -NoProfile -NonInteractive -Command "Add-MpPreference -ExclusionPath '$PYTHON_ROOT_DIR' -ErrorAction SilentlyContinue"
			echo "✅ Root exclusion path verified/added."
		fi
	fi
fi

# Snapshot the current files so Ctrl+C during generation can put them back.
REQ_BACKUP="$(mktemp)"
CONSTRAINTS_BACKUP="$(mktemp)"
if [ -f "$REQ" ]; then
	cp -f "$REQ" "$REQ_BACKUP"
	REQ_EXISTED=1
fi
if [ -f "$CONSTRAINTS" ]; then
	cp -f "$CONSTRAINTS" "$CONSTRAINTS_BACKUP"
	CONSTRAINTS_EXISTED=1
fi
PHASE="generate"

touch "$REQ"
{
	echo "# AUTO-GENERATED by setup_pymodules.sh -- do not edit by hand."
	echo "# This is a build artifact, not source: it is truncated and"
	echo "# rewritten from scratch on every run, so any manual edits here"
	echo "# will be lost the next time the script runs."
	echo "#"
	echo "# On Termux: pins SYSTEM_MANAGED packages (bcrypt, cryptography,"
	echo "# pyppmd, psutil, pynacl) to whatever 'pkg' currently has installed,"
	echo "# so pip can use them to satisfy other packages' requirements but"
	echo "# can never download/rebuild its own copy."
	echo "#"
	echo "# Off Termux: intentionally left empty -- those packages are"
	echo "# pip-managed normally there, with no lock needed."
} >"$CONSTRAINTS"

if [ "$IS_TERMUX" -eq 1 ]; then
	echo "==> Termux detected -- system-managed packages will be pkg-upgraded and locked, not pip-built."
	echo "==> Refreshing pkg index..."
	pkg update -y >/dev/null 2>&1
else
	echo "==> Not running in Termux -- every package below is pip-managed normally."
fi
echo

for pkg in "${packages[@]}"; do
	# pkg        -- exact string as written to requirements.txt/constraints.txt,
	#               and the key used for SYSTEM_MANAGED / COMPAT_CEILING lookups
	#               (extras marker kept, e.g. "hypercorn[h3]").
	# pkg_base   -- extras stripped, for pip queries ("pip show", "pip index
	#               versions" don't want/need "[h3]").
	# pkg_regex  -- regex-escaped, for use inside grep/sed -E patterns so any
	#               "[", "]" etc. are matched literally, not as regex syntax.
	pkg_base="${pkg%%\[*}"
	pkg_regex="$(regex_escape "$pkg")"

	# --- Exception case: Termux + this package is system-managed ---
	if [ "$IS_TERMUX" -eq 1 ] && [ -n "${SYSTEM_MANAGED[$pkg]+x}" ]; then
		termux_name="${SYSTEM_MANAGED[$pkg]}"

		# Strip any stale direct entry from requirements.txt -- a leftover
		# version line here would force pip to manage it directly no
		# matter what constraints.txt says.
		sed -i -E "/^${pkg_regex}([>=<~!].*)?$/d" "$REQ"

		if [ -n "$termux_name" ]; then
			echo "[PKG] pkg upgrade -y $termux_name"
			if ! pkg upgrade -y "$termux_name" >"/tmp/pkg_${pkg_base}.log" 2>&1; then
				echo "[WARN] pkg upgrade failed for $termux_name -- see /tmp/pkg_${pkg_base}.log, leaving existing install as-is."
			fi
		fi

		installed=$(pip show "$pkg_base" 2>/dev/null | awk -F': ' '/^Version/{print $2}')
		if [ -n "$installed" ]; then
			echo "${pkg}==${installed}" >>"$CONSTRAINTS"
			echo "[LOCK] $pkg -> $installed (Termux-managed, excluded from pip's direct list)"
		else
			echo "[WARN] $pkg not installed -- run termux_setup.sh first?"
		fi
		continue
	fi

	# --- Normal path: pip manages this package directly ---
	latest=$(pip index versions "$pkg_base" 2>/dev/null | grep -oP "(?<=Available versions: )[\d.]+" | head -n 1)

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

	if grep -qE "^${pkg_regex}([>=<~!]|$)" "$REQ"; then
		sed -i -E "s/^${pkg_regex}([>=<~!].*)?\$/${pkg}${constraint}/" "$REQ"
	else
		echo "${pkg}${constraint}" >>"$REQ"
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

PHASE="prompt"
read -p "Do you want to install/update these packages now? (y/n): " choice

case "$choice" in
y | Y)
	echo "Installing updated packages..."
	PHASE="install"
	python -m pip install -r "$REQ" -c "$CONSTRAINTS" --upgrade --no-cache-dir

	echo
	echo "==> Verifying installed environment is internally consistent..."
	if pip check; then
		echo "[OK] pip check passed."
	else
		echo "[WARN] pip check found broken requirement sets above -- investigate before relying on this environment."
	fi

	PHASE="done"
	read -p "Press any key to exit..."
	;;
*)
	echo "Skipped installation. You can run:"
	echo "pip install -r $REQ -c $CONSTRAINTS --upgrade --no-cache-dir"
	read -p "Press any key to exit..."
	;;
esac
