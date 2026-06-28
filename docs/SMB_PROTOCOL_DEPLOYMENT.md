# 📡 SMB Protocol Deployment Guide

CloudinatorFTP can serve files over SMB — the protocol that makes a folder show up as a real, native network drive on Windows (and mountable on macOS/Linux too). This guide covers the one-time setup needed, per platform, plus the antivirus quirk you'll almost certainly hit on Windows.

## 📋 Table of Contents

1. [Why SMB Needs Setup First (Unlike WebDAV/SFTP/FTP)](#why-smb-needs-setup-first)
2. [Step 1 — Install impacket](#step-1--install-impacket)
3. [Step 2 — The Antivirus Problem (Windows)](#step-2--the-antivirus-problem-windows)
4. [Step 3 — Run smb_setup.py](#step-3--run-smb_setuppy)
5. [Platform-Specific Details](#platform-specific-details)
6. [Connecting to the Share](#connecting-to-the-share)
7. [Password Resets and SMB Credentials](#password-resets-and-smb-credentials)
8. [Undoing the Setup](#undoing-the-setup)
9. [Troubleshooting](#troubleshooting)
10. [FAQ](#faq)

---

## Why SMB Needs Setup First

WebDAV, SFTP, and FTP all work the moment their library is installed — `pip install` it, restart the server, done. SMB is different, and deliberately defaults to **disabled** even with `impacket` installed:

| | Other 3 protocols | SMB |
|---|---|---|
| Library installed → works? | ✅ Yes, immediately | ❌ No — needs a one-time machine setup too |
| Needs OS-level changes? | No | Yes, on Windows specifically |
| Needs a restart? | No | Yes, on Windows (Linux/Android: no) |

The reason: SMB's standard port, **445**, is a privileged port (needs root on Linux/Android) **and**, on Windows, it's already occupied by Windows' own built-in file-sharing service by default. Getting port 445 requires a deliberate, one-time decision — not something that should happen silently just because a library got installed.

Until that setup is done, CloudinatorFTP's SMB server automatically falls back to **port 8445** — the rest of the server works completely normally either way.

---

## Step 1 — Install impacket

```bash
pip install impacket
```

This is the only Python SMB *server* library that exists — confirmed directly against the current PyPI listings for the alternatives: `smbprotocol` describes itself as an "SMBv2 and v3 **Client** for Python," and `pysmb`'s own docs state outright: *"Note that this is only a client library. It does not share files."* Neither can act as a server, at all, by design. `impacket.smbserver` is the only option that can actually accept incoming connections.

---

## Step 2 — The Antivirus Problem (Windows)

**This will very likely happen to you, so read this before you're confused by it.**

`impacket` is also the basis of several well-known penetration-testing tools. Windows Defender (and most other antivirus products) flag parts of it heuristically — even though `impacket.smbserver` itself does nothing malicious. You'll typically see an error like:

```
SMB: error: [Errno 22] Invalid argument: '...site-packages\impacket\dcerpc\v5\epm.py'
```

That's Defender quarantining the file mid-import, not a bug in CloudinatorFTP.

### Fix: add an exclusion

**Find your Python install path first** — it differs depending on whether you're using a virtual environment or system Python:

```powershell
# If using a venv (check your venv's Scripts folder):
.\venv\Scripts\python.exe -c "import impacket; print(impacket.__file__)"

# If using system Python:
python -c "import impacket; print(impacket.__file__)"
```

This prints the exact path to `impacket/__init__.py` — the folder containing it is what you exclude.

**Add the exclusion** (elevated PowerShell):
```powershell
# venv example:
Add-MpPreference -ExclusionPath "C:\path\to\your\project\venv\Lib\site-packages\impacket"

# system Python example:
Add-MpPreference -ExclusionPath "C:\Users\YOURNAME\AppData\Local\Programs\Python\Python3XX\Lib\site-packages\impacket"
```

**If files were already quarantined** (not just blocked), reinstall after adding the exclusion so Defender doesn't grab the fresh copies too:
```powershell
pip uninstall impacket -y
pip install impacket --no-cache-dir
```

### This isn't a one-time annoyance

The exclusion is per-machine — you'll need to repeat this on every Windows machine you deploy to, and anyone else who clones the project hits the same wall on first run. Two longer-term options:

1. **Submit it as a false positive** to Microsoft: https://www.microsoft.com/en-us/wdsi/filesubmission — slow, but if accepted, future installs won't need the exclusion at all.
2. **Reconsider whether you need SMB at all.** You already have WebDAV (native drive mapping, zero AV drama) and rclone mount support — both give the same "mapped network drive" experience without this friction. SMB is worth it mainly if you specifically need legacy-client compatibility or `\\HOST\Share`-style UNC paths.

---

## Step 3 — Run smb_setup.py

This is a **standalone, manual, one-time tool** — exactly like `create_user.py` or `reset_db.py`. It is *never* run automatically by `prod_server.py` or `dev_server.py`.

```bash
python smb_setup.py
# or
./manage.sh smb-setup
```

It detects your platform automatically and walks you through the right action.

---

## Platform-Specific Details

### 🪟 Windows

Stops Windows' own native file-sharing service (`LanmanServer`) so CloudinatorFTP's SMB server can use port 445 instead.

**Example run:**
```
============================================================
  CloudinatorFTP — SMB Port 445 Setup
============================================================
  Platform detected: windows
============================================================

1. Allow CloudinatorFTP to use port 445 (one-time setup)
2. Undo — restore native Windows file sharing
3. Check current status
4. Exit

Select (1-4): 1

This will stop Windows' own native file-sharing service
(LanmanServer) so CloudinatorFTP's SMB server can use port 445.

⚠️  Requires a RESTART afterward to take effect — this is a
    driver-level binding, not just a service flag, so the port
    doesn't actually release until you reboot. Use Restart, not
    Shut Down — Windows' Fast Startup can skip re-applying this
    on a shutdown/power-on cycle.

⚠️  Other PCs will no longer reach folders shared natively FROM
    this PC via Windows' own sharing — your ability to access
    OTHER computers' shares (Win+R, mapped drives) is unaffected,
    that's a separate service (Workstation).

Type 'yes' to continue: yes

🔐 This needs Administrator rights. Requesting elevation now —
   you'll see a UAC prompt; this script will relaunch itself
   and continue automatically once you approve it.
```

A UAC prompt appears — click **Yes**. The script relaunches itself elevated and continues automatically:

```
✅ LanmanServer stopped and disabled.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  RESTART YOUR PC NOW — use Restart, not Shut Down.

  After restarting, just start CloudinatorFTP normally.
  Port 445 will work automatically — no further action needed.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Flip SMB_ENABLED to True in config.py now? [y/N]: y
✅ SMB_ENABLED set to True and saved.
```

**Restart the PC** (a real Restart — see the Fast Startup note below), then start CloudinatorFTP normally. That's it, permanently, until you explicitly undo it.

> **Why this script never reboots for you:** it will only ever *tell* you to restart, never execute one itself, under any circumstance. You decide when that happens.

> **Why "Restart," not "Shut Down":** Windows' Fast Startup (on by default on most consumer installs) makes a shutdown/power-on cycle hibernate-and-resume the kernel session rather than truly reinitializing it. Only **Restart** guarantees the LanmanServer change actually takes effect.

### 🐧 Linux

Grants the Python binary a capability to bind port 445 without root — takes effect **immediately**, no restart needed.

**As root:**
```
1. Allow CloudinatorFTP to use port 445 (one-time setup)
Select (1-3): 1

This grants Python permission to bind port 445 without root,
via a one-time capability grant (setcap). Takes effect
immediately — no restart needed, unlike Windows.

Running: setcap cap_net_bind_service=+ep /usr/bin/python3.12
✅ Done. Port 445 will work immediately, no root needed from now on.
```

**As a regular user**, it gives you the exact command to run yourself rather than silently trying to escalate:
```
This needs root. Run this exact command yourself, then start
CloudinatorFTP normally — no need to re-run this script after:

   sudo setcap cap_net_bind_service=+ep /usr/bin/python3.12

Note: this applies to that exact Python binary path. If you
rebuild your virtualenv or switch interpreters later, you'll
need to run it again for the new path.
```

This has been verified directly: a freshly-created, genuinely non-root user successfully bound port 445 immediately after this exact command was applied — no further steps, no restart.

### 📱 Android (Termux)

**Rooted devices:** rather than `setcap` (its behavior on Android is unpredictable — SELinux policy varies significantly across devices and rooting methods, and a granted capability can silently fail to actually apply at runtime), the script points you at the reliable option instead:

```
su -c 'python prod_server.py'
# or, if you use tsu:
tsu
python prod_server.py
```

Running the server itself as root can bind port 445 directly, no extra setup step, no SELinux ambiguity.

**Non-rooted devices:** there's no path to port 445 at all. CloudinatorFTP automatically uses port 8445 instead — nothing further to do.

---

## Connecting to the Share

### Port 445 (after setup)

Standard SMB — works with any client, any Windows version:
```cmd
net use X: \\SERVER-IP\SharedFolder /persistent:yes
```

### Port 8445 (fallback, no setup done yet)

This is where it gets platform-specific:

| Client | Can map a non-445 port? |
|---|---|
| **Windows 11 24H2+ / Server 2025+** | ✅ Yes, via `/TCPPORT:` |
| **Windows 10, older Windows 11** | ❌ No native way at all |
| **macOS Finder** | Generally no for custom ports via standard UI |
| **Linux (smbclient/cifs-utils)** | ✅ Yes, `-p` / `port=` option supported |

**Windows 11 24H2+ / Server 2025+ only:**
```cmd
net use X: \\SERVER-IP\SharedFolder /TCPPORT:8445 /persistent:yes
```

> ⚠️ The familiar `\\server@port\share` trick does **not** work here — that syntax is specific to WebDAV (it forces a fallback to HTTP regardless of the port given), not generic SMB. There is no equivalent trick for older Windows clients; if you're on Windows 10 or pre-24H2 Windows 11, the only way to use the real network-drive experience is to run `smb_setup.py` and get port 445 working.

**Linux:**
```bash
sudo mount -t cifs -o port=8445,username=admin //SERVER-IP/SharedFolder /mnt/cloudinator
```

---

## Password Resets and SMB Credentials

SMB uses NTLM authentication — a challenge-response protocol where the plaintext password is **never sent over the wire**. This means CloudinatorFTP's SMB server must already know a special hash of your password (called an NT hash) to verify a login — it can't just check it against the bcrypt hash used for the web UI.

**What this means practically:**

- New users created *after* SMB support was added get full SMB access immediately — no extra step.
- Users that existed *before* (including your existing `admin`/`guest` accounts on a live server) need their **password reset once** — even resetting it to the same value works — before SMB will accept their login.
- Check who still needs this:
  ```bash
  python
  >>> from database import db
  >>> db.users_missing_nt_hash()
  ['admin', 'guest']
  ```
- Reset via `create_user.py` (change password) or the web UI, same as any normal password change.

This is an inherent property of NTLM, not a CloudinatorFTP limitation — every SMB server, including real Windows and Samba, has the same constraint.

---

## Undoing the Setup

### Windows

```
python smb_setup.py
→ 2. Undo — restore native Windows file sharing
```

Same confirm → elevate → restart shape, in reverse. Restores `LanmanServer` to its exact original startup type (not just blindly "Automatic" — if it was `Disabled` before CloudinatorFTP ever touched it, e.g. by IT policy, it goes back to `Disabled`, not turned on).

### Linux

There's nothing to undo — `setcap` doesn't need reverting unless you specifically want to revoke it:
```bash
sudo setcap -r $(readlink -f $(which python3))
```

### Android

Nothing was changed by the script in the first place (it only gave guidance) — nothing to undo.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `[Errno 22] Invalid argument` on import | Defender quarantine — see [Step 2](#step-2--the-antivirus-problem-windows) |
| "not running elevated" during setup | Click **Yes** on the UAC prompt when it appears; the script relaunches itself, you don't need to manually run as admin first |
| Port 445 still unavailable after restart | Confirm you used **Restart**, not Shut Down (Fast Startup). Still failing? Check what's holding it: `netstat -ano \| findstr :445` |
| `smb_setup.py` says "already stopped" but 445 still won't bind | Something else has claimed it (another app, a VPN client, etc.) — `netstat -ano \| findstr :445` shows the PID holding it |
| User can't log in over SMB despite correct password | Check `db.users_missing_nt_hash()` — reset their password once |
| Older Windows client can't map the 8445 fallback | Expected — only Windows 11 24H2+/Server 2025+ support `/TCPPORT:`. Run `smb_setup.py` to get real port 445 instead |
| `setcap` fails with "command not found" | Install it: `sudo apt install libcap2-bin` (Debian/Ubuntu) |
| Rooted Termux, `setcap` doesn't seem to work | Expected — this is exactly why the script doesn't attempt `setcap` on Android at all. Run the server via `su -c` / `tsu` instead |

---

## FAQ

**Q: Do I have to use SMB? Can I just use WebDAV instead?**
A: Yes — WebDAV gives the same "mapped network drive" experience on Windows/macOS/Linux with zero antivirus drama and no reboot requirement. SMB is mainly worth the extra setup if you need legacy-client compatibility or specifically want `\\HOST\Share` UNC paths.

**Q: Will running `smb_setup.py`'s Windows action break my ability to access other network shares?**
A: No. Windows splits SMB into two independent services: `LanmanServer` (hosting — what we stop) and `LanmanWorkstation` (client — accessing *other* shares, completely untouched). Win+R `\\othernas\share`, mapped drives to other PCs, Network folder browsing — all unaffected.

**Q: I have a real folder shared natively from Windows already (`Get-SmbShare` shows it) — what happens to it?**
A: If it's the *same* folder as your CloudinatorFTP `ROOT_DIR`, nothing changes from the client's perspective — same path, same port, just answered by CloudinatorFTP instead of Windows (though authentication switches to CloudinatorFTP's own accounts, and permissions collapse to readwrite/readonly instead of fine-grained NTFS ACLs). If it's a *different* folder, that specific share stops working — `smb_setup.py` doesn't know about or migrate unrelated native shares.

**Q: Why does this need a restart but the other protocols don't?**
A: Windows' SMB hosting is bound at the kernel driver level (`srv2.sys`/`srvnet.sys`), not just a userspace service flag — disabling the service doesn't release that binding until the next true boot. This is a Windows architecture detail, not something CloudinatorFTP can work around.

**Q: Can `smb_setup.py` itself reboot my PC automatically?**
A: No, by design, under any circumstance. It will only ever print a message asking you to do it yourself, whenever you're ready.