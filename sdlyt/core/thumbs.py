"""Thumbnail download and cache service.

Callbacks run on a worker thread. UI layers must marshal back to their
own event loop before touching widgets.
"""
from __future__ import annotations

import io
import os
import threading
import urllib.request
from typing import Callable, Optional

from . import paths, system_profile, utils

try:
    from PIL import Image  # type: ignore

    HAVE_PIL = True
except Exception:
    Image = None  # type: ignore
    HAVE_PIL = False

ThumbCallback = Callable[[Optional["Image.Image"]], None]


class ThumbService:
    """Download, cache and resize video thumbnails."""

    def __init__(
        self,
        size: tuple[int, int] = (96, 54),
        enabled: bool = True,
        max_files: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        self.size = size
        self.enabled = enabled and HAVE_PIL
        self.max_files = max_files if max_files is not None else (
            200 if system_profile.is_low_ram() else 800
        )
        self.max_bytes = max_bytes if max_bytes is not None else (
            (15 if system_profile.is_low_ram() else 40) * 1024 * 1024
        )
        self._sem = threading.Semaphore(1 if system_profile.is_low_ram() else 3)

    def request(self, video_id: str, callback: ThumbCallback) -> None:
        """Fetch a thumbnail asynchronously and pass a PIL image to *callback*."""
        if not self.enabled or not video_id:
            callback(None)
            return
        threading.Thread(
            target=self._work, args=(video_id, callback), daemon=True
        ).start()

    def _work(self, video_id: str, callback: ThumbCallback) -> None:
        with self._sem:
            path = os.path.join(paths.THUMBS, video_id + ".png")
            if os.path.exists(path):
                try:
                    os.utime(path)
                except OSError:
                    pass
            else:
                if not self._fetch(video_id, path):
                    callback(None)
                    return
        try:
            callback(Image.open(path).copy())
        except Exception:
            callback(None)

    def _fetch(self, video_id: str, path: str) -> bool:
        try:
            request = urllib.request.Request(
                "https://i.ytimg.com/vi/%s/mqdefault.jpg" % video_id,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = urllib.request.urlopen(request, timeout=15).read()
            image = Image.open(io.BytesIO(data)).convert("RGB")
            image = image.resize(self.size, Image.LANCZOS)
            image.save(path, "PNG")
            utils.prune_thumbs(self.max_files, self.max_bytes)
            return True
        except Exception:
            return False

    def cache_stats(self) -> tuple[int, int]:
        """Return ``(file_count, total_bytes)`` for the thumbnail cache."""
        count = total = 0
        try:
            for name in os.listdir(paths.THUMBS):
                full = os.path.join(paths.THUMBS, name)
                if os.path.isfile(full):
                    count += 1
                    total += os.path.getsize(full)
        except OSError:
            pass
        return count, total

    def clear(self) -> None:
        """Delete all cached thumbnails."""
        try:
            for name in os.listdir(paths.THUMBS):
                try:
                    os.remove(os.path.join(paths.THUMBS, name))
                except OSError:
                    pass
        except OSError:
            pass