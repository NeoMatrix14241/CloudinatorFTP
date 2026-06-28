#!/usr/bin/env python3
"""
smb_setup.py — One-time SMB port-445 setup for CloudinatorFTP
------------------------------------------------------------------
This is a standalone tool you run manually, like create_user.py or
reset_db.py — it is NEVER invoked automatically by prod_server.py or
dev_server.py. Run it once, when you decide you want CloudinatorFTP's
SMB server to use the real port 445 instead of the 8445 fallback.

    python smb_setup.py
    ./manage.sh smb-setup

What it does, per platform:

  Windows
    Stops Windows' own native file-sharing service (LanmanServer) so
    CloudinatorFTP's SMB server can use port 445 instead. This does NOT
    take effect immediately — Windows binds SMB hosting at the driver
    level, not just a service flag, so the port doesn't actually release
    until you restart. This script will tell you to restart; it will
    NEVER execute a restart on your behalf, under any circumstance.

    Your ability to access OTHER computers' shares (Win+R \\\\server\\share,
    mapped drives, Network folder browsing) is NOT affected — that's a
    completely separate Windows service (Workstation). Only the ability
    for OTHER computers to reach folders shared natively FROM this PC
    changes — CloudinatorFTP's own SMB server takes over that exact job.

  Linux
    Grants the Python binary permission to bind port 445 without root,
    via setcap. Takes effect immediately, no restart needed.

  Android (Termux)
    If rooted: points you at launching the server itself as root, since
    setcap's behavior on Android is unpredictable across devices due to
    SELinux policy differences — better to be unambiguous here than to
    grant a capability that might silently not work on your specific
    device.
    If not rooted: there's no path to port 445 at all. CloudinatorFTP
    falls back to port 8445 automatically either way.

This script can also UNDO its Windows change (restore native file
sharing), with the same confirm-then-restart shape in reverse.
"""

import json
import os
import platform
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import lanman_guard
from paths import get_db_dir

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux" if not IS_WINDOWS else False


def is_termux() -> bool:
    return os.path.exists("/data/data/com.termux") or "com.termux" in os.environ.get(
        "PREFIX", ""
    )


def state_path() -> str:
    return os.path.join(get_db_dir(create=True), ".smb_lanman_state.json")


def detect_platform() -> str:
    if IS_WINDOWS:
        return "windows"
    if is_termux():
        return "termux"
    return "linux"


# ── Windows ──────────────────────────────────────────────────────────────────


def _relaunch_elevated_and_exit(resume_action: str):
    """
    Relaunch THIS script elevated via a UAC prompt, passing --resume so the
    new instance skips straight to the action instead of re-showing the
    menu. The current (unelevated) process exits either way — the new
    elevated instance is the one that actually continues.

    NOTE: this is the one piece of Windows handling that cannot be
    exercised end-to-end outside a real Windows session with a human
    available to click the UAC prompt — there's no way to script past
    that consent dialog, by design. ShellExecuteW's plain success/failure
    return code has been checked against its documented contract, but the
    live UAC round-trip itself hasn't been, and can't be, run in this
    environment.
    """
    import ctypes

    script = os.path.abspath(__file__)
    params = f'"{script}" --resume {resume_action}'
    # ShellExecuteW return value contract (per Win32 docs): >32 means it
    # launched successfully; <=32 is an error code (most commonly the user
    # clicking "No" on the UAC prompt, or the file/path not being found).
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
    if ret <= 32:
        print()
        print("⚠️  Elevation request failed or was declined — nothing was changed.")
    sys.exit(0)


def windows_disable(skip_confirm: bool = False):
    print()
    print("This will stop Windows' own native file-sharing service")
    print("(LanmanServer) so CloudinatorFTP's SMB server can use port 445.")
    print()
    print("⚠️  Requires a RESTART afterward to take effect — this is a")
    print("    driver-level binding, not just a service flag, so the port")
    print("    doesn't actually release until you reboot. Use Restart, not")
    print("    Shut Down — Windows' Fast Startup can skip re-applying this")
    print("    on a shutdown/power-on cycle.")
    print()
    print("⚠️  Other PCs will no longer reach folders shared natively FROM")
    print("    this PC via Windows' own sharing — your ability to access")
    print("    OTHER computers' shares (Win+R, mapped drives) is unaffected,")
    print("    that's a separate service (Workstation).")
    print()

    if not skip_confirm:
        confirm = input("Type 'yes' to continue: ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            return

    if not lanman_guard.is_elevated():
        print()
        print("🔐 This needs Administrator rights. Requesting elevation now —")
        print("   you'll see a UAC prompt; this script will relaunch itself")
        print("   and continue automatically once you approve it.")
        _relaunch_elevated_and_exit("windows-disable")
        return  # unreachable — _relaunch_elevated_and_exit always exits

    try:
        current = lanman_guard.get_lanman_state()
    except Exception as e:
        print(f"❌ Could not query LanmanServer: {e}")
        return

    if current["status"] != "Running":
        print(
            f"ℹ️  LanmanServer is already stopped (StartType: {current['start_type']})."
        )
        print("   Nothing to do here. If port 445 still won't bind once you've")
        print("   restarted, something else may be holding it — check with:")
        print("   netstat -ano | findstr :445")
        return

    try:
        lanman_guard.run_ps("Stop-Service LanmanServer -Force")
        lanman_guard.run_ps("Set-Service LanmanServer -StartupType Disabled")
    except Exception as e:
        print(f"❌ Failed to stop LanmanServer: {e}")
        return

    lanman_guard.mark_disable_pending(state_path(), current["start_type"], True)

    print()
    print("✅ LanmanServer stopped and disabled.")
    print()
    print("━" * 68)
    print("  RESTART YOUR PC NOW — use Restart, not Shut Down.")
    print()
    print("  After restarting, just start CloudinatorFTP normally.")
    print("  Port 445 will work automatically — no further action needed.")
    print("━" * 68)

    _offer_enable_smb_in_config()


def windows_restore(skip_confirm: bool = False):
    pending = lanman_guard.get_pending_state(state_path())

    print()
    print("This restores Windows' own native file-sharing service")
    print("(LanmanServer), undoing what smb_setup.py changed earlier.")
    print()
    print("⚠️  Also requires a RESTART to fully take effect, same as the")
    print("    original change did.")
    print()

    if not skip_confirm:
        confirm = input("Type 'yes' to continue: ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            return

    if not lanman_guard.is_elevated():
        print()
        print("🔐 This needs Administrator rights. Requesting elevation now —")
        print("   you'll see a UAC prompt; this script will relaunch itself")
        print("   and continue automatically once you approve it.")
        _relaunch_elevated_and_exit("windows-restore")
        return

    original_start_type = (
        pending.get("original_start_type", "Automatic") if pending else "Automatic"
    )
    was_running = pending.get("was_running", True) if pending else True

    try:
        lanman_guard.run_ps(
            f"Set-Service LanmanServer -StartupType {original_start_type}"
        )
        if was_running:
            lanman_guard.run_ps("Start-Service LanmanServer")
    except Exception as e:
        print(f"❌ Failed to restore LanmanServer: {e}")
        print(
            f"   Manual fix: Set-Service LanmanServer -StartupType {original_start_type}"
        )
        if was_running:
            print("              Start-Service LanmanServer")
        return

    lanman_guard.clear_pending_state(state_path())

    print()
    print(f"✅ LanmanServer restored (StartupType → {original_start_type}).")
    print()
    print("━" * 68)
    print("  RESTART YOUR PC WHENEVER CONVENIENT to fully complete this.")
    print("  CloudinatorFTP's SMB server will fall back to port 8445 until")
    print("  then (and from then on, unless you run setup again).")
    print("━" * 68)


def windows_status():
    print()
    print("Checking LanmanServer + port 445 status…")
    try:
        current = lanman_guard.get_lanman_state()
        print(
            f"  LanmanServer:  {current['status']}  (StartType: {current['start_type']})"
        )
    except Exception as e:
        print(f"  LanmanServer:  could not query ({e})")

    bindable = lanman_guard.can_bind_445()
    print(f"  Port 445:      {'available' if bindable else 'in use / not bindable'}")

    pending = lanman_guard.get_pending_state(state_path())
    if pending:
        print()
        print(f"  ⏳ A disable was requested at {pending.get('changed_at', '?')}, ")
        if bindable:
            print("     and port 445 is now available — looks like the restart worked!")
            print(
                "     This will be confirmed automatically next time the server starts."
            )
        else:
            print("     but port 445 still isn't available.")
            print("     If you haven't restarted since running this, restart now")
            print("     (use Restart, not Shut Down). Already restarted and still")
            print("     seeing this? Check what's holding it:")
            print("     netstat -ano | findstr :445")
    elif bindable:
        print()
        print("  No setup has been done, and none is needed — port 445 is free.")


# ── Linux ────────────────────────────────────────────────────────────────────


def linux_setup():
    print()
    print("This grants Python permission to bind port 445 without root,")
    print("via a one-time capability grant (setcap). Takes effect")
    print("immediately — no restart needed, unlike Windows.")
    print()

    python_path = (
        subprocess.run(
            ["readlink", "-f", sys.executable], capture_output=True, text=True
        ).stdout.strip()
        or sys.executable
    )

    cmd = ["setcap", "cap_net_bind_service=+ep", python_path]

    if os.geteuid() == 0:
        print(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(
                f"✅ Done. Port 445 will work immediately for {python_path}, no root needed from now on."
            )
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed: {e.stderr.strip()}")
            print("   Is 'setcap' installed? Try: sudo apt install libcap2-bin")
    else:
        print("This needs root. Run this exact command yourself, then start")
        print("CloudinatorFTP normally — no need to re-run this script after:")
        print()
        print(f"   sudo setcap cap_net_bind_service=+ep {python_path}")
        print()
        print("Note: this applies to that exact Python binary path. If you")
        print("rebuild your virtualenv or switch interpreters later, you'll")
        print("need to run it again for the new path.")


def linux_status():
    print()
    bindable = lanman_guard.can_bind_445()
    print(
        f"  Port 445: {'available' if bindable else 'not bindable (needs setcap or root)'}"
    )
    if not bindable:
        python_path = (
            subprocess.run(
                ["readlink", "-f", sys.executable], capture_output=True, text=True
            ).stdout.strip()
            or sys.executable
        )
        print(
            f"  Run option 1 (or: sudo setcap cap_net_bind_service=+ep {python_path})"
        )


# ── Android / Termux ─────────────────────────────────────────────────────────


def termux_is_rooted() -> bool:
    try:
        result = subprocess.run(
            ["su", "-c", "id"], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and "uid=0" in result.stdout
    except Exception:
        return False


def termux_setup():
    print()
    if termux_is_rooted():
        print("Root access detected.")
        print()
        print("Rather than setcap (its behavior on Android is unpredictable —")
        print("SELinux policy varies a lot across devices and rooting methods,")
        print("and a granted capability can silently fail to actually apply at")
        print("runtime) — the reliable option is launching the server itself")
        print("as root:")
        print()
        print("   su -c 'python prod_server.py'")
        print("   # or, if you use tsu:")
        print("   tsu")
        print("   python prod_server.py")
        print()
        print("Running as root can bind port 445 directly, no extra setup step.")
    else:
        print("No root access detected on this device.")
        print()
        print("There's no path to port 445 without root on Android.")
        print("CloudinatorFTP will use port 8445 instead — this is automatic,")
        print("nothing further to do here.")


# ── Shared ───────────────────────────────────────────────────────────────────


def _offer_enable_smb_in_config():
    print()
    answer = input("Flip SMB_ENABLED to True in config.py now? [y/N]: ").strip().lower()
    if answer != "y":
        print("OK — you can do this later by editing config.py, or via:")
        print("   python config.py   (option 13 → SMB)")
        return
    try:
        import config

        config.SMB_ENABLED = True
        config.save_server_config()
        print("✅ SMB_ENABLED set to True and saved.")
    except Exception as e:
        print(f"⚠️  Could not update config.py automatically: {e}")
        print("   Set SMB_ENABLED = True yourself, or via: python config.py")


def main():
    # --resume is how the elevated relaunch continues after a UAC prompt —
    # not meant to be typed by a human directly.
    if "--resume" in sys.argv:
        idx = sys.argv.index("--resume")
        action = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if action == "windows-disable":
            windows_disable(skip_confirm=True)
        elif action == "windows-restore":
            windows_restore(skip_confirm=True)
        else:
            print(f"Unknown resume action: {action!r}")
        return

    plat = detect_platform()
    print("=" * 60)
    print("  CloudinatorFTP — SMB Port 445 Setup")
    print("=" * 60)
    print(f"  Platform detected: {plat}")
    print("=" * 60)

    if plat == "windows":
        while True:
            print()
            print("1. Allow CloudinatorFTP to use port 445 (one-time setup)")
            print("2. Undo — restore native Windows file sharing")
            print("3. Check current status")
            print("4. Exit")
            choice = input("\nSelect (1-4): ").strip()
            if choice == "1":
                windows_disable()
            elif choice == "2":
                windows_restore()
            elif choice == "3":
                windows_status()
            elif choice == "4":
                break
            else:
                print("Invalid option.")
    elif plat == "termux":
        termux_setup()
    else:
        while True:
            print()
            print("1. Allow CloudinatorFTP to use port 445 (one-time setup)")
            print("2. Check current status")
            print("3. Exit")
            choice = input("\nSelect (1-3): ").strip()
            if choice == "1":
                linux_setup()
            elif choice == "2":
                linux_status()
            elif choice == "3":
                break
            else:
                print("Invalid option.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
