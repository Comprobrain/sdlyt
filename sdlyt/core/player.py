"""Playback via mpv (preferred) or VLC."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from typing import Callable, Optional

from . import errors, paths, resolutions, settings as settings_module, utils

StatusCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]


class Player:
    """Spawn and control an external media player."""

    def __init__(
        self,
        settings: settings_module.Settings,
        on_status: Optional[StatusCallback] = None,
        on_error: Optional[ErrorCallback] = None,
    ) -> None:
        self.settings = settings
        self.on_status = on_status
        self.on_error = on_error
        self.proc: Optional[subprocess.Popen] = None
        self._label = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def play_url(self, video_id: str, audio_only: bool = False, title: str = "") -> None:
        """Play a YouTube video by ID."""
        args = ["--script-opts=ytdl_hook-ytdl_path=" + paths.YT]
        raw: list[str] = []
        if os.path.exists(paths.COOKIES):
            raw.append("cookies=" + paths.COOKIES)

        if audio_only:
            args += ["--no-video", "--force-window=no", "--ytdl-format=ba[ext=m4a]/ba"]
        else:
            args.append(
                "--ytdl-format=" + resolutions.play_fmt(int(self.settings.get("play_res", 480)))
            )
            if self.settings.get("subs"):
                language = self.settings.sub_language()
                raw += [
                    "write-subs=",
                    "write-auto-subs=",
                    "sub-langs=" + language + ".*",
                ]
                args += ["--sid=auto", "--slang=" + language]
            else:
                args.append("--sid=no")

        if raw:
            args.append("--ytdl-raw-options=" + ",".join(raw))
        args.append("https://www.youtube.com/watch?v=" + video_id)

        label = ("Listening: " if audio_only else "Playing: ") + title[:40]
        self._run_mpv(args, label)

    def play_local(self, path: str, audio: bool = False, label: str = "") -> None:
        """Play a local file with mpv or VLC."""
        if self.settings.get("local_player") == "vlc" and shutil.which("vlc"):
            command = ["vlc", "--play-and-exit"]
            if audio:
                command.append("--no-video")
            elif self.settings.get("fs"):
                command.append("--fullscreen")
            self._spawn(command + [path], label or os.path.basename(path))
            return

        args = [path]
        if audio:
            args = ["--no-video", "--force-window=no"] + args
        self._run_mpv(args, label or os.path.basename(path))

    def stop(self) -> None:
        """Stop the current playback process."""
        proc = self.proc
        self.proc = None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _run_mpv(
        self,
        args: list[str],
        label: str,
        retry_no_hwdec: bool = False,
    ) -> None:
        command = [
            "mpv",
            "--speed=%s" % self.settings.get("speed", 1.0),
            "--volume=%d" % int(self.settings.get("volume", 100)),
        ]
        if self.settings.get("fs"):
            command.append("--fs")
        if self.settings.get("hwdec") and not retry_no_hwdec:
            command.append("--hwdec=auto-safe")
        self._spawn(
            command + args,
            label,
            original_args=args,
            retry_no_hwdec=retry_no_hwdec,
        )

    def _spawn(
        self,
        command: list[str],
        label: str,
        original_args: Optional[list[str]] = None,
        retry_no_hwdec: bool = False,
    ) -> None:
        self.stop()
        try:
            log = open(paths.MPVLOG, "w", encoding="utf-8")
            proc = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=log
            )
            log.close()
        except FileNotFoundError:
            self._error("%s is not installed. Check Settings → Tools." % command[0])
            return

        self.proc = proc
        self._label = label
        if self.on_status:
            self.on_status(label)

        def waiter() -> None:
            returncode = proc.wait()
            if self.proc is not proc:
                return
            if returncode in (1, 2, 3):
                tail = ""
                try:
                    with open(paths.MPVLOG, encoding="utf-8", errors="replace") as handle:
                        tail = handle.read()[-2000:]
                except Exception:
                    pass

                if (
                    not retry_no_hwdec
                    and self.settings.get("hwdec")
                    and original_args
                ):
                    if self.on_status:
                        self.on_status("Hardware decode failed — retrying without it")
                    self._run_mpv(original_args, label, retry_no_hwdec=True)
                    return

                self._error(
                    "Can't play: "
                    + (errors.friendly(tail) if tail.strip() else "unknown error")
                )
            elif self.on_status:
                self.on_status("Ready")

        threading.Thread(target=waiter, daemon=True).start()

    def _error(self, message: str) -> None:
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass