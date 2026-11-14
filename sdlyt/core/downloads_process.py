"""Download job lifecycle: spawn, read, parse progress, stall detection."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Optional

from . import downloads_format, errors, paths, resolutions, utils

if TYPE_CHECKING:
    from .downloads import DownloadJob


LOG_DIR = os.path.join(paths.APP_DIR, "logs")
STALL_AFTER_SECONDS = 20


class _ProcessMixin:
    """Internal download-process lifecycle for ``DownloadManager``."""

    def _start(self, job: "DownloadJob") -> None:
        if not self._disk_ok():
            job.state = "failed"
            job.err = "Disk is full."
            self._update(job)
            return

        if not job.log_path:
            job.log_path = os.path.join(
                LOG_DIR, "%d_%s.log" % (job.uid, job.video_id)
            )

        log = None
        try:
            log = open(job.log_path, "w", encoding="utf-8", errors="replace")
            log.write("# yt-dlp log for: %s\n" % job.title)
            log.write("# started: %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            log.flush()
        except OSError:
            log = None

        command = self._command(job)
        if log is not None:
            try:
                log.write("# CMD: %s\n" % " ".join(shlex.quote(a) for a in command))
                log.flush()
            except Exception:
                pass

        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except FileNotFoundError:
            job.state = "failed"
            job.err = "yt-dlp not found at %s." % command[0]
            self._update(job)
            if log is not None:
                log.close()
            return
        except Exception as exc:
            job.state = "failed"
            job.err = errors.friendly(str(exc))
            self._update(job)
            if log is not None:
                log.close()
            return

        job.state = "running"
        job.pct = 0.0
        job.phase = "fetching"
        job.info = "Fetching formats\u2026"
        self.procs[job.uid] = proc
        self._update(job)

        threading.Thread(
            target=self._monitor_stall, args=(job, proc), daemon=True
        ).start()
        threading.Thread(
            target=self._read, args=(job, proc, log), daemon=True
        ).start()

    def _command(self, job: "DownloadJob") -> list[str]:
        out_dir = str(self.settings.get("out_dir", paths.DEFAULT_OUT))
        os.makedirs(out_dir, exist_ok=True)

        ytdlp = getattr(self, "ytdlp_path", None) or paths.YT
        command: list[str] = [
            ytdlp,
            "--newline",
            "--progress",
            "--no-playlist",
            "--no-colors",
            "--no-simulate",
            "--retries", "10",
            "--fragment-retries", "10",
            "--progress-template",
            "download:DL|%(progress._percent_str)s"
            "|%(progress._speed_str)s|%(progress._eta_str)s"
            "|%(info.vcodec)s",
            "--print", "before_dl:SDLYT_RES|%(height)s",
            "-o", os.path.join(out_dir, "%(title).100B [%(id)s].%(ext)s"),
        ]

        if job.kind == "video":
            command += downloads_format.video_format_args(job.res)
            if job.subs:
                command += [
                    "--write-subs", "--write-auto-subs",
                    "--sub-langs", job.lang + ".*", "--embed-subs",
                ]
        else:
            command += downloads_format.audio_format_args(job.afmt)
            if job.embed:
                command += [
                    "--embed-thumbnail", "--embed-metadata",
                    "--convert-thumbnails", "jpg",
                ]

        return command + utils.cookie_args() + [
            "https://www.youtube.com/watch?v=" + job.video_id
        ]

    def _read(self, job: "DownloadJob", proc: subprocess.Popen, log) -> None:
        last_vcodec = ""
        error_line = ""
        try:
            for raw in proc.stdout:  # type: ignore[union-attr]
                if not raw:
                    break
                for line in raw.replace("\r", "\n").split("\n"):
                    if not line:
                        continue
                    if log is not None:
                        try:
                            log.write(line + "\n")
                            log.flush()
                        except Exception:
                            pass
                    try:
                        last_vcodec = self._process_line(
                            job, line, last_vcodec
                        )
                    except Exception as exc:
                        if log is not None:
                            try:
                                log.write("# [parse error] %r\n" % exc)
                                log.flush()
                            except Exception:
                                pass
                    if line.startswith("ERROR"):
                        error_line = line
        except Exception as exc:
            if not error_line:
                error_line = str(exc)

        try:
            returncode = proc.wait()
        except Exception:
            returncode = -1

        if log is not None:
            try:
                log.close()
            except Exception:
                pass

        self._finish(job, returncode, error_line)

    def _process_line(
        self, job: "DownloadJob", line: str, last_vcodec: str
    ) -> str:
        if line.startswith("DL|"):
            parts = line.split("|")
            if len(parts) >= 4:
                pct = self._parse_pct(parts[1])
                if pct is None:
                    return last_vcodec
                raw_vcodec = parts[4].strip().lower() if len(parts) >= 5 else ""
                if raw_vcodec == "none":
                    effective = "none"
                elif raw_vcodec in ("", "na", "n/a", "unknown"):
                    effective = last_vcodec
                else:
                    effective = raw_vcodec
                job.phase = "downloading"
                self._apply_progress(
                    job, pct, parts[2].strip(), parts[3].strip(), effective
                )
                self._update(job)
                return effective
            return last_vcodec

        if line.startswith("SDLYT_RES|"):
            try:
                height = int(float(line.split("|", 1)[1].strip()))
                if height > 0:
                    job.actual_height = height
            except (ValueError, IndexError, TypeError):
                pass
            return last_vcodec

        if self._try_default_progress(job, line, last_vcodec):
            return last_vcodec

        if "[Merger]" in line:
            job.phase = "merging"
            job.pct = max(job.pct, 96.0)
            job.info = "Merging\u2026"
            self._update(job)
            return last_vcodec

        if any(
            tag in line
            for tag in (
                "[ExtractAudio]", "[EmbedThumbnail]",
                "[Metadata]", "[EmbedSubtitle]",
            )
        ):
            job.phase = "processing"
            job.pct = max(job.pct, 97.0)
            job.info = "Processing\u2026"
            self._update(job)
            return last_vcodec

        if "has already been downloaded" in line:
            job.info = "Already downloaded"
            self._update(job)
            return last_vcodec

        return last_vcodec

    def _try_default_progress(
        self, job: "DownloadJob", line: str, vcodec: str
    ) -> bool:
        if "[download]" not in line or "%" not in line:
            return False
        match = re.search(r"\[download\]\s+([\d.]+)\s*%", line)
        if not match:
            return False
        try:
            pct = float(match.group(1))
        except ValueError:
            return False
        speed_m = re.search(r"\bat\s+(\S+)", line)
        eta_m = re.search(r"\bETA\s+(\S+)", line)
        speed = speed_m.group(1) if speed_m else "?"
        eta = eta_m.group(1) if eta_m else "?"
        job.phase = "downloading"
        self._apply_progress(job, pct, speed, eta, vcodec)
        self._update(job)
        return True

    def _monitor_stall(
        self, job: "DownloadJob", proc: subprocess.Popen
    ) -> None:
        while True:
            time.sleep(2.0)
            try:
                if proc.poll() is not None:
                    return
            except Exception:
                return
            if job.state != "running":
                return
            try:
                idle = time.time() - os.path.getmtime(job.log_path)
            except OSError:
                idle = STALL_AFTER_SECONDS
            if idle >= STALL_AFTER_SECONDS and job.state == "running":
                mins = int(idle // 60)
                secs = int(idle % 60)
                job.info = "Still working\u2026 (%dm %ds idle)" % (mins, secs)
                self._update(job)

    def _apply_progress(
        self,
        job: "DownloadJob",
        raw_pct: float,
        speed: str,
        eta: str,
        vcodec: str,
    ) -> None:
        if job.state != "running":
            return
        speed = speed or "?"
        eta = eta or "?"
        if job.kind == "audio":
            overall = raw_pct * 0.90
            label = "Audio"
        elif vcodec == "none":
            overall = 50.0 + raw_pct * 0.45
            label = "Audio"
        else:
            overall = raw_pct * 0.50
            label = "Video"
        job.pct = min(94.0, overall)
        job.info = "%s: %.1f%% \u00b7 %s \u00b7 ETA %s" % (
            label, raw_pct, speed, eta
        )

    @staticmethod
    def _parse_pct(raw: str) -> Optional[float]:
        if not raw:
            return None
        text = raw.strip().replace("%", "").strip()
        if text.lower() in ("n/a", "na", "unknown", ""):
            return None
        try:
            return float(text)
        except ValueError:
            match = re.search(r"[\d.]+", text)
            if match:
                try:
                    return float(match.group())
                except ValueError:
                    return None
        return None

    def _finish(
        self, job: "DownloadJob", returncode: int, error_line: str
    ) -> None:
        self.procs.pop(job.uid, None)
        if job.state == "running":
            if returncode == 0:
                job.state = "done"
                job.pct = 100.0
                job.info = "Done"
                job.phase = "done"
                if (
                    job.kind == "video"
                    and job.actual_height
                    and job.actual_height < job.res
                ):
                    self._toast(
                        "Requested %s, got %s. Saved the best available."
                        % (
                            resolutions.label(job.res),
                            resolutions.label(job.actual_height),
                        ),
                        "warn",
                    )
            else:
                job.state = "failed"
                job.phase = "failed"
                full_error = self._extract_last_error(error_line, job.log_path)
                if full_error:
                    job.err = errors.friendly(full_error)
                else:
                    job.err = (
                        "Download failed (exit %d). Log: %s"
                        % (returncode, job.log_path)
                    )
                self._toast(job.err, "err")
        self._update(job)
        self.save()
        self.pump()

    @staticmethod
    def _extract_last_error(error_line: str, log_path: str) -> str:
        if error_line:
            return error_line
        try:
            with open(log_path, encoding="utf-8", errors="replace") as handle:
                lines = [line for line in handle if line.strip()]
        except OSError:
            return ""
        errors_found = [line for line in lines if "ERROR" in line]
        if errors_found:
            return errors_found[-1]
        return " ".join(lines[-3:]) if lines else ""

    def _disk_ok(self) -> bool:
        out_dir = str(self.settings.get("out_dir", paths.DEFAULT_OUT))
        try:
            return shutil.disk_usage(out_dir).free > 200 * 1024 * 1024
        except Exception:
            return True
