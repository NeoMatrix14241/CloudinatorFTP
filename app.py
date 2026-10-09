"""
app.py - application entry point (final form after the 10-phase split, CLAUDE.md 4.78).

`from core import ...` MUST stay the first project import: core.py runs ensure_dirs() and all
import-time startup in the original order. `import middleware` registers the hooks, then every
routes/* module is imported so its routes register on the shared core.app. This file keeps only
initialize_cleanup() (+ its call) and the __main__ block. prod_server.py, dev_server.py and
protocol_manager.py keep doing `from app import app` / `from app import get_local_ip`, so both
names stay importable from here.
"""

from core import (
    app,
    chunk_tracker,
    get_local_ip,
    get_protected_files,
)
import middleware  # noqa: F401  (registers every hook; must come right after core)
import routes.hls  # noqa: F401  (Phase 2: registers /hls_start, /hls_status, /hls_files)
import routes.image_preview  # noqa: F401  (Phase 3: registers /image_preview, /image_preview_status, /image_info)
import routes.versions  # noqa: F401  (Phase 4: registers /api/versions/* and /download/recovered/*)
import routes.previews  # noqa: F401  (Phase 5: registers /office_preview and /archive_preview)
import routes.admin  # noqa: F401  (Phase 6: registers /admin/clear_media_preview and /admin/rebuild_cache*)
import routes.stats  # noqa: F401  (Phase 6: stats/SSE/health/search/speedtest + the before_serving loop watchdog)
import routes.shares  # noqa: F401  (Phase 7: share links, /shared/*, /admin/shares*)
import routes.uploads  # noqa: F401  (Phase 8: uploads, chunks, assembly status, admin chunk routes)
import routes.files  # noqa: F401  (Phase 9: /, /<path>, /download, /view, bulk jobs, file operations)
import routes.login  # noqa: F401  (Phase 10: /login, /logout, /check_session, /csrf-token)
import routes.site_meta  # noqa: F401  (Phase 10: /robots.txt, /sitemap.xml, /.well-known/security.txt, /debug/headers)
from routes.uploads import (
    detect_ready_assemblies,
    start_assembly_worker,
    start_enhanced_cleanup_scheduler,
    start_expired_share_cleanup_scheduler,
    start_orphan_cleanup_scheduler,
)  # called by initialize_cleanup() below

import os
from config import (
    PORT,
    HOST,
    ROOT_DIR,
    CHUNK_SIZE,
    ENABLE_CHUNKED_UPLOADS,
)
import storage


# Initialize cleanup on startup
def initialize_cleanup():
    """Initialize all cleanup processes"""
    print("🧹 Initializing cleanup systems...")

    # Start enhanced cleanup schedulers
    start_enhanced_cleanup_scheduler()
    start_orphan_cleanup_scheduler()
    start_expired_share_cleanup_scheduler()

    # Start assembly worker
    start_assembly_worker()

    # Do an initial aggressive cleanup on startup
    try:
        print("🧹 Running startup cleanup...")

        # Get active assembly jobs to protect them (should be none on startup)
        active_assembly_jobs = get_protected_files()

        storage.cleanup_old_chunks(
            max_age_hours=0.1, protected_files=active_assembly_jobs
        )  # Clean chunks older than 6 minutes
        chunk_tracker.cleanup_orphaned_chunks()
        print("✅ Startup cleanup completed")
    except Exception as e:
        print(f"⚠️ Warning: Startup cleanup failed: {e}")

    # Check for any existing chunks that are ready for assembly
    print("🔍 Checking for incomplete uploads ready for assembly...")
    detect_ready_assemblies()


# Initialize cleanup when app starts
initialize_cleanup()


if __name__ == "__main__":
    print(f"🚀 Starting Enhanced Cloudinator FTP Server on port {PORT}")
    print(f"📁 Root directory: {os.path.abspath(ROOT_DIR)}")
    print(f"🔧 Chunked uploads: {'Enabled' if ENABLE_CHUNKED_UPLOADS else 'Disabled'}")
    print(f"📦 Chunk size: {CHUNK_SIZE // (1024*1024)}MB")
    print("✨ Enhanced Features:")
    print("   • Smart progress tracking with speed/ETA")
    print("   • Multi-file selection with bulk operations")
    print("   • Advanced chunk cleanup system")
    print("   • Session-based upload tracking")
    print("   • Orphaned chunk detection and cleanup")
    print("   • Real-time cleanup on page refresh")
    print("   • Background file assembly with status tracking")
    print("🧹 Cleanup Schedule:")
    print("   • Every 5 minutes: Orphaned chunks cleanup")
    print("   • Every 15 minutes: Stale chunks cleanup (1+ hours)")
    print("   • Every 1 hour: Full cleanup (24+ hours)")
    print("   • On page load: Request-based cleanup")
    print("   • On logout: Session cleanup")
    print("🔄 Assembly System:")
    print("   • Background worker processes file assembly")
    print("   • Real-time status updates via API")
    print("   • Resume capability after page refresh")
    print("   • Automatic recovery of incomplete uploads")

    LOCAL_IP = get_local_ip()
    print(f"🌐 Local network:  http://{LOCAL_IP}:{PORT}")
    print(f"🔁 Localhost:      http://localhost:{PORT}")

    # Start the alternate-protocol servers (WebDAV, SFTP, FTP, SMB) via the
    # shared protocol_manager module — same mechanism dev_server.py and
    # prod_server.py use. NOTE: in normal operation this __main__ block never
    # runs, since app.py is imported (not executed directly) by those two
    # launcher scripts, and they call protocol_manager.start_all() themselves
    # right after importing `app`. This call only matters if you run
    # `python app.py` directly. protocol_manager.start_all() is idempotent
    # (guarded by an internal _started flag), so this is safe even if it
    # somehow already ran earlier in the same process.
    import atexit
    import protocol_manager

    protocol_manager.start_all()
    atexit.register(protocol_manager.stop_all)

    app.run(host=HOST, port=PORT, debug=False)
