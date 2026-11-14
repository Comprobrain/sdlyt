"""Small, UI-independent helpers used across the core layer."""
from __future__ import annotations

import glob
import json
import os
import platform
import re
import shutil
import signal
import subprocess
from typing import Any, Optional

from . import paths


def jload(path: str, default: Any) -> Any:
    """Load JSON, returning *default* on any error."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def jsave(path: str, data: Any) -> None:
    """Write JSON atomically enough for this application."""
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except Exception:
        pass


def human(size: float) -> str:
    """Format a byte count for display."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return ("%.0f%s" if unit == "B" else "%.1f%s") % (size, unit)
        size /= 1024.0
    return "%.1fTB" % size


def detect_pm() -> str:
    """Return the name of the system package manager, if known."""
    for executable, name in (
        ("apt-get", "apt"),
        ("dnf", "dnf"),
        ("pacman", "pacman"),
        ("apk", "apk"),
        ("zypper", "zypper"),
    ):
        if shutil.which(executable):
            return name
    return ""


def ytdlp_asset() -> str:
    """Return the correct yt-dlp release asset name for this machine."""
    if glob.glob("/lib/ld-musl-*") or glob.glob("/usr/lib/ld-musl-*"):
        return "yt-dlp"
    machine = platform.machine().lower()
    return {
        "x86_64": "yt-dlp_linux",
        "amd64": "yt-dlp_linux",
        "aarch64": "yt-dlp_linux_aarch64",
        "arm64": "yt-dlp_linux_aarch64",
        "armv7l": "yt-dlp_linux_armv7l",
    }.get(machine, "yt-dlp")


def kill_group(proc: Optional[subprocess.Popen]) -> None:
    """Terminate a process and, on POSIX, its whole process group."""
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def cookie_args() -> list[str]:
    """Return yt-dlp cookie arguments when a cookie file exists."""
    return ["--cookies", paths.COOKIES] if os.path.exists(paths.COOKIES) else []


def prune_thumbs(max_files: int, max_bytes: int) -> None:
    """Delete oldest thumbnails until the cache is under both limits."""
    try:
        entries: list[tuple[float, int, str]] = []
        for name in os.listdir(paths.THUMBS):
            full = os.path.join(paths.THUMBS, name)
            if os.path.isfile(full):
                stat = os.stat(full)
                entries.append((stat.st_mtime, stat.st_size, full))
        entries.sort()
        count = len(entries)
        total = sum(item[1] for item in entries)
        for _mtime, size, full in entries:
            if count <= max_files and total <= max_bytes:
                break
            os.remove(full)
            count -= 1
            total -= size
    except Exception:
        pass


def version_of(binary: str, flag: str) -> str:
    """Return a short version string for *binary*, or an empty string."""
    try:
        output = subprocess.run(
            [binary, flag], capture_output=True, text=True, timeout=10
        ).stdout
        first = output.splitlines()[0] if output else ""
        match = re.search(r"\d+(\.\d+)+[\w.-]*", first)
        return match.group() if match else "installed"
    except Exception:
        return ""