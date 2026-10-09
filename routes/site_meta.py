"""
routes/site_meta.py - site metadata routes: /robots.txt, /.well-known/security.txt and /sitemap.xml
(Phase 10 of the split, CLAUDE.md 4.78; /debug/headers was removed in 4.79).

Moved verbatim from app.py. Gets shared objects via `from core import ...`; imports no other route
module.
"""

from core import app

from quart import abort, send_from_directory


# Route to robots.txt
@app.route("/robots.txt")
async def robots_txt():
    response = await send_from_directory(
        app.static_folder, "robots.txt", mimetype="text/plain"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


# Route to security.txt for search engine crawlers and security researchers
@app.route("/.well-known/security.txt")
async def security_txt():
    response = await send_from_directory(
        app.static_folder, ".well-known/security.txt", mimetype="text/plain"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


# No sitemap — this app intentionally isn't meant to be crawled/indexed.
@app.route("/sitemap.xml")
async def sitemap_xml():
    abort(404)
