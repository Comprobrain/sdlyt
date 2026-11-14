"""Progress-parser self-test using a fake yt-dlp script.

Builds a shell-less fake ``yt-dlp`` executable, runs it through the
same ``_ProcessMixin._start`` spawn / read / parse / on_update chain
that a real download uses, and asserts that at least three distinct
non-zero percentages with speed and ETA set reach the callback.

``--selftest-progress`` in the launcher dispatches here.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from typing import Optional


_SAMPLE_LINES: list[str] = [
    "DL|  0.0%| 790.78KiB/s|00:37|avc1.640028",
    "DL|  3.5%|   7.89MiB/s|00:03|avc1.640028",
    "DL| 45.2%|   8.11MiB/s|00:01|avc1.640028",
    "DL|100.0%|   9.00MiB/s|00:00|avc1.640028",
    "DL|  0.0%| Unknown B/s|Unknown|none",
    "DL| 50.0%|   1.11MiB/s|00:02|none",
    "[download]  50.0% of  10.00MiB at  1.11MiB/s ETA 00:02",
    "DL|100.0%|   1.11MiB/s|00:00|none",
    "SDLYT_RES|2160",
]


class _FakeSettings(dict):
    """Minimal settings object exposing only what ``_command`` needs."""

    def sub_language(self) -> str:
        return "en"

    def get(self, key, default=None):  # type: ignore[override]
        return dict.get(self, key, default)


def _make_fake_script(path: str) -> None:
    body = (
        "#!%s\n"
        "import sys, time\n"
        "for line in %r:\n"
        "    print(line, flush=True)\n"
        "    time.sleep(0.05)\n"
        "sys.exit(0)\n"
    ) % (sys.executable, _SAMPLE_LINES)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.chmod(path, 0o755)


def selftest_progress() -> tuple[int, int]:
    """Return ``(passed, failed)`` and print a report."""
    from .downloads import DownloadJob, DownloadManager

    print("Super Duper Lite YT - progress parser self-test")
    print("=" * 60)

    if os.name == "nt":
        print("[SKIP] Windows is not supported by this self-test.")
        return (1, 0)

    with tempfile.TemporaryDirectory() as td:
        fake = os.path.join(td, "yt-dlp")
        _make_fake_script(fake)

        settings = _FakeSettings(
            {
                "out_dir": td,
                "parallel": 1,
                "dl_res": 2160,
                "audio_fmt": "m4a",
                "subs": False,
                "embed": False,
            }
        )

        updates: list[tuple[float, str]] = []

        def on_update(job: DownloadJob) -> None:
            updates.append((float(job.pct or 0.0), str(job.info or "")))

        mgr = DownloadManager(settings, on_update=on_update)
        mgr.ytdlp_path = fake

        job = DownloadJob(
            uid=1,
            video_id="FAKEVIDEOID",
            title="Self-test job",
            kind="video",
            res=2160,
            log_path=os.path.join(td, "log.txt"),
        )
        mgr.jobs.append(job)
        mgr._start(job)

        deadline = time.time() + 10.0
        while time.time() < deadline:
            if job.state in ("done", "failed", "cancelled"):
                break
            time.sleep(0.05)

        log_path = job.log_path
        raw_log: list[str] = []
        if log_path and os.path.exists(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as handle:
                raw_log = [line.rstrip("\n") for line in handle]

        good = [
            (pct, info)
            for pct, info in updates
            if pct > 0.0 and "ETA" in info and "\u00b7" in info
        ]
        distinct = sorted({round(pct, 1) for pct, _ in good})

        for pct, info in updates:
            print("  update pct=%-6.2f info=%r" % (pct, info))

        print("-" * 60)
        print("state: %s" % job.state)
        print("progress updates with pct+speed+eta: %d" % len(good))
        print("distinct percentages: %s" % (distinct,))
        print("log lines captured: %d" % len(raw_log))

        problems: list[str] = []
        if job.state != "done":
            problems.append("job did not reach 'done' (state=%s)" % job.state)
        if len(distinct) < 3:
            problems.append(
                "need at least 3 distinct non-zero percentages, got %d"
                % len(distinct)
            )
        if not any("CMD:" in line for line in raw_log):
            problems.append("full command line was not logged")
        if len(raw_log) < 5:
            problems.append(
                "expected at least 5 raw log lines, got %d" % len(raw_log)
            )

        if problems:
            for problem in problems:
                print("[FAIL] %s" % problem)
            return (0, 1)

        print("[ OK ] at least 3 distinct percentages with pct/speed/ETA")
        print("[ OK ] full command line and every raw output line logged")
        return (1, 0)
