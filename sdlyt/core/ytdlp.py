"""yt-dlp search and version helpers."""
from __future__ import annotations

import subprocess

from . import errors, paths, utils


class YtDlpError(RuntimeError):
    """Raised when yt-dlp fails in a way the UI should display."""


def search(query: str, timeout: int = 60) -> list[dict]:
    """Search YouTube and return lightweight result dictionaries."""
    command = [
        paths.YT,
        "--flat-playlist",
        "--print",
        "%(id)s\t%(title)s\t%(channel)s\t%(duration_string)s",
        "ytsearch15:" + query,
    ] + utils.cookie_args()

    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        raise YtDlpError("Search timed out") from exc
    except FileNotFoundError as exc:
        raise YtDlpError("yt-dlp not found at ~/bin/yt-dlp.") from exc

    items: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            items.append(
                {
                    "id": parts[0],
                    "title": parts[1],
                    "channel": parts[2],
                    "length": parts[3],
                    "meta": "%s  ·  %s" % (parts[2], parts[3]),
                }
            )

    if not items and proc.returncode != 0:
        raise YtDlpError(errors.friendly(proc.stderr))
    return items


def version() -> str:
    """Return the installed yt-dlp version, or an empty string."""
    return utils.version_of(paths.YT, "--version")