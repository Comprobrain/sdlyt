"""Shared resolution lists and yt-dlp format selectors.

YouTube serves H.264 only up to 1080p. Above that, 1440p, 2160p and
4320p require VP9 or AV1. MP4 cannot reliably hold VP9/AV1 for all
players, so downloads above 1080p are merged/remuxed into MKV. The
actual format-selection logic now lives in ``downloads_format.py``;
this module only holds the resolution list, labels and helpers the
UIs use for display.
"""
from __future__ import annotations

RESOLUTIONS: tuple[int, ...] = (240, 360, 480, 720, 1080, 1440, 2160, 4320)

_LABELS = {
    1440: "1440p (2K)",
    2160: "2160p (4K)",
    4320: "4320p (8K)",
}


def label(height: int) -> str:
    """Return the display label for a resolution height."""
    return _LABELS.get(height, "%dp" % height)


def choices() -> list[tuple[int, str]]:
    """Return ``(height, label)`` pairs for UI option widgets."""
    return [(height, label(height)) for height in RESOLUTIONS]


def is_above_hd(height: int) -> bool:
    """True for 1080p and above."""
    return height >= 1080


def is_above_720(height: int) -> bool:
    """True for resolutions that may stress weak devices."""
    return height > 720


def is_above_1080(height: int) -> bool:
    """True for 1440p, 2160p and 4320p, which require VP9/AV1."""
    return height > 1080


def play_fmt(height: int) -> str:
    """Return the mpv ``--ytdl-format`` selector.

    mpv handles its own format selection and tolerates codec filters,
    so this string is intentionally separate from the download selector.
    """
    return "bv*[height<=%d]+ba/b[height<=%d]" % (height, height)


def dl_fmt(height: int) -> str:
    """Deprecated. Prefer :func:`downloads_format.video_format_args`.

    This string is a safe, minimal fallback: no codec regex filters,
    no height cap. The full download argument set (``-f`` + ``-S`` +
    merge container) is built by ``downloads_format.video_format_args``.
    """
    return "bv*+ba/b"


def merge_output_format(height: int) -> str:
    """Return the container used when merging separate streams."""
    return "mp4" if height <= 1080 else "mkv"


def container_note(height: int) -> str:
    """Return a short explanation for the settings UI."""
    if height <= 1080:
        return "H.264 + M4A -> MP4 (widest compatibility)."
    return "VP9/AV1 + Opus -> MKV (MP4 cannot reliably hold these codecs)."


def weak_system_warning(height: int) -> str:
    """Return warning text for high playback resolutions."""
    return (
        "%s playback may lag, drop frames, or use a lot of RAM on this "
        "device. Raspberry Pi hardware decoders usually cannot hardware-"
        "decode VP9/AV1 at this size, so mpv may fall back to software "
        "decoding." % label(height)
    )
