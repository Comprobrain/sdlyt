"""Format selection for downloads. Sort-based, never fails on codecs.

Uses ``-f bv*+ba/b`` with ``-S res:N[,vcodec:h264]`` rather than codec
regex filters, because yt-dlp's format-selector parser rejects the
unquoted ``()|`` inside ``[vcodec~=...]`` filters. At or below 1080p
we prefer H.264 + M4A and merge into MP4; above 1080p we merge into
MKV because MP4 cannot hold VP9/AV1 + Opus reliably.
"""
from __future__ import annotations

import re
from typing import Optional

RESOLUTIONS: tuple[int, ...] = (240, 360, 480, 720, 1080, 1440, 2160, 4320)


def video_format_args(resolution: int) -> list[str]:
    """Return ``-f``, ``-S`` and merge output args for a video download."""
    fmt = "bv*+ba/b"
    if resolution <= 1080:
        sort = "res:%d,vcodec:h264" % resolution
        return ["-f", fmt, "-S", sort, "--merge-output-format", "mp4"]
    sort = "res:%d" % resolution
    return [
        "-f", fmt,
        "-S", sort,
        "--merge-output-format", "mkv",
        "--remux-video", "mkv",
    ]


def audio_format_args(audio_format: str) -> list[str]:
    """Return ``-f``/``-x`` args for an audio-only download."""
    if audio_format == "mp3":
        return ["-x", "--audio-format", "mp3"]
    return ["-f", "ba[ext=m4a]/ba"]


def all_format_args() -> list[tuple[str, list[str]]]:
    """Return every possible format argument set with a description."""
    cases: list[tuple[str, list[str]]] = []
    for res in RESOLUTIONS:
        cases.append(("video@%dp" % res, video_format_args(res)))
    for afmt in ("m4a", "mp3"):
        cases.append(("audio@%s" % afmt, audio_format_args(afmt)))
    return cases


_REGEX_FILTER_RE = re.compile(r"\[[^\]]*~=[^\]]*\]")


def _check_fmt(fmt: str) -> list[str]:
    problems: list[str] = []
    if _REGEX_FILTER_RE.search(fmt):
        problems.append("regex filter ~= is unsupported: %s" % fmt)
    return problems


def _check_sort(sort: str) -> list[str]:
    problems: list[str] = []
    for segment in sort.split(","):
        segment = segment.strip()
        if not segment:
            problems.append("empty sort segment in %r" % sort)
            continue
        if ":" not in segment:
            problems.append("sort segment missing colon: %r" % segment)
            continue
        field = segment.split(":", 1)[0]
        if not field.replace("_", "").isalnum():
            problems.append("invalid sort field: %r" % field)
    return problems


def validate_format_args(args: list[str]) -> list[str]:
    """Return a list of problems found in *args* (empty means OK)."""
    problems: list[str] = []
    try:
        fmt_index = args.index("-f")
        fmt = args[fmt_index + 1]
        problems.extend(_check_fmt(fmt))
    except (ValueError, IndexError):
        pass
    try:
        sort_index = args.index("-S")
        sort = args[sort_index + 1]
        problems.extend(_check_sort(sort))
    except (ValueError, IndexError):
        pass
    return problems


def _try_ytdlp_import():
    try:
        from yt_dlp import YoutubeDL  # type: ignore
        return YoutubeDL
    except Exception:
        return None


def _validate_with_ytdlp(fmt: str) -> tuple[Optional[bool], str]:
    YoutubeDL = _try_ytdlp_import()
    if YoutubeDL is None:
        return (None, "python yt_dlp module not installed")
    try:
        ydl = YoutubeDL({"quiet": True, "no_warnings": True})
        build = getattr(ydl, "build_format_selector", None) or getattr(
            ydl, "_build_format_selector", None
        )
        if build is None:
            return (None, "build_format_selector method not found")
        selector = build(fmt)
        if selector is None:
            return (False, "build_format_selector returned None")
        return (True, "")
    except Exception as exc:
        return (False, "%s: %s" % (type(exc).__name__, exc))


def selftest() -> tuple[int, int]:
    """Validate every format string the app can produce.

    Returns ``(passed, failed)`` and prints a report to stdout.
    """
    passed = 0
    failed = 0
    print("Super Duper Lite YT - format selector self-test")
    print("=" * 60)
    ytdlp_state = "?"

    for description, args in all_format_args():
        local_problems = validate_format_args(args)
        if local_problems:
            failed += 1
            print("[FAIL] %-12s  local: %s" % (description, "; ".join(local_problems)))
            continue

        fmt = ""
        try:
            fmt = args[args.index("-f") + 1]
        except (ValueError, IndexError):
            pass

        if fmt:
            ok, reason = _validate_with_ytdlp(fmt)
            if ok is None:
                if ytdlp_state == "?":
                    print("[INFO] %s - syntax-only validation" % reason)
                    ytdlp_state = "missing"
                passed += 1
                print("[ OK ] %-12s  %s" % (description, fmt))
                continue
            if not ok:
                failed += 1
                print("[FAIL] %-12s  %s" % (description, reason))
                continue

        passed += 1
        print("[ OK ] %-12s  %s" % (description, " ".join(args)))

    print("=" * 60)
    print("Passed: %d  Failed: %d" % (passed, failed))
    return passed, failed
