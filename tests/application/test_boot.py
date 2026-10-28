"""
Black-box boot tests: the real application, started from a scratch copy (see conftest.py).

These prove two things before any deeper application test is written: the app starts from a
copy whose data folders are all inside the scratch tree, and the first public pages answer.
Anonymous access must not reach files.
"""

import pytest

pytestmark = pytest.mark.application


def test_login_page_is_served(scratch_server):
    status, _headers, body = scratch_server.get("/login")
    assert status == 200
    assert b"<html" in body.lower()


def test_robots_txt_is_served(scratch_server):
    status, _headers, _body = scratch_server.get("/robots.txt")
    assert status == 200


def test_anonymous_root_is_not_a_file_listing(scratch_server):
    status, _headers, body = scratch_server.get("/")
    # An anonymous visitor must be redirected to the login page or refused, never served.
    assert status in (301, 302, 303, 307, 308, 401, 403), (status, body[:200])


def test_server_keeps_its_data_inside_the_scratch_folder(scratch_server, scratch_tools):
    data = scratch_server.root / "data"
    for name in ("db", "cache", "versions", "storage"):
        assert (data / name).is_dir(), f"{name}/ was not created in the scratch tree"
    assert scratch_tools.is_inside(data, scratch_server.root)


def test_real_config_files_were_not_modified(scratch_server, scratch_tools):
    before = scratch_server.real_config_hashes
    after = scratch_tools.real_config_hashes()
    assert after == before


def test_server_process_is_still_running(scratch_server):
    assert scratch_server.proc.poll() is None, scratch_server.log_tail()
