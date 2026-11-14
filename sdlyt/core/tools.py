"""Dependency detection for the Settings → Tools section."""
from __future__ import annotations

import os
import shutil
from typing import TypedDict

from . import paths, utils

OSK_CANDIDATES = (
    "wvkbd-mobintl",
    "wvkbd",
    "onboard",
    "matchbox-keyboard",
    "florence",
    "squeekboard",
)


class ToolStatus(TypedDict):
    ok: bool
    version: str


def check_tools() -> dict[str, ToolStatus]:
    """Return availability and versions for external tools."""
    yt_ok = os.path.isfile(paths.YT) and os.access(paths.YT, os.X_OK)
    osk = next((name for name in OSK_CANDIDATES if shutil.which(name)), "")

    return {
        "mpv": {
            "ok": bool(shutil.which("mpv")),
            "version": utils.version_of("mpv", "--version"),
        },
        "ffmpeg": {
            "ok": bool(shutil.which("ffmpeg")),
            "version": utils.version_of("ffmpeg", "-version"),
        },
        "yt-dlp": {
            "ok": yt_ok,
            "version": utils.version_of(paths.YT, "--version") if yt_ok else "",
        },
        "vlc": {
            "ok": bool(shutil.which("vlc")),
            "version": utils.version_of("vlc", "--version"),
        },
        "pillow": {
            "ok": _pillow_ok(),
            "version": "installed" if _pillow_ok() else "",
        },
        "osk": {
            "ok": bool(osk),
            "version": osk,
        },
    }


def _pillow_ok() -> bool:
    try:
        import PIL  # noqa: F401

        return True
    except Exception:
        return False