"""Download queue: job state, persistence and public API.

The process lifecycle (spawn, read, stall detection, finish) lives in
``sdlyt.core.downloads_process`` and is mixed into ``DownloadManager``.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from typing import Callable, Optional

from . import paths, utils
from .downloads_process import LOG_DIR, _ProcessMixin


UpdateCallback = Callable[["DownloadJob"], None]
ToastCallback = Callable[[str, str], None]
ChangeCallback = Callable[[], None]


@dataclass
class DownloadJob:
    """A single queued or running download."""

    uid: int
    video_id: str
    title: str
    kind: str
    state: str = "queued"
    pct: float = 0.0
    info: str = ""
    err: str = ""
    res: int = 720
    afmt: str = "m4a"
    subs: bool = False
    lang: str = "en"
    embed: bool = True
    actual_height: Optional[int] = None
    phase: str = ""
    log_path: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict, uid: int) -> "DownloadJob":
        """Build a job from persisted data, clamping interrupted states."""
        state = data.get("state", "queued")
        if state in ("running", "queued"):
            state = "paused"
        return cls(
            uid=uid,
            video_id=data.get("id", data.get("video_id", "")),
            title=data.get("title", ""),
            kind=data.get("kind", "video"),
            state=state,
            pct=float(data.get("pct", 0) or 0),
            info=data.get("info", ""),
            err=data.get("err", ""),
            res=int(data.get("res", 720)),
            afmt=data.get("afmt", "m4a"),
            subs=bool(data.get("subs", False)),
            lang=data.get("lang", "en"),
            embed=bool(data.get("embed", True)),
            actual_height=data.get("actual_height"),
            phase=data.get("phase", ""),
            log_path=data.get("log_path", ""),
        )


class DownloadManager(_ProcessMixin):
    """Owns the download queue and its worker processes."""

    def __init__(
        self,
        settings,
        on_update: Optional[UpdateCallback] = None,
        on_toast: Optional[ToastCallback] = None,
        on_change: Optional[ChangeCallback] = None,
    ) -> None:
        self.settings = settings
        self.on_update = on_update
        self.on_toast = on_toast
        self.on_change = on_change
        self.jobs: list[DownloadJob] = []
        self.procs: dict[int, subprocess.Popen] = {}
        self._uid = 0
        self._lock = threading.Lock()
        os.makedirs(LOG_DIR, exist_ok=True)
        self.load()

    def load(self) -> None:
        """Load the persisted queue, pausing interrupted jobs."""
        for raw in utils.jload(paths.QUEUEF, []):
            if not isinstance(raw, dict):
                continue
            self._uid += 1
            job = DownloadJob.from_dict(raw, self._uid)
            if not job.log_path:
                job.log_path = os.path.join(
                    LOG_DIR, "%d_%s.log" % (job.uid, job.video_id)
                )
            self.jobs.append(job)

    def save(self) -> None:
        """Persist all jobs that are not finished."""
        utils.jsave(
            paths.QUEUEF,
            [job.to_dict() for job in self.jobs if job.state != "done"],
        )

    def add(self, item: dict, kind: str) -> bool:
        """Queue a download. Returns False for duplicates."""
        video_id = item.get("id", "")
        if any(
            job.video_id == video_id
            and job.kind == kind
            and job.state in ("queued", "running")
            for job in self.jobs
        ):
            return False

        self._uid += 1
        job = DownloadJob(
            uid=self._uid,
            video_id=video_id,
            title=item.get("title", ""),
            kind=kind,
            res=int(self.settings.get("dl_res", 720)),
            afmt=str(self.settings.get("audio_fmt", "m4a")),
            subs=bool(self.settings.get("subs", False)),
            lang=self.settings.sub_language(),
            embed=bool(self.settings.get("embed", True)),
        )
        job.log_path = os.path.join(
            LOG_DIR, "%d_%s.log" % (job.uid, video_id)
        )
        self.jobs.append(job)
        self.save()
        self._changed()
        self.pump()
        return True

    def pump(self) -> None:
        """Start queued jobs up to the parallel limit."""
        limit = max(1, int(self.settings.get("parallel", 1)))
        running = sum(1 for job in self.jobs if job.state == "running")
        for job in self.jobs:
            if running >= limit:
                break
            if job.state == "queued":
                self._start(job)
                running += 1
        self._changed()

    def cancel(self, job: DownloadJob) -> None:
        """Cancel a queued or running job."""
        proc = self.procs.pop(job.uid, None)
        job.state = "cancelled"
        job.info = "Cancelled"
        job.phase = "cancelled"
        if proc:
            utils.kill_group(proc)
        self._update(job)
        self.save()
        self.pump()

    def retry(self, job: DownloadJob) -> None:
        """Re-queue a failed, cancelled or paused job."""
        job.state = "queued"
        job.err = ""
        job.pct = 0.0
        job.info = ""
        job.phase = ""
        self._update(job)
        self.save()
        self.pump()

    def remove(self, job: DownloadJob) -> None:
        """Cancel and remove a job from the queue."""
        proc = self.procs.pop(job.uid, None)
        job.state = "cancelled"
        if proc:
            utils.kill_group(proc)
        with self._lock:
            if job in self.jobs:
                self.jobs.remove(job)
        self.save()
        self.pump()

    def clear_done(self) -> None:
        """Remove every finished job."""
        for job in [j for j in self.jobs if j.state == "done"]:
            self.remove(job)

    def retry_all(self) -> None:
        """Retry every failed, cancelled or paused job."""
        for job in self.jobs:
            if job.state in ("failed", "cancelled", "paused"):
                job.state = "queued"
                job.err = ""
                self._update(job)
        self.save()
        self.pump()

    def stop_all(self) -> None:
        """Pause running jobs and terminate their processes."""
        for job in self.jobs:
            if job.state == "running":
                job.state = "paused"
                proc = self.procs.pop(job.uid, None)
                if proc:
                    utils.kill_group(proc)
                self._update(job)
        self.save()

    def open_log(self, job: DownloadJob) -> bool:
        """Try to open the job's log file in the system viewer."""
        if not job.log_path or not os.path.exists(job.log_path):
            return False
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", job.log_path])
            elif os.name == "nt":
                os.startfile(job.log_path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(
                    ["xdg-open", job.log_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return True
        except Exception:
            return False

    def _update(self, job: DownloadJob) -> None:
        if self.on_update:
            try:
                self.on_update(job)
            except Exception:
                pass

    def _toast(self, message: str, kind: str) -> None:
        if self.on_toast:
            try:
                self.on_toast(message, kind)
            except Exception:
                pass

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass
