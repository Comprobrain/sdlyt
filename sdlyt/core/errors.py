"""Friendly error-message mapping for yt-dlp, mpv and download failures."""
from __future__ import annotations

import re

ERR_MAP: list[tuple[str, str]] = [
    (r"confirm your age|age[- ]restricted|age verification",
     "Age-restricted. Import cookies (Account tab)."),
    (r"not a bot|sign in to confirm|login required",
     "YouTube wants a login. Import cookies (Account tab)."),
    (r"private video", "This video is private."),
    (r"members[- ]only|join this channel", "Members-only video."),
    (r"not available in your country|geo.?restrict",
     "Not available in your country."),
    (r"premieres in|live event will begin|will begin in", "Not live yet."),
    (r"video unavailable|has been removed|no longer available|account.*terminated",
     "Video unavailable or removed."),
    (r"http error 429|too many requests",
     "Too many requests (429). Wait a bit, then Retry."),
    (r"http error 403|403: forbidden",
     "YouTube blocked it (403). Update yt-dlp in Settings."),
    (r"ssl|certificate verify failed|certificate is not yet valid",
     "SSL error — check your system clock (Settings → Date & Time)."),
    (r"unable to extract|signature extraction|nsig|"
     r"requested format is not available|only images are available|"
     r"no video formats|please report this issue|update yt-dlp",
     "yt-dlp is out of date. Update yt-dlp in Settings."),
    (r"(ffmpeg|ffprobe).{0,40}not (found|installed)|ffmpeg is not installed",
     "ffmpeg is missing. Install it from Tools."),
    (r"no space left", "Disk is full."),
    (r"no such file or directory.*yt-dlp|yt-dlp.*no such file",
     "yt-dlp not found at ~/bin/yt-dlp."),
    (r"permission denied", "Permission denied. Check the download folder."),
    (r"name resolution|name or service not known|network is unreachable|"
     r"unable to download (webpage|api)|timed out|"
     r"connection (reset|refused|aborted)|failed to resolve|getaddrinfo",
     "No internet connection."),
]


def friendly(raw: str) -> str:
    """Convert raw tool output into a short, human-readable message."""
    text = (raw or "").strip()
    low = text.lower()
    for pattern, message in ERR_MAP:
        if re.search(pattern, low):
            return message

    lines = [line for line in text.splitlines() if line.strip()]
    error_lines = [line for line in lines if "ERROR" in line]
    line = (error_lines or lines or ["Unknown error"])[-1]
    line = re.sub(r"^.*?ERROR:\s*", "", line)
    line = re.sub(r"^\[[^\]]+\]\s*[\w-]+:\s*", "", line)
    return line[:110]