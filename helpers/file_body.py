"""
helpers/file_body.py - send files in big pieces (CLAUDE.md 5.42).

Quart sends a file (`send_file`, `send_from_directory`: /download, /view) through
quart.wrappers.response.FileBody, which reads 8 KiB per iteration and awaits TWO thread-pool
operations for each of them (aiofiles `tell()` and `read()`), then hands the piece to the server.
A 32 MB download is 4096 iterations, i.e. more than 8000 thread hand-offs. On the owner's Windows
PC that made a freshly written, RAM-cached 32 MB file download at 2.6 MB/s while uploads ran at
12 MB/s. Measured on Linux with real Quart and Hypercorn, the same file went 41 MB/s (8 KiB),
194 MB/s (64 KiB), 346 MB/s (256 KiB), 355 MB/s (1 MiB).

`use_file_buffer(app, size)` makes every file response of ONE app read `size` bytes per iteration.
It uses two attributes Quart documents (`Response.file_body_class` and `FileBody.buffer_size`) and
changes nothing globally: a subclass is created, Quart's own classes stay as they are.

Standard library only (it works on the objects of the app it is given). Never imports the application.
"""

MIN_BUFFER_SIZE = 8192  # Quart's own default
MAX_BUFFER_SIZE = 16 * 1024 * 1024


def use_file_buffer(app, buffer_size, log=print):
    """Make `app`'s file responses read `buffer_size` bytes at a time.

    Returns the FileBody subclass, or None when it could not be applied (a Quart version without
    `Response.file_body_class`): a download that is slower than it could be is better than an
    application that does not start, so the reason is logged and nothing is raised.
    """
    try:
        size = int(buffer_size)
        if not MIN_BUFFER_SIZE <= size <= MAX_BUFFER_SIZE:
            raise ValueError(
                f"buffer size {size} is outside {MIN_BUFFER_SIZE}..{MAX_BUFFER_SIZE}"
            )
        base = app.response_class
        if not hasattr(base, "file_body_class"):
            raise AttributeError("this Quart has no Response.file_body_class")
        # extend what the app already uses, so an existing customisation survives
        sized = type("SizedFileBody", (base.file_body_class,), {"buffer_size": size})
        app.response_class = type(base.__name__, (base,), {"file_body_class": sized})
        return sized
    except Exception as exc:  # see the docstring: never stop the application for this
        log(f"⚠️ downloads keep Quart's default read size: {exc}")
        return None
