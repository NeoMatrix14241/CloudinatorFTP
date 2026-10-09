"""
routes/hls.py - HLS video streaming (Phase 2 of the split, CLAUDE.md 4.70).

Moved verbatim from app.py. Gets shared objects via `from core import ...`; imports no other
route module.
"""

from core import app, login_required

from quart import jsonify, send_file
import os
import json
import asyncio
import threading
import re
import subprocess
import hashlib
from config import (
    ROOT_DIR,
    HLS_MIN_SIZE,
    HLS_FORCE_FORMATS,
    ENABLE_FFMPEG,
)
import storage

# ─────────────────────────────────────────────────────────────────────────────
# HLS Adaptive Streaming  (ffmpeg backend → Video.js frontend)
# ─────────────────────────────────────────────────────────────────────────────

_VIDEO_EXTS_HLS = frozenset(
    [
        "mp4",
        "webm",
        "mov",
        "m4v",
        "mkv",
        "avi",
        "wmv",
        "flv",
        "mpg",
        "mpeg",
        "m2ts",
        "mts",
        "3gp",
        "ogv",
        "ts",
    ]
)

# CRF-based quality ladder — no target bitrate, just a maxrate ceiling.
# Encoding uses -crf 18 (visually near-lossless) + -maxrate/-bufsize to cap
# runaway bitrates on complex scenes, same approach as YouTube.
#
# (name, target_height, maxrate, bufsize, audio_bitrate)
_HLS_BASE_PROFILES = [
    ("2160p", 2160, "40000k", "80000k", "192k"),  # 4K  — ~40 Mbps ceiling
    ("1440p", 1440, "24000k", "48000k", "192k"),  # 2K  — ~24 Mbps ceiling
    ("1080p", 1080, "12000k", "24000k", "192k"),  # matches YouTube Premium
    ("720p", 720, "7500k", "15000k", "128k"),
    ("480p", 480, "4000k", "8000k", "128k"),
    ("360p", 360, "1500k", "3000k", "96k"),
    ("240p", 240, "800k", "1600k", "64k"),
    ("144p", 144, "300k", "600k", "64k"),
]

# High-frame-rate variants — only added when source ≥ 48 fps, for 720p and above.
# Ceilings are ~50% higher than their SDR counterparts to accommodate extra frames.
# (name, target_height, maxrate, bufsize, audio_bitrate)
_HLS_HFR_PROFILES = [
    ("2160p60", 2160, "60000k", "120000k", "192k"),
    ("1440p60", 1440, "36000k", "72000k", "192k"),
    ("1080p60", 1080, "20000k", "40000k", "192k"),
    ("720p60", 720, "12000k", "24000k", "128k"),
]

_HLS_SEG_DURATION = 6  # seconds per HLS segment

# Suppress console windows on Windows when spawning ffmpeg/ffprobe subprocesses.
# CREATE_NO_WINDOW is a Windows-only flag; on Linux/macOS it evaluates to 0 (no-op).
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# HLS cache root lives in the configured cache dir, not inside ROOT_DIR
from paths import get_hls_cache_dir as _get_hls_cache_dir


def _hls_cache_root() -> str:
    """Return (and create) the HLS cache directory from paths configuration."""
    return _get_hls_cache_dir(create=True)


def _hls_cache_key(full_path: str) -> str:
    """
    Stable 32-char hex key derived from (file_size, mtime).
    A renamed/moved file whose content is unchanged reuses the same key
    and avoids a full re-transcode.
    """
    try:
        st = os.stat(full_path)
        fingerprint = f"{st.st_size}:{st.st_mtime}"
    except OSError:
        fingerprint = f"{full_path}:0"
    return hashlib.md5(fingerprint.encode()).hexdigest()


def _hls_output_dir(cache_key: str) -> str:
    return os.path.join(_hls_cache_root(), cache_key)


_hls_status_lock = threading.Lock()


def _hls_read_status(cache_key: str) -> dict:
    f = os.path.join(_hls_output_dir(cache_key), ".status.json")
    if not os.path.exists(f):
        return {"status": "not_started"}
    try:
        with _hls_status_lock:
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        return {"status": "unknown"}


def _hls_write_status(cache_key: str, data: dict):
    """
    Write .status.json under a threading lock.
    os.replace() is avoided because on Windows it raises PermissionError
    when another thread has the destination file open for reading at the
    same time (WinError 5).  A lock + direct overwrite is safe here because
    every reader also holds the same lock, so reads and writes never race.
    """
    d = _hls_output_dir(cache_key)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, ".status.json")
    with _hls_status_lock:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)


def _probe_video(file_path: str):
    """
    Return (width, height, has_audio, duration_secs, fps) via ffprobe.
    fps is the real/exact frame rate from r_frame_rate (e.g. 59.94, 60.0, 30.0).
    Falls back to (0, 0, False, 0.0, 0.0) on any error.
    """
    try:
        _ffmpeg_bin = _resolve_ffmpeg()
        _ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        ffprobe_bin = os.path.join(os.path.dirname(_ffmpeg_bin), _ffprobe_name)
        r = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if r.returncode != 0:
            return 0, 0, False, 0.0, 0.0
        data = json.loads(r.stdout)
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        w = h = 0
        has_audio = False
        fps = 0.0
        found_video = False
        for s in streams:
            if s.get("codec_type") == "video" and not found_video:
                # Skip attached pictures (cover art embedded in MKV/MP4).
                # ffprobe reports these as video streams but they are tiny
                # images (e.g. 240×240) and would wrongly cap the quality ladder.
                disposition = s.get("disposition") or {}
                if disposition.get("attached_pic"):
                    continue
                w = int(s.get("width") or 0)
                h = int(s.get("height") or 0)
                # r_frame_rate is exact rational e.g. "60000/1001" or "30/1"
                rfr = s.get("r_frame_rate") or s.get("avg_frame_rate") or "0/1"
                try:
                    num, den = rfr.split("/")
                    fps = float(int(num)) / float(int(den)) if int(den) != 0 else 0.0
                except Exception:
                    fps = 0.0
                found_video = True  # keep iterating — audio streams may come after
            elif s.get("codec_type") == "audio":
                has_audio = True
        try:
            duration = float(fmt.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        return w, h, has_audio, duration, fps
    except Exception:
        return 0, 0, False, 0.0, 0.0


def _probe_streams(file_path: str):
    """
    Return (audio_streams, sub_streams) with per-track language/label info.

    audio_streams — list of dicts, one per audio track:
        {"index": int, "lang": str, "label": str, "dir_name": str}
    sub_streams   — list of dicts, only TEXT-based subtitle tracks (not PGS/VOBSUB):
        {"src_idx": int, "lang": str, "label": str}

    Falls back to ([], []) on any error.
    """
    _LANG_NAMES = {
        "eng": "English",
        "spa": "Spanish",
        "fra": "French",
        "fre": "French",
        "deu": "German",
        "ger": "German",
        "ita": "Italian",
        "por": "Portuguese",
        "jpn": "Japanese",
        "kor": "Korean",
        "zho": "Chinese",
        "chi": "Chinese",
        "ara": "Arabic",
        "rus": "Russian",
        "hin": "Hindi",
        "tur": "Turkish",
        "pol": "Polish",
        "nld": "Dutch",
        "dut": "Dutch",
        "swe": "Swedish",
        "nor": "Norwegian",
        "dan": "Danish",
        "fin": "Finnish",
        "heb": "Hebrew",
        "tha": "Thai",
        "vie": "Vietnamese",
        "ind": "Indonesian",
        "ces": "Czech",
        "cze": "Czech",
        "slk": "Slovak",
        "slo": "Slovak",
        "hun": "Hungarian",
        "ron": "Romanian",
        "rum": "Romanian",
        "bul": "Bulgarian",
        "hrv": "Croatian",
        "srp": "Serbian",
        "ukr": "Ukrainian",
        "cat": "Catalan",
        "ell": "Greek",
        "gre": "Greek",
    }
    # Only extract these text-based subtitle codecs (not bitmap formats like PGS/VOBSUB)
    _TEXT_SUB_CODECS = frozenset(
        [
            "subrip",
            "srt",
            "ass",
            "ssa",
            "webvtt",
            "mov_text",
            "text",
            "jacosub",
            "microdvd",
            "realtext",
            "sami",
            "stl",
            "pjs",
            "vplayer",
        ]
    )
    try:
        _ffmpeg_bin = _resolve_ffmpeg()
        _ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        ffprobe_bin = os.path.join(os.path.dirname(_ffmpeg_bin), _ffprobe_name)
        r = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if r.returncode != 0:
            return [], []
        streams = json.loads(r.stdout).get("streams", [])

        audio_streams = []
        sub_streams = []
        used_dir_names: set = set()
        sub_src_idx = 0  # running index over ALL subtitle streams in the file

        for s in streams:
            tags = s.get("tags") or {}
            raw_lang = (tags.get("language") or "").lower().strip()[:3]
            title = (tags.get("title") or "").strip()
            codec = s.get("codec_name", "").lower()

            if s.get("codec_type") == "audio":
                i = len(audio_streams)
                lang = raw_lang or f"aud{i}"
                label = title or _LANG_NAMES.get(raw_lang, "") or f"Track {i + 1}"
                # Build a filesystem-safe unique directory name
                safe = re.sub(r"[^a-zA-Z0-9]", "", lang)[:8] or f"aud{i}"
                dir_name = f"aud_{safe}"
                if dir_name in used_dir_names:
                    dir_name = f"aud_{safe}_{i}"
                used_dir_names.add(dir_name)
                audio_streams.append(
                    {
                        "index": i,
                        "lang": lang,
                        "label": label,
                        "dir_name": dir_name,
                    }
                )

            elif s.get("codec_type") == "subtitle":
                if codec in _TEXT_SUB_CODECS:
                    j = len(sub_streams)
                    lang = raw_lang or f"sub{j}"
                    label = (
                        title or _LANG_NAMES.get(raw_lang, "") or f"Subtitle {j + 1}"
                    )
                    sub_streams.append(
                        {
                            "src_idx": sub_src_idx,  # for -map 0:s:N
                            "lang": lang,
                            "label": label,
                        }
                    )
                sub_src_idx += 1

        return audio_streams, sub_streams
    except Exception:
        return [], []


def _resolve_ffmpeg() -> str:
    """Return the ffmpeg executable path, searching PATH then common Windows install dirs."""
    import shutil as _shutil

    found = _shutil.which("ffmpeg")
    if found:
        return found
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
        os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin"),
        os.path.expandvars(r"%ProgramFiles(x86)%\ffmpeg\bin"),
        r"C:\ProgramData\chocolatey\bin",
        os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
        r"C:\ffmpeg\bin",
        r"C:\tools\ffmpeg\bin",
    ]
    for base in candidates:
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            for fname in files:
                if fname.lower() in ("ffmpeg.exe", "ffmpeg"):
                    return os.path.join(root, fname)
            if root.count(os.sep) - base.count(os.sep) >= 5:
                dirs.clear()
    return "ffmpeg"  # last resort


def _ffmpeg_available() -> bool:
    """Return True if ffmpeg is both enabled in config AND installed/executable.

    ENABLE_FFMPEG=True  + installed   → True  (full HLS)
    ENABLE_FFMPEG=True  + not found   → False (graceful raw fallback, same as before)
    ENABLE_FFMPEG=False               → False (intentionally disabled, raw fallback)
    """
    import shutil as _shutil

    if not ENABLE_FFMPEG:
        return False

    bin_path = _resolve_ffmpeg()
    if bin_path == "ffmpeg" and not _shutil.which("ffmpeg"):
        return False
    try:
        subprocess.run(
            [bin_path, "-version"],
            capture_output=True,
            timeout=5,
            check=True,
            creationflags=_SUBPROCESS_FLAGS,
        )
        return True
    except Exception:
        return False


def _run_hls_transcode(file_path: str, cache_key: str):
    """
    Background daemon thread: transcode video → multi-quality HLS.

    Profile selection:
      • Standard profiles (144p→4K, capped at 30 fps) are included up to the
        source height.
      • HFR profiles (720p60→4K60) are added only when the source is ≥ 48 fps,
        for heights ≤ source height and ≥ 720.
      • Each standard profile applies an fps=30 cap via filter when the source
        is HFR; HFR profiles pass the source frame-rate through unchanged.
      • GOP size is set per-stream to 2 × effective_fps (2-second keyframe
        interval) so seeking stays accurate at any frame-rate.

    Writes live progress 0-100 to .status.json via -progress pipe:1 parsing.
    Survives frontend refresh — never interrupted by the browser.
    """
    output_dir = _hls_output_dir(cache_key)
    os.makedirs(output_dir, exist_ok=True)
    _hls_write_status(cache_key, {"status": "processing", "progress": 0})

    try:
        _, src_height, has_audio, duration_secs, src_fps = _probe_video(file_path)
        audio_streams, sub_streams = _probe_streams(file_path)

        # Use multi-audio agroup mode when the source has 2+ audio tracks.
        # Single-audio keeps the simpler muxed approach for maximum compatibility.
        use_multi_audio = has_audio and len(audio_streams) > 1

        # Treat 48+ fps sources as HFR (covers both 50 Hz / PAL and 59.94/60 Hz)
        is_hfr = src_fps >= 48.0

        # ── Build active profile list ─────────────────────────────────────────
        # Each entry: (name, height, fps_cap, maxr, bufs, abr)
        #   fps_cap = 30    → standard profile; filter limits fps to 30 when HFR source
        #   fps_cap = None  → HFR profile; source frame-rate passes through unchanged
        # ── Build active profile list ─────────────────────────────────────────
        # Each entry: (name, height, fps_cap, maxr, bufs, abr)\n        #   fps_cap = 30    → standard profile; filter limits fps to 30 when HFR source
        #   fps_cap = None  → HFR profile; source frame-rate passes through unchanged
        profiles = []

        # Find the smallest standard profile height that is >= src_height.
        # This is the "ceiling rung" — we include it so that non-standard source
        # heights (open matte, anamorphic, etc.) are not silently capped one rung
        # lower than they should be.  e.g. a 1040p open matte film gets a 1080p
        # profile (tiny upscale) rather than being stuck at 720p.
        # src_height == 0 means probe failed — use 1080 as a safe ceiling.
        effective_src = src_height if src_height > 0 else 1080
        base_heights = [h for _, h, *_ in _HLS_BASE_PROFILES]
        ceiling_h = next(
            (h for h in sorted(base_heights) if h >= effective_src), effective_src
        )

        for name, h, maxr, bufs, abr in _HLS_BASE_PROFILES:
            if h < ceiling_h:
                profiles.append((name, h, 30, maxr, bufs, abr))
            elif h == ceiling_h:
                # If src exactly matches a rung, use it as-is.
                # If src is between rungs (e.g. 1040p), encode at the real source
                # height and label it accurately (e.g. "1040p") — no upscaling.
                actual_h = effective_src if effective_src < ceiling_h else ceiling_h
                actual_name = f"{actual_h}p" if actual_h != ceiling_h else name
                profiles.append((actual_name, actual_h, 30, maxr, bufs, abr))

        if is_hfr:
            hfr_heights = [h for _, h, *_ in _HLS_HFR_PROFILES]
            ceiling_hfr = next(
                (h for h in sorted(hfr_heights) if h >= effective_src), effective_src
            )
            for name, h, maxr, bufs, abr in _HLS_HFR_PROFILES:
                if h < ceiling_hfr and h >= 720:
                    profiles.append((name, h, None, maxr, bufs, abr))
                elif h == ceiling_hfr:
                    actual_h = (
                        effective_src if effective_src < ceiling_hfr else ceiling_hfr
                    )
                    actual_name = f"{actual_h}p60" if actual_h != ceiling_hfr else name
                    profiles.append((actual_name, actual_h, None, maxr, bufs, abr))

        if not profiles:
            # Absolute fallback: lowest rung of the standard ladder
            name, h, maxr, bufs, abr = _HLS_BASE_PROFILES[-1]
            profiles = [(name, h, 30, maxr, bufs, abr)]

        n = len(profiles)

        for name, *_ in profiles:
            os.makedirs(os.path.join(output_dir, name), exist_ok=True)

        # Pre-create audio rendition subdirs too — ffmpeg won't create them
        # and without them the init.mp4 falls back to CWD (project root).
        if use_multi_audio:
            for aud in audio_streams:
                os.makedirs(os.path.join(output_dir, aud["dir_name"]), exist_ok=True)

        # ── Build filter_complex ──────────────────────────────────────────────
        # For standard profiles on an HFR source, append ",fps=fps=30" so the
        # 30-fps streams are correctly limited.  HFR profiles get no fps filter.
        splits = "".join(f"[vsp{i}]" for i in range(n))
        filter_parts = [f"[0:v]split={n}{splits}"]
        for i, (name, h, fps_cap, *_) in enumerate(profiles):
            fps_filter = (
                f",fps=fps={fps_cap}" if (fps_cap is not None and is_hfr) else ""
            )
            filter_parts.append(f"[vsp{i}]scale=-2:{h}{fps_filter}[vout{i}]")
        filter_complex = "; ".join(filter_parts)

        cmd = [
            _resolve_ffmpeg(),
            "-y",
            "-i",
            file_path,
            "-filter_complex",
            filter_complex,
        ]

        for i in range(n):
            cmd += ["-map", f"[vout{i}]"]

        # ── Audio stream mapping ──────────────────────────────────────────────
        # Multi-audio (2+ tracks): map each unique audio track once — ffmpeg
        # will create separate audio-only HLS renditions via agroup in var_stream_map.
        # Single-audio: duplicate the one track per quality profile (muxed, existing behaviour).
        if use_multi_audio:
            for aud in audio_streams:
                cmd += ["-map", f"0:a:{aud['index']}"]
        elif has_audio:
            for _ in range(n):
                cmd += ["-map", "0:a:0"]

        # ── Per-stream video encoder options (CRF mode) ──────────────────────
        # -crf 18 targets perceptual near-lossless quality; -maxrate/-bufsize
        # cap the bitrate ceiling so complex scenes don't explode, identical
        # to how YouTube's encoder pipeline works.
        for i, (name, h, fps_cap, maxr, bufs, abr) in enumerate(profiles):
            eff_fps = (fps_cap if fps_cap is not None else src_fps) or 30
            gop = max(48, int(round(eff_fps * 2)))
            cmd += [
                f"-c:v:{i}",
                "libx264",
                f"-crf:v:{i}",
                "22",
                f"-maxrate:v:{i}",
                maxr,
                f"-bufsize:v:{i}",
                bufs,
                f"-preset:v:{i}",
                "fast",
                f"-g:v:{i}",
                str(gop),
                f"-keyint_min:v:{i}",
                str(gop),
                f"-sc_threshold:v:{i}",
                "0",
            ]

        # ── Audio encoder options ─────────────────────────────────────────────
        if use_multi_audio:
            # Separate audio renditions: use best-quality AAC for all tracks
            for i, aud in enumerate(audio_streams):
                cmd += [f"-c:a:{i}", "aac", f"-b:a:{i}", "192k", f"-ar:a:{i}", "48000"]
        elif has_audio:
            # Muxed single-audio: per-profile bitrate (lower for low-quality rungs)
            for i, (name, h, fps_cap, maxr, bufs, abr) in enumerate(profiles):
                cmd += [f"-c:a:{i}", "aac", f"-b:a:{i}", abr, "-ar", "48000"]

        # ── var_stream_map ────────────────────────────────────────────────────
        if use_multi_audio:
            # Audio-only renditions first (agroup ties them to the video streams)
            aud_parts = []
            for i, aud in enumerate(audio_streams):
                default_flag = "YES" if i == 0 else "NO"
                aud_parts.append(
                    f"a:{i},agroup:aud,language:{aud['lang']},"
                    f"name:{aud['dir_name']},default:{default_flag}"
                )
            # Video-only renditions reference the same agroup
            vid_parts = [
                f"v:{i},agroup:aud,name:{name}" for i, (name, *_) in enumerate(profiles)
            ]
            vsm = " ".join(aud_parts + vid_parts)
        elif has_audio:
            vsm = " ".join(
                f"v:{i},a:{i},name:{name}" for i, (name, *_) in enumerate(profiles)
            )
        else:
            vsm = " ".join(
                f"v:{i},name:{name}" for i, (name, *_) in enumerate(profiles)
            )

        seg_tpl = os.path.join(output_dir, "%v", "seg%03d.m4s")
        list_tpl = os.path.join(output_dir, "%v", "index.m3u8")

        cmd += [
            "-progress",
            "pipe:1",
            "-nostats",
            "-f",
            "hls",
            "-hls_time",
            str(_HLS_SEG_DURATION),
            "-hls_playlist_type",
            "vod",
            "-hls_segment_type",
            "fmp4",
            "-hls_fmp4_init_filename",
            os.path.join(output_dir, "%v", "init.mp4"),
            # absolute path + %v → files land in output_dir/%v/init.mp4
            # ffmpeg writes the full path as EXT-X-MAP:URI — we fix
            # that to just "init.mp4" in _fix_fmp4_init_uris() below
            "-hls_flags",
            "independent_segments",
            "-var_stream_map",
            vsm,
            "-master_pl_name",
            "master.m3u8",
            "-hls_segment_filename",
            seg_tpl,
            list_tpl,
        ]

        profile_names = [p[0] for p in profiles]
        print(
            f"🎬 HLS transcode start: {os.path.basename(file_path)}  "
            f"src={src_height}p {'HFR({:.2f}fps)'.format(src_fps) if is_hfr else '{:.2f}fps'.format(src_fps)}  "
            f"profiles={profile_names}  duration={duration_secs:.1f}s",
            flush=True,
        )

        # Resolve ffmpeg to an absolute path before changing cwd —
        # on Windows, a bare "ffmpeg" would fail to resolve once cwd changes.
        import shutil as _shutil

        if not os.path.isabs(cmd[0]):
            abs_ffmpeg = _shutil.which(cmd[0])
            if abs_ffmpeg:
                cmd[0] = abs_ffmpeg

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=output_dir,  # ffmpeg resolves "%v/init.mp4" relative to here
            creationflags=_SUBPROCESS_FLAGS,
        )

        stderr_tail = []
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                print(f"[ffmpeg progress] {key}={val}", flush=True)
                # out_time_ms is in microseconds
                if key == "out_time_ms" and duration_secs > 0:
                    try:
                        pct = min(99, int(int(val) / 1_000_000 / duration_secs * 100))
                        _hls_write_status(
                            cache_key, {"status": "processing", "progress": pct}
                        )
                    except (ValueError, ZeroDivisionError):
                        pass
            else:
                print(f"[ffmpeg] {line}", flush=True)
                stderr_tail.append(line)
                if len(stderr_tail) > 50:
                    stderr_tail.pop(0)

        proc.wait()

        if proc.returncode == 0:
            # Fix EXT-X-MAP URIs: ffmpeg writes the absolute path we passed
            # to -hls_fmp4_init_filename verbatim into each playlist.
            # Replace it with just "init.mp4" so browsers can fetch it correctly.
            _fix_fmp4_init_uris(output_dir)

            # ── Subtitle extraction (text-based tracks → WebVTT) ──────────────
            # Run as a separate pass after the main transcode so subtitle
            # failures never block the video from playing.
            extracted_subs = _extract_subtitles(file_path, output_dir, sub_streams)

            _hls_write_status(
                cache_key,
                {
                    "status": "ready",
                    "progress": 100,
                    "profiles": [p[0] for p in profiles],
                    "audio_tracks": [
                        {"lang": a["lang"], "label": a["label"]} for a in audio_streams
                    ],
                    "sub_tracks": [
                        {
                            "lang": s["lang"],
                            "label": s["label"],
                            "vtt_filename": s["vtt_filename"],
                        }
                        for s in extracted_subs
                    ],
                },
            )
            print(f"\u2705 HLS transcode done: {cache_key[:8]}\u2026", flush=True)
        else:
            err_tail = "\n".join(stderr_tail)[-800:]
            _hls_write_status(cache_key, {"status": "error", "message": err_tail})
            print(
                f"\u274c HLS transcode failed (rc={proc.returncode}):\n{err_tail}",
                flush=True,
            )

    except subprocess.TimeoutExpired:
        _hls_write_status(
            cache_key, {"status": "error", "message": "Transcoding timed out"}
        )
        print(f"\u274c HLS transcode timed out: {cache_key[:8]}\u2026")
    except Exception as exc:
        _hls_write_status(cache_key, {"status": "error", "message": str(exc)})
        print(f"\u274c HLS transcode error: {exc}")


def _extract_subtitles(file_path: str, output_dir: str, sub_streams: list) -> list:
    """
    Extract each text-based subtitle stream to a WebVTT file in output_dir.

    Returns a list of the sub_streams entries that were successfully extracted,
    each augmented with a "vtt_filename" key for the generated file.
    """
    if not sub_streams:
        return []
    ffmpeg_bin = _resolve_ffmpeg()
    extracted = []
    for sub in sub_streams:
        lang = re.sub(r"[^a-zA-Z0-9]", "", sub["lang"])[:8] or f"sub{sub['src_idx']}"
        vtt_filename = f"sub_{sub['src_idx']}_{lang}.vtt"
        vtt_path = os.path.join(output_dir, vtt_filename)
        try:
            r = subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-i",
                    file_path,
                    "-map",
                    f"0:s:{sub['src_idx']}",
                    "-c:s",
                    "webvtt",
                    vtt_path,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if (
                r.returncode == 0
                and os.path.exists(vtt_path)
                and os.path.getsize(vtt_path) > 0
            ):
                extracted.append({**sub, "vtt_filename": vtt_filename})
                print(
                    f"\u2705 Subtitle extracted: {vtt_filename} ({sub['label']})",
                    flush=True,
                )
            else:
                print(
                    f"\u26a0\ufe0f  Subtitle extraction failed for track {sub['src_idx']} "
                    f"({sub['label']}): {r.stderr[-200:] if r.stderr else 'unknown error'}",
                    flush=True,
                )
        except Exception as exc:
            print(f"\u26a0\ufe0f  Subtitle extraction error: {exc}", flush=True)
    return extracted


def _fix_fmp4_init_uris(output_dir: str) -> None:
    """
    ffmpeg writes the full absolute path passed to -hls_fmp4_init_filename
    verbatim into EXT-X-MAP:URI in each variant playlist.  Replace those
    absolute paths with just "init.mp4" so browsers can resolve them
    relative to the playlist URL via the normal HLS file-serving route.
    """
    import glob as _glob

    for playlist in _glob.glob(
        os.path.join(output_dir, "**", "index.m3u8"), recursive=True
    ):
        try:
            with open(playlist, "r", encoding="utf-8") as f:
                content = f.read()
            if "#EXT-X-MAP" not in content:
                continue
            # Replace any EXT-X-MAP URI value with just "init.mp4"
            fixed = re.sub(
                r'#EXT-X-MAP:URI="[^"]*"',
                '#EXT-X-MAP:URI="init.mp4"',
                content,
            )
            if fixed != content:
                with open(playlist, "w", encoding="utf-8") as f:
                    f.write(fixed)
                print(
                    f"  fixed EXT-X-MAP URI in {os.path.relpath(playlist, output_dir)}"
                )
        except Exception as e:
            print(f"  warning: could not fix {playlist}: {e}")


def _patch_master_m3u8_subtitles(master_path: str, extracted_subs: list) -> None:
    """
    Post-process the ffmpeg-generated master.m3u8 to inject EXT-X-MEDIA subtitle
    entries and add SUBTITLES="subs" to every EXT-X-STREAM-INF line.
    No-ops gracefully if the file doesn't exist or subs list is empty.
    """
    if not extracted_subs or not os.path.exists(master_path):
        return
    try:
        with open(master_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Build EXT-X-MEDIA subtitle declarations
        media_lines = []
        for i, sub in enumerate(extracted_subs):
            media_lines.append(
                f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",'
                f'LANGUAGE="{sub["lang"]}",NAME="{sub["label"]}",'
                f"DEFAULT=NO,AUTOSELECT=NO,FORCED=NO,"
                f'URI="{sub["vtt_filename"]}"\n'
            )

        new_lines: list = []
        inserted = False
        for line in lines:
            # Insert subtitle media declarations before the first stream variant
            if line.startswith("#EXT-X-STREAM-INF") and not inserted:
                new_lines.extend(media_lines)
                inserted = True
            if line.startswith("#EXT-X-STREAM-INF") and "SUBTITLES=" not in line:
                line = line.rstrip() + ',SUBTITLES="subs"\n'
            new_lines.append(line)

        with open(master_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(
            f"\u2705 master.m3u8 patched with {len(extracted_subs)} subtitle track(s)",
            flush=True,
        )
    except Exception as exc:
        print(f"\u26a0\ufe0f  Failed to patch master.m3u8 subtitles: {exc}", flush=True)


@app.route("/hls_start/<path:video_path>")
@login_required
async def hls_start(video_path):
    """
    Kick off HLS transcoding (idempotent).  Returns:
      hls_available: false  — ffmpeg not installed; frontend shows Play Raw only
      status: processing    — transcode running; frontend shows progress bar
      status: ready         — segments ready;    frontend shows Stream HLS button
    """
    if not storage.is_safe_path(video_path):
        return jsonify({"error": "Invalid path"}), 400

    full_path = os.path.join(ROOT_DIR, video_path)
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return jsonify({"error": "File not found"}), 404

    ext = video_path.rsplit(".", 1)[-1].lower() if "." in video_path else ""
    if ext not in _VIDEO_EXTS_HLS:
        return jsonify({"hls_available": False, "reason": "unsupported_format"})

    # Skip HLS for small web-native files — play raw is fine and saves CPU/disk.
    # Non-web-native formats (mkv, avi, wmv, etc.) always get HLS regardless of
    # size because the browser cannot decode them natively.
    # Both thresholds are configurable via config.py / server_config.json.
    _web_native = {"mp4", "webm", "mov", "m4v", "ts"}
    if HLS_MIN_SIZE > 0 and ext in _web_native and ext not in HLS_FORCE_FORMATS:
        try:
            file_size = os.path.getsize(full_path)
        except OSError:
            file_size = 0
        if file_size < HLS_MIN_SIZE:
            return jsonify(
                {
                    "hls_available": False,
                    "reason": "file_too_small",
                    "file_size": file_size,
                    "min_size": HLS_MIN_SIZE,
                }
            )

    if not await asyncio.to_thread(_ffmpeg_available):
        reason = "ffmpeg_disabled" if not ENABLE_FFMPEG else "ffmpeg_not_installed"
        print(
            f"\u26a0\ufe0f  ffmpeg {'disabled' if not ENABLE_FFMPEG else 'not found'} — HLS unavailable, client will use raw playback"
        )
        return jsonify({"hls_available": False, "reason": reason})

    cache_key = _hls_cache_key(full_path)
    status = _hls_read_status(cache_key)

    # Guard stale "ready" when hls cache dir was wiped externally
    if status.get("status") == "ready":
        master = os.path.join(_hls_output_dir(cache_key), "master.m3u8")
        if os.path.exists(master):
            return jsonify({"hls_available": True, "cache_key": cache_key, **status})
        print(
            f"\u26a0\ufe0f  HLS stale cache — re-transcoding: {cache_key[:8]}\u2026",
            flush=True,
        )
        # fall through

    if status.get("status") == "processing":
        return jsonify({"hls_available": True, "cache_key": cache_key, **status})

    # Spawn background daemon thread — survives frontend refresh
    threading.Thread(
        target=_run_hls_transcode, args=(full_path, cache_key), daemon=True
    ).start()

    _hls_write_status(cache_key, {"status": "processing", "progress": 0})
    return jsonify(
        {
            "hls_available": True,
            "cache_key": cache_key,
            "status": "processing",
            "progress": 0,
        }
    )


@app.route("/hls_status/<cache_key>")
@login_required
async def hls_status_route(cache_key):
    """Poll transcoding status.  Returns {status, progress 0-100, profiles?}."""
    if not re.fullmatch(r"[a-f0-9]{32}", cache_key):
        return jsonify({"error": "Invalid key"}), 400
    return jsonify(_hls_read_status(cache_key))


@app.route("/hls_files/<cache_key>/<path:hls_path>")
@login_required
async def hls_files(cache_key, hls_path):
    """Serve HLS master/sub-playlists (.m3u8) and TS segments (.ts)."""
    if not re.fullmatch(r"[a-f0-9]{32}", cache_key):
        return "Invalid key", 400
    if ".." in hls_path or hls_path.startswith("/"):
        return "Forbidden", 403
    _, ext = os.path.splitext(hls_path)
    if ext.lower() not in (".m3u8", ".ts", ".m4s", ".vtt", ".mp4"):
        return "Forbidden", 403
    output_dir = _hls_output_dir(cache_key)
    file_path = os.path.normpath(os.path.join(output_dir, hls_path))
    if not file_path.startswith(os.path.abspath(output_dir)):
        return "Path traversal", 403
    if not os.path.exists(file_path):
        return "Not found", 404
    if ext.lower() == ".m3u8":
        return await send_file(
            file_path,
            mimetype="application/vnd.apple.mpegurl",
            cache_timeout=0,
            conditional=False,
        )
    if ext.lower() == ".vtt":
        return await send_file(
            file_path,
            mimetype="text/vtt",
            cache_timeout=3600,
        )
    if ext.lower() == ".mp4":
        return await send_file(file_path, mimetype="video/mp4", cache_timeout=3600)
    if ext.lower() == ".m4s":
        return await send_file(
            file_path, mimetype="video/iso.segment", cache_timeout=3600
        )
    # .ts segments
    return await send_file(file_path, mimetype="video/mp2t", cache_timeout=3600)


# ─────────────────────────────────────────────────────────────────────────────
# End HLS Adaptive Streaming
# ─────────────────────────────────────────────────────────────────────────────
