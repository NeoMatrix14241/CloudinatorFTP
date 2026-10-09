"""
routes/previews.py - Office and archive preview routes: /office_preview/* and /archive_preview/*
(Phase 5 of the split, CLAUDE.md 4.73).

Moved verbatim from app.py. The blocking *_sync helpers stay plain functions and are run with
asyncio.to_thread by their routes. Gets shared objects via `from core import ...`; imports no
other route module.
"""

from core import app, login_required

from quart import jsonify, request
import os
import asyncio
import logging
import zipfile
from config import ROOT_DIR
import storage


@app.route("/office_preview/<path:path>")
@login_required
async def office_preview(path):
    """Thin async wrapper — see _office_preview_sync. mammoth/openpyxl/
    python-pptx document conversion is CPU/IO-heavy synchronous work; same
    reasoning as archive_preview's wrapper above."""
    return await asyncio.to_thread(_office_preview_sync, path)


def _office_preview_sync(path):
    """Convert Office documents (docx, xlsx, pptx) to structured data for browser preview."""
    import html as html_lib

    if not storage.is_safe_path(path):
        return jsonify({"error": "Invalid file path"}), 400
    full_path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return jsonify({"error": "File not found"}), 404

    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    try:
        # ── DOCX ──────────────────────────────────────────────────────────────
        if ext in ("docx", "doc"):
            import mammoth

            with open(full_path, "rb") as f:
                result = mammoth.convert_to_html(f)
            return jsonify({"type": "docx", "html": result.value})

        # ── XLSX / XLS ────────────────────────────────────────────────────────
        elif ext in ("xlsx", "xls"):
            import openpyxl

            MAX_ROWS = 500
            MAX_COLS = 50
            wb = openpyxl.load_workbook(full_path, read_only=True, data_only=True)
            sheets = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = []
                for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
                    if r_idx >= MAX_ROWS:
                        break
                    cells = [
                        html_lib.escape(str(c)) if c is not None else ""
                        for c in list(row)[:MAX_COLS]
                    ]
                    rows.append(cells)
                sheets.append(
                    {
                        "name": html_lib.escape(sheet_name),
                        "rows": rows,
                        "truncated": ws.max_row is not None and ws.max_row > MAX_ROWS,
                    }
                )
            wb.close()
            return jsonify({"type": "xlsx", "sheets": sheets})

        # ── CSV ───────────────────────────────────────────────────────────────────────
        elif ext == "csv":
            import csv as csv_mod

            MAX_ROWS = 500
            rows = []
            with open(full_path, newline="", encoding="utf-8", errors="replace") as f:
                reader = csv_mod.reader(f)
                for i, row in enumerate(reader):
                    if i >= MAX_ROWS:
                        break
                    rows.append([html_lib.escape(str(c)) for c in row])
            truncated = False
            try:
                # cheap line-count check without re-reading the whole file
                with open(full_path, encoding="utf-8", errors="replace") as f:
                    total_lines = sum(1 for _ in f)
                truncated = total_lines > MAX_ROWS
            except Exception:
                pass
            return jsonify(
                {
                    "type": "xlsx",  # reuse the same xlsx renderer on the frontend
                    "sheets": [{"name": "CSV", "rows": rows, "truncated": truncated}],
                }
            )

        # ── PPTX / PPT ────────────────────────────────────────────────────────
        elif ext in ("pptx", "ppt"):
            from pptx import Presentation

            try:
                from pptx.enum.shapes import PP_PLACEHOLDER

                _HAS_PLACEHOLDER_ENUM = True
            except ImportError:
                _HAS_PLACEHOLDER_ENUM = False

            prs = Presentation(full_path)
            slides = []
            for i, slide in enumerate(prs.slides):
                shapes_data = []
                for shape in slide.shapes:
                    if not shape.has_text_frame:
                        continue
                    paragraphs = []
                    for para in shape.text_frame.paragraphs:
                        text = para.text.strip()
                        if not text:
                            continue
                        paragraphs.append(
                            {"text": html_lib.escape(text), "level": para.level}
                        )
                    if not paragraphs:
                        continue
                    is_title = False
                    if _HAS_PLACEHOLDER_ENUM:
                        try:
                            if (
                                shape.is_placeholder
                                and shape.placeholder_format.type
                                in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
                            ):
                                is_title = True
                        except Exception:
                            pass
                    shapes_data.append({"is_title": is_title, "paragraphs": paragraphs})
                slides.append({"index": i + 1, "shapes": shapes_data})
            return jsonify({"type": "pptx", "slides": slides, "total": len(slides)})

        else:
            return jsonify({"error": f"Unsupported format: .{ext}"}), 400

    except ImportError as e:
        missing = str(e).split("'")[1] if "'" in str(e) else str(e)
        return (
            jsonify(
                {
                    "error": f"Missing package '{missing}'. Install with: pip install mammoth openpyxl python-pptx"
                }
            ),
            500,
        )
    except Exception as e:
        logging.exception(f"Office preview failed for {path}")
        return jsonify({"error": f"Preview failed: {str(e)}"}), 500


@app.route("/archive_preview/<path:path>")
@login_required
async def archive_preview(path):
    """Thin async wrapper — see _archive_preview_sync for the actual logic.
    Reading/decompressing archive contents (zip/tar/7z/rar, up to 10,000
    entries, plus password-verification decompression) is CPU/IO-heavy
    synchronous work. Running it directly in this coroutine would freeze
    Hypercorn's single event loop for as long as it takes, stalling every
    other concurrent request — login, other page loads, video preview,
    everything — for the whole duration. Verified request.args/jsonify()
    still resolve correctly from inside asyncio.to_thread (Quart's context
    vars propagate into the worker thread automatically)."""
    return await asyncio.to_thread(_archive_preview_sync, path)


def _archive_preview_sync(path):
    """List contents of an archive file for in-browser preview.

    Supports: .zip, .rar, .7z, .tar, .tar.gz, .tar.bz2, .tar.xz
    Optional query param: ?password=<password>

    Returns JSON:
      { type, entries: [{name, is_dir, size, compressed_size, modified}],
        total_entries, total_size, truncated, encrypted }

    Error responses (always JSON):
      {"error": "password_required"}   -> HTTP 401
      {"error": "wrong_password"}      -> HTTP 401
      {"error": "<message>"}           -> HTTP 400/500
    """
    import html as html_lib
    import datetime

    if not storage.is_safe_path(path):
        return jsonify({"error": "Invalid file path"}), 400
    full_path = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return jsonify({"error": "File not found"}), 404

    # Resolve compound extensions first (must check before splitting on last '.')
    lower = path.lower()
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        ext = "tar.gz"
    elif lower.endswith(".tar.bz2") or lower.endswith(".tbz2"):
        ext = "tar.bz2"
    elif lower.endswith(".tar.xz") or lower.endswith(".txz"):
        ext = "tar.xz"
    else:
        ext = lower.rsplit(".", 1)[-1] if "." in lower else ""

    password = request.args.get("password") or None
    MAX_ENTRIES = 10_000

    def _fmt_zip_date(dt_tuple):
        try:
            y, mo, d, h, mi = dt_tuple[:5]
            return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}"
        except Exception:
            return ""

    try:
        # ── ZIP ───────────────────────────────────────────────────────────────
        if ext == "zip":
            # Use pyzipper when available — it handles WinZip AES encryption
            # (compression method 99). Python's stdlib zipfile cannot decrypt
            # AES zips: both correct and wrong passwords raise the same
            # NotImplementedError("That compression method is not supported"),
            # making password verification completely impossible without it.
            try:
                import pyzipper

                _zip_open = pyzipper.AESZipFile
            except ImportError:
                _zip_open = zipfile.ZipFile

            with _zip_open(full_path, "r") as zf:
                info_list = zf.infolist()
                needs_pw = any(i.flag_bits & 0x1 for i in info_list)

                if needs_pw:
                    if not password:
                        return jsonify({"error": "password_required"}), 401
                    pw_bytes = password.encode("utf-8")
                    zf.setpassword(pw_bytes)
                    # Verify the password by reading the first non-empty file.
                    # pyzipper raises RuntimeError("Bad password") on wrong password.
                    # stdlib raises RuntimeError("Bad password") for standard crypto
                    # or BadZipFile — but cannot verify AES (use pyzipper for that).
                    for info in info_list:
                        if not info.is_dir() and info.file_size > 0:
                            try:
                                zf.read(info.filename)
                            except RuntimeError as e:
                                if (
                                    "password" in str(e).lower()
                                    or "bad" in str(e).lower()
                                ):
                                    return jsonify({"error": "wrong_password"}), 401
                                raise
                            except zipfile.BadZipFile:
                                return jsonify({"error": "wrong_password"}), 401
                            break

                entries, total_size = [], 0
                for info in info_list[:MAX_ENTRIES]:
                    total_size += info.file_size
                    entries.append(
                        {
                            "name": html_lib.escape(info.filename),
                            "is_dir": info.is_dir(),
                            "size": info.file_size,
                            "compressed_size": info.compress_size,
                            "modified": _fmt_zip_date(info.date_time),
                        }
                    )

                return jsonify(
                    {
                        "type": "zip",
                        "entries": entries,
                        "total_entries": len(info_list),
                        "total_size": total_size,
                        "truncated": len(info_list) > MAX_ENTRIES,
                        "encrypted": needs_pw,
                    }
                )

        # ── TAR family (no native password support) ───────────────────────────
        elif ext in (
            "tar",
            "tar.gz",
            "tgz",
            "tar.bz2",
            "tbz2",
            "tar.xz",
            "txz",
            "gz",
            "bz2",
        ):
            import tarfile as _tf

            mode_map = {
                "tar": "r:",
                "tar.gz": "r:gz",
                "tgz": "r:gz",
                "tar.bz2": "r:bz2",
                "tbz2": "r:bz2",
                "tar.xz": "r:xz",
                "txz": "r:xz",
                "gz": "r:gz",
                "bz2": "r:bz2",
            }
            mode = mode_map.get(ext, "r:*")
            try:
                with _tf.open(full_path, mode) as tf:
                    members = tf.getmembers()
                    entries, total_size = [], 0
                    for m in members[:MAX_ENTRIES]:
                        is_dir = m.isdir()
                        size = 0 if is_dir else m.size
                        total_size += size
                        try:
                            modified = (
                                datetime.datetime.fromtimestamp(m.mtime).strftime(
                                    "%Y-%m-%d %H:%M"
                                )
                                if m.mtime
                                else ""
                            )
                        except Exception:
                            modified = ""
                        name = (
                            m.name
                            if not (is_dir and not m.name.endswith("/"))
                            else m.name + "/"
                        )
                        entries.append(
                            {
                                "name": html_lib.escape(name),
                                "is_dir": is_dir,
                                "size": size,
                                "compressed_size": None,
                                "modified": modified,
                            }
                        )
                    return jsonify(
                        {
                            "type": "tar",
                            "entries": entries,
                            "total_entries": len(members),
                            "total_size": total_size,
                            "truncated": len(members) > MAX_ENTRIES,
                            "encrypted": False,
                        }
                    )
            except _tf.TarError as e:
                return jsonify({"error": f"Could not read archive: {e}"}), 500

        # ── 7Z ────────────────────────────────────────────────────────────────
        elif ext == "7z":
            try:
                import py7zr
                import py7zr.exceptions as _7zexc
            except ImportError:
                return (
                    jsonify(
                        {
                            "error": "Missing package 'py7zr'. Install with: pip install py7zr"
                        }
                    ),
                    500,
                )

            # FIX: py7zr's needs_password() only returns True when the archive
            # was opened WITH a password — useless for probing. Instead, open
            # without a password and call list(); if the archive is encrypted,
            # py7zr raises PasswordRequired during list() / decompressor setup.
            needs_pw = False
            try:
                with py7zr.SevenZipFile(full_path, mode="r") as _probe:
                    _probe.list()  # raises PasswordRequired if encrypted
            except _7zexc.PasswordRequired:
                needs_pw = True
            except Exception:
                pass  # other errors caught later when opening for real

            if needs_pw and not password:
                return jsonify({"error": "password_required"}), 401

            try:
                kwargs = {"mode": "r"}
                if password:
                    kwargs["password"] = password

                with py7zr.SevenZipFile(full_path, **kwargs) as archive:
                    # list() will raise PasswordRequired if still wrong
                    try:
                        file_list = archive.list()
                    except _7zexc.PasswordRequired:
                        # Shouldn't happen for correct password, but be safe
                        if needs_pw:
                            return jsonify({"error": "wrong_password"}), 401
                        raise

                    entries, total_size = [], 0
                    for info in file_list[:MAX_ENTRIES]:
                        is_dir = info.is_directory
                        size = (info.uncompressed or 0) if not is_dir else 0
                        compressed = (info.compressed or 0) if not is_dir else 0
                        total_size += size
                        try:
                            modified = (
                                info.creationtime.strftime("%Y-%m-%d %H:%M")
                                if info.creationtime
                                else ""
                            )
                        except Exception:
                            modified = ""
                        name = info.filename
                        if is_dir and not name.endswith("/"):
                            name += "/"
                        entries.append(
                            {
                                "name": html_lib.escape(name),
                                "is_dir": is_dir,
                                "size": size,
                                "compressed_size": compressed,
                                "modified": modified,
                            }
                        )
                    return jsonify(
                        {
                            "type": "7z",
                            "entries": entries,
                            "total_entries": len(file_list),
                            "total_size": total_size,
                            "truncated": len(file_list) > MAX_ENTRIES,
                            "encrypted": needs_pw,
                        }
                    )
            except _7zexc.PasswordRequired:
                return jsonify({"error": "wrong_password"}), 401
            except (_7zexc.Bad7zFile, _7zexc.CrcError) as e:
                if needs_pw:
                    return jsonify({"error": "wrong_password"}), 401
                return jsonify({"error": f"Could not read archive: {e}"}), 500
            except Exception as e:
                err = str(e).lower()
                if needs_pw and any(
                    k in err for k in ("password", "wrong", "bad", "crc", "decrypt")
                ):
                    return jsonify({"error": "wrong_password"}), 401
                return jsonify({"error": f"Could not read archive: {e}"}), 500

        # ── RAR ───────────────────────────────────────────────────────────────
        elif ext == "rar":
            try:
                import rarfile
            except ImportError:
                return (
                    jsonify(
                        {
                            "error": "Missing package 'rarfile'. Install with: pip install rarfile"
                        }
                    ),
                    500,
                )

            try:
                rf = rarfile.RarFile(full_path)
            except rarfile.NotRarFile:
                return jsonify({"error": "Not a valid RAR file"}), 400
            except Exception as e:
                return jsonify({"error": f"Could not open RAR: {e}"}), 500

            with rf:
                parser = rf._file_parser
                header_encrypted = bool(parser and parser.has_header_encryption())

                # ── Case 1: Header encryption (WinRAR "Encrypt file names") ──
                # The file listing itself is encrypted. needs_password() returns
                # False here because no entries were parsed — check the parser flag.
                if header_encrypted:
                    if not password:
                        return jsonify({"error": "password_required"}), 401

                    # FIX: setpassword() takes a str, NOT bytes.
                    # For RAR5, setpassword() re-parses the archive and immediately
                    # raises RarWrongPassword if the PBKDF2 check fails.
                    try:
                        rf.setpassword(password)
                    except rarfile.RarWrongPassword:
                        return jsonify({"error": "wrong_password"}), 401
                    except rarfile.BadRarFile:
                        return jsonify({"error": "wrong_password"}), 401

                    # After correct setpassword, infolist() should now be populated
                    try:
                        info_list = rf.infolist()
                    except (rarfile.PasswordRequired, rarfile.BadRarFile):
                        return jsonify({"error": "wrong_password"}), 401

                    # Paranoia check: if the list is still empty the password was wrong
                    # (can happen with RAR3 header encryption where AES produces garbage)
                    if not info_list:
                        return jsonify({"error": "wrong_password"}), 401

                # ── Case 2: File-level encryption (content encrypted, list visible) ──
                else:
                    info_list = rf.infolist()
                    needs_pw = rf.needs_password()

                    if needs_pw:
                        if not password:
                            return jsonify({"error": "password_required"}), 401

                        # FIX: str, not bytes
                        rf.setpassword(password)

                        # Verify by attempting to read the first non-empty file
                        verified = False
                        for info in info_list:
                            if not info.is_dir() and info.file_size > 0:
                                try:
                                    rf.read(info.filename)
                                    verified = True
                                except (
                                    rarfile.RarWrongPassword,
                                    rarfile.RarCRCError,
                                    rarfile.BadRarFile,
                                    rarfile.PasswordRequired,
                                ):
                                    return jsonify({"error": "wrong_password"}), 401
                                break
                        # No extractable files to verify against — trust the listing
                        if not verified and needs_pw:
                            pass  # Accept — can't verify an all-directory archive

                # ── Build entry list ──────────────────────────────────────────
                entries, total_size = [], 0
                for info in info_list[:MAX_ENTRIES]:
                    is_dir = info.is_dir()
                    size = 0 if is_dir else (info.file_size or 0)
                    compressed = 0 if is_dir else (info.compress_size or 0)
                    total_size += size
                    try:
                        modified = (
                            info.date_time.strftime("%Y-%m-%d %H:%M")
                            if info.date_time
                            else ""
                        )
                    except Exception:
                        modified = ""
                    name = info.filename
                    if is_dir and not name.endswith("/"):
                        name += "/"
                    entries.append(
                        {
                            "name": html_lib.escape(name),
                            "is_dir": is_dir,
                            "size": size,
                            "compressed_size": compressed,
                            "modified": modified,
                        }
                    )

                return jsonify(
                    {
                        "type": "rar",
                        "entries": entries,
                        "total_entries": len(info_list),
                        "total_size": total_size,
                        "truncated": len(info_list) > MAX_ENTRIES,
                        "encrypted": header_encrypted
                        or (not header_encrypted and rf.needs_password()),
                    }
                )

        else:
            return jsonify({"error": f"Unsupported archive format: .{ext}"}), 400

    except Exception as e:
        logging.exception(f"Archive preview failed for {path}")
        return jsonify({"error": f"Preview failed: {e}"}), 500
