"""Filesystem paths and legacy data migration."""
from __future__ import annotations

import os
import shutil

HOME = os.path.expanduser("~")
APP_DIR = os.path.join(HOME, ".sdlyt")
HIST = os.path.join(APP_DIR, "history.json")
RECENT = os.path.join(APP_DIR, "recent.json")
SETF = os.path.join(APP_DIR, "settings.json")
QUEUEF = os.path.join(APP_DIR, "queue.json")
COOKIES = os.path.join(APP_DIR, "cookies.txt")
THUMBS = os.path.join(APP_DIR, "thumbs")
MPVLOG = os.path.join(APP_DIR, "mpv.log")
DEFAULT_OUT = os.path.join(HOME, "Downloads", "YT")
YT = os.path.join(HOME, "bin", "yt-dlp")

_LEGACY_DIR = os.path.join(HOME, ".ytmini")


def ensure_dirs() -> None:
    """Create application directories if they do not exist."""
    for directory in (APP_DIR, THUMBS, DEFAULT_OUT):
        os.makedirs(directory, exist_ok=True)


def migrate_legacy() -> None:
    """Copy data from the old ``~/.ytmini`` directory once."""
    if os.path.exists(SETF) or not os.path.isdir(_LEGACY_DIR):
        return
    for name in ("settings.json", "history.json", "queue.json", "cookies.txt"):
        source = os.path.join(_LEGACY_DIR, name)
        if os.path.exists(source):
            try:
                shutil.copy(source, os.path.join(APP_DIR, name))
            except OSError:
                pass


ensure_dirs()
migrate_legacy()