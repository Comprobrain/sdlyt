"""Qt worker threads and bridges around the core services.

Every long-running call (search, thumbnail download, tools check) is
dispatched to a worker. ``DownloadManager`` and ``Player`` already run
their own worker threads; the bridges below marshal their callbacks
back to the Qt thread with signals.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

from ... import core


class SearchWorker(QThread):
    """Run ``core.ytdlp.search`` off the UI thread."""

    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, query: str) -> None:
        super().__init__()
        self._query = query

    def run(self) -> None:
        try:
            items = core.ytdlp.search(self._query)
        except core.ytdlp.YtDlpError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(str(exc))
            return
        self.finished.emit(items)


class ToolsWorker(QThread):
    """Run ``core.tools.check_tools`` off the UI thread."""

    finished = Signal(dict)

    def run(self) -> None:
        try:
            result = core.tools.check_tools()
        except Exception:
            result = {}
        self.finished.emit(result)


class _ThumbRunnable(QRunnable):
    def __init__(
        self,
        service: core.thumbs.ThumbService,
        video_id: str,
        bridge: "ThumbBridge",
    ) -> None:
        super().__init__()
        self._service = service
        self._video_id = video_id
        self._bridge = bridge

    def run(self) -> None:
        try:
            self._service.request(
                self._video_id,
                lambda pil: self._bridge._deliver(self._video_id, pil),
            )
        except Exception:
            self._bridge._deliver(self._video_id, None)


class ThumbBridge(QObject):
    """Marshal thumbnail results back onto the Qt thread."""

    ready = Signal(str, QPixmap)

    def __init__(
        self,
        service: core.thumbs.ThumbService,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._pool = QThreadPool.globalInstance()

    def request(self, video_id: str) -> None:
        """Fetch a thumbnail asynchronously; result is emitted via :attr:`ready`."""
        if not video_id:
            return
        self._pool.start(_ThumbRunnable(self._service, video_id, self))

    def _deliver(self, video_id: str, pil) -> None:
        if pil is None:
            return
        try:
            data = pil.tobytes("raw", "RGBA")
            image = QImage(
                data, pil.width, pil.height, QImage.Format_RGBA8888
            ).copy()
            pixmap = QPixmap.fromImage(image)
        except Exception:
            return
        self.ready.emit(video_id, pixmap)


class DownloadBridge(QObject):
    """Bridge ``core.downloads.DownloadManager`` callbacks to Qt signals."""

    job_updated = Signal(object)
    queue_changed = Signal()
    toast = Signal(str, str)

    def __init__(
        self,
        manager: core.downloads.DownloadManager,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        manager.on_update = self._on_update
        manager.on_toast = self._on_toast
        manager.on_change = self._on_change

    def _on_update(self, job) -> None:
        self.job_updated.emit(job)

    def _on_change(self) -> None:
        self.queue_changed.emit()

    def _on_toast(self, message: str, kind: str) -> None:
        self.toast.emit(message, kind)


class PlayerBridge(QObject):
    """Bridge ``core.player.Player`` callbacks to Qt signals."""

    status = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        player: core.player.Player,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.player = player
        player.on_status = self.status.emit
        player.on_error = self.error.emit