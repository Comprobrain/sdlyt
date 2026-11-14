"""Persistent application settings, backward compatible with old files."""
from __future__ import annotations

import importlib.util
from collections.abc import Iterator, MutableMapping
from typing import Any

from . import paths, system_profile, utils


def _pillow_available() -> bool:
    try:
        return importlib.util.find_spec("PIL") is not None
    except Exception:
        return False


HAVE_PIL = _pillow_available()


def _defaults() -> dict[str, Any]:
    low_ram = system_profile.is_low_ram()
    very_low = system_profile.is_very_low_ram()
    return {
        "play_res": 480,
        "dl_res": 720,
        "audio_fmt": "m4a",
        "fs": True,
        "hwdec": not very_low,
        "speed": 1.0,
        "volume": 100,
        "local_player": "mpv",
        "appearance": "dark" if not low_ram else "light",
        "font_scale": 1.0,
        "subs": False,
        "sub_lang": "en",
        "embed": True,
        "parallel": 1 if low_ram else 2,
        "thumbs": HAVE_PIL and not very_low,
        "audio_only": False,
        "out_dir": paths.DEFAULT_OUT,
        "auto_update": False,
        "compact": low_ram,
        "warned": [],
        # New keys
        "ui": "auto",
        "reduce_animations": False,
    }


DEFAULTS: dict[str, Any] = _defaults()


class Settings(MutableMapping[str, Any]):
    """Dictionary-like settings object backed by ``settings.json``."""

    def __init__(self, path: str = paths.SETF) -> None:
        self.path = path
        self.data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Merge stored values over defaults, ignoring unknown keys."""
        stored = utils.jload(self.path, {})
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS:
                    self.data[key] = value
            # Keep any extra keys for forward compatibility.
            for key, value in stored.items():
                if key not in self.data:
                    self.data[key] = value

    def save(self) -> None:
        """Persist the current settings."""
        utils.jsave(self.path, self.data)

    # ------------------------------------------------------------------
    # Mapping protocol
    # ------------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def __delitem__(self, key: str) -> None:
        del self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        """Set a value and optionally persist immediately."""
        self.data[key] = value
        if save:
            self.save()

    def mark_warned(self, key: str) -> None:
        """Add a warning identifier to the ``warned`` list."""
        warned = list(self.data.get("warned", []))
        if key not in warned:
            warned.append(key)
            self.data["warned"] = warned
            self.save()

    def was_warned(self, key: str) -> bool:
        """Return whether a warning has been dismissed."""
        return key in (self.data.get("warned") or [])

    def sub_language(self) -> str:
        """Return the first, cleaned subtitle language code."""
        import re

        first = re.split(r"[,\s]+", str(self.data.get("sub_lang", "en")).strip())[0]
        return re.sub(r"[^A-Za-z0-9-]", "", first) or "en"

    def reset(self) -> None:
        """Reset everything to defaults and save."""
        self.data = dict(DEFAULTS)
        self.save()