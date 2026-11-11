CloudinatorFTP
├── .github
│   ├── codeql
│   │   └── codeql-config.yml
│   ├── workflows
│   │   ├── audit.yml
│   │   ├── codeql.yml
│   │   ├── coverage.yml
│   │   ├── lint.yml
│   │   ├── mutation.yml
│   │   ├── nightly.yml
│   │   └── tests.yml
│   ├── CODEOWNERS
│   └── dependabot.yml
├── docs
│   ├── rulesets
│   │   ├── dev.json
│   │   ├── main.json
│   │   └── README.md
│   ├── ANDROID_DEPLOYMENT.md
│   ├── CLAUDE.md
│   ├── CODING_GUIDELINES.md
│   ├── CONFIG_PY_REFERENCE.md
│   ├── DEPLOY_APACHE.md
│   ├── LINUX_DEPLOYMENT.md
│   ├── RCLONE_DEPLOYMENT.md
│   ├── SERVER_MANAGEMENT_SCRIPT_GUIDE.md
│   ├── SETUP_TUNNEL_ADVANCED.md
│   ├── SMB_PROTOCOL_DEPLOYMENT.md
│   ├── TESTING_STRATEGY.md
│   ├── USER_GUIDE.md
│   ├── VSCODE_SETUP.md
│   └── WINDOWS_DEPLOYMENT.md
├── helpers
│   ├── __init__.py
│   ├── file_body.py
│   ├── hypercorn_ssl_fix.py
│   ├── lanman_guard.py
│   ├── net_utils.py
│   ├── parent_watch.py
│   ├── ssl_cert.py
│   ├── upload_perf.py
│   └── walk_executor.py
├── images
│   └── ... (pdfjs dependency)
├── routes
│   ├── __init__.py
│   ├── admin.py
│   ├── files.py
│   ├── hls.py
│   ├── image_preview.py
│   ├── login.py
│   ├── previews.py
│   ├── shares.py
│   ├── site_meta.py
│   ├── stats.py
│   ├── uploads.py
│   └── versions.py
├── static
│   ├── .well-known
│   │   └── security.txt
│   ├── audio
│   │   └── bg_mus.opus
│   ├── css
│   │   ├── images
│   │   │   └── ... (pdfjs dependency)
│   │   ├── 404.css
│   │   ├── all.min.css
│   │   ├── index.css
│   │   ├── login.css
│   │   ├── pdfjs-viewer-overlay.css
│   │   ├── shared.css
│   │   ├── video-skin-overrides.css
│   │   ├── video.css (video.js dependency)
│   │   └── viewer.css (pdf.js dependency)
│   ├── icons
│   │   └── icon.webp
│   ├── js
│   │   ├── cmaps
│   │   │   └── ... (pdfjs dependency)
│   │   ├── iccs
│   │   │   └── ... (pdfjs dependency)
│   │   ├── images
│   │   │   └── ... (pdfjs dependency)
│   │   ├── locale
│   │   │   └── ... (pdfjs dependency)
│   │   ├── standard_fonts
│   │   │   └── ... (pdfjs dependency)
│   │   ├── wasm
│   │   │   └── ... (pdfjs dependency)
│   │   ├── 404.js
│   │   ├── bg_audio.js
│   │   ├── index.js
│   │   ├── login.js
│   │   ├── pdf.mjs (pdfjs dependency)
│   │   ├── pdf.worker.mjs (pdfjs dependency)
│   │   ├── pdfjs-worker-init.mjs
│   │   ├── shared.js
│   │   ├── video.js (video.js dependency)
│   │   └── viewer.mjs (pdf.js dependency)
│   ├── webfonts
│   │   └── ... (fontawesome dependency)
│   └── robots.txt
├── templates
│   ├── 404.html
│   ├── index.html
│   ├── login.html
│   └── shared.html
├── tests
│   ├── application
│   │   ├── test_async_offload_routes.py
│   │   ├── test_authorization.py
│   │   ├── test_boot.py
│   │   ├── test_download_buffer.py
│   │   ├── test_file_index_recovery.py
│   │   ├── test_file_monitor_recovery.py
│   │   ├── test_login.py
│   │   ├── test_path_containment.py
│   │   ├── test_purge_missing_versions.py
│   │   ├── test_recover_uploads.py
│   │   ├── test_revoke_code_generation.py
│   │   ├── test_session_revocation.py
│   │   ├── test_upload_integrity.py
│   │   ├── test_upload_tuning.py
│   │   ├── test_version_restore.py
│   │   └── test_version_routes.py
│   ├── frontend
│   │   ├── test_browser_flows.py
│   │   └── test_browser_smoke.py
│   ├── performance
│   │   ├── test_baselines.py
│   │   └── test_slow_download.py
│   ├── property
│   │   └── test_properties.py
│   ├── protocols
│   │   ├── conftest.py
│   │   ├── test_ftp_protocol.py
│   │   ├── test_sftp_protocol.py
│   │   ├── test_smb_protocol.py
│   │   └── test_webdav_protocol.py
│   ├── reliability
│   │   ├── test_concurrency.py
│   │   ├── test_restart.py
│   │   ├── test_version_chunks_excluded.py
│   │   ├── test_version_engine_crash.py
│   │   └── test_version_engine_live.py
│   ├── unit
│   │   ├── test_abandoned_upload_cleanup.py
│   │   ├── test_assemble_atomic.py
│   │   ├── test_async_handlers_no_blocking.py
│   │   ├── test_chunk_tracker_lock.py
│   │   ├── test_client_ip_trust.py
│   │   ├── test_database_connect.py
│   │   ├── test_dev_server_coverage_save.py
│   │   ├── test_dev_server_identity.py
│   │   ├── test_file_body.py
│   │   ├── test_http_client.py
│   │   ├── test_image_preview_waiters.py
│   │   ├── test_index_js_logic.py
│   │   ├── test_login_js.py
│   │   ├── test_manage_log_follow.py
│   │   ├── test_manage_qa.py
│   │   ├── test_monitor_cache.py
│   │   ├── test_monitor_handler.py
│   │   ├── test_paths.py
│   │   ├── test_purge_missing_versions.py
│   │   ├── test_qa_audit.py
│   │   ├── test_qa_coverage.py
│   │   ├── test_qa_runner.py
│   │   ├── test_request_auth_memo.py
│   │   ├── test_response_timeout.py
│   │   ├── test_scratch_copy.py
│   │   ├── test_scratch_environment.py
│   │   ├── test_setup_pymodules.py
│   │   ├── test_static_check_skip_dirs.py
│   │   ├── test_storage_stats_cache.py
│   │   ├── test_stream_from_thread.py
│   │   ├── test_upload_body_paths.py
│   │   ├── test_upload_chunk_keys.py
│   │   ├── test_upload_perf.py
│   │   ├── test_upload_perf_split.py
│   │   ├── test_upload_progress_js.py
│   │   ├── test_upload_settings.py
│   │   ├── test_version_engine_backoff.py
│   │   ├── test_version_engine_scope.py
│   │   ├── test_versions_stream_close.py
│   │   ├── test_walk_executor.py
│   │   └── test_webdav_listener_binds.py
│   ├── audit_ignore.txt
│   ├── check.py
│   ├── codeql_sarif_parser.py
│   ├── conftest.py
│   ├── dir_tree.py
│   ├── mutation_trial.py
│   ├── qa.py
│   ├── smoke.py
│   └── smoke_routes.json
├── tools
│   ├── kick_sessions.py
│   ├── manage_users.py
│   ├── purge_missing_versions.py
│   ├── reset_db.py
│   ├── revoke_sharing.py
│   ├── setup_storage.py
│   ├── smb_setup.py
│   ├── sri_validator.py
│   └── version_manage.py
├── .gitattributes
├── .gitignore
├── app.py
├── auth.py
├── config.py
├── core.py
├── database.py
├── dev_server.py
├── file_index.py
├── file_monitor.py
├── ftp_server.py
├── LICENSE
├── logging_setup.py
├── manage.sh
├── middleware.py
├── paths.py
├── prod_server.py
├── protocol_manager.py
├── pyproject.toml
├── README.md
├── realtime_shares.py
├── realtime_stats.py
├── requirements-dev.txt
├── requirements.txt
├── search_index.py
├── server_config.json
├── setup_pymodules.sh
├── sftp_server.py
├── smb_server.py
├── storage.py
├── storage_config.json
├── termux_setup.sh
├── version_engine.py
├── version_history.py
└── webdav_server.py
