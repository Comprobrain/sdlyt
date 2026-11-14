"""Play history persistence."""
from __future__ import annotations

import time
from typing import Iterator

from . import paths, utils


class History:
    """A bounded, most-recent-first list of played items."""

    def __init__(self, path: str = paths.HIST, limit: int = 200) -> None:
        self.path = path
        self.limit = limit
        self.entries: list[dict] = []
        self.load()

    def load(self) -> None:
        """Load history from disk."""
        stored = utils.jload(self.path, [])
        self.entries = stored if isinstance(stored, list) else []

    def save(self) -> None:
        """Persist history to disk."""
        utils.jsave(self.path, self.entries[: self.limit])

    def add(self, item: dict) -> None:
        """Insert or move an item to the top of the history."""
        video_id = item.get("id", "")
        self.entries = [entry for entry in self.entries if entry.get("id") != video_id]
        self.entries.insert(
            0,
            {
                "id": video_id,
                "title": item.get("title", ""),
                "channel": item.get("channel", ""),
                "when": time.strftime("%Y-%m-%d %H:%M"),
            },
        )
        self.entries = self.entries[: self.limit]
        self.save()

    def clear(self) -> None:
        """Remove all history."""
        self.entries = []
        self.save()

    def __iter__(self) -> Iterator[dict]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)