"""Reusable PySide6 widgets for the modern UI."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import core
from . import theme


# ---------------------------------------------------------------------------
# Sidebar button
# ---------------------------------------------------------------------------
class SidebarButton(QPushButton):
    """Icon + label button used for the left navigation rail."""

    def __init__(
        self,
        icon_name: str,
        text: str,
        palette: theme.Palette,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self.setObjectName("SidebarButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setIconSize(QSize(18, 18))
        self._icon_name = icon_name
        self._palette = palette
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        color = self._palette.accent if self.isChecked() else self._palette.muted
        self.setIcon(theme.svg_icon_qicon(self._icon_name, color, 18))

    def refresh_palette(self, palette: theme.Palette) -> None:
        self._palette = palette
        self._refresh_icon()

    def setChecked(self, checked: bool) -> None:  # type: ignore[override]
        super().setChecked(checked)
        self._refresh_icon()


# ---------------------------------------------------------------------------
# Hover frame
# ---------------------------------------------------------------------------
class HoverFrame(QFrame):
    """Frame that animates a background swap on hover and selection."""

    def __init__(
        self,
        palette: theme.Palette,
        hover_color: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._hover_color = hover_color
        self._hovered = False
        self._selected = False
        self.setAttribute(Qt.WA_Hover, True)

    def refresh_palette(self, palette: theme.Palette) -> None:
        self._palette = palette
        self._apply()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._hovered = True
        self._apply()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hovered = False
        self._apply()
        super().leaveEvent(event)

    def _apply(self) -> None:
        if self._selected:
            color = self._palette.sel
        elif self._hovered:
            color = self._hover_color
        else:
            color = self._palette.card
        self.setStyleSheet(
            "QFrame { background-color: %s; border-radius: 12px; }" % color
        )


# ---------------------------------------------------------------------------
# Result card + list
# ---------------------------------------------------------------------------
class ResultCard(HoverFrame):
    """A single search/history/library row."""

    clicked = Signal()
    double_clicked = Signal()

    def __init__(
        self,
        palette: theme.Palette,
        item: dict,
        thumb_size: tuple[int, int],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(palette, palette.card_hover, parent)
        self.item = item
        self._thumb_size = thumb_size
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(thumb_size[1] + 16)
        self._apply()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self.thumb = QLabel(self)
        self.thumb.setFixedSize(*thumb_size)
        self.thumb.setStyleSheet(
            "background-color: %s; border-radius: 8px;" % palette.panel
        )
        self.thumb.setScaledContents(True)
        layout.addWidget(self.thumb)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.title_label = QLabel(item.get("title", "?"), self)
        self.title_label.setObjectName("Title")
        self.title_label.setWordWrap(True)
        text_col.addWidget(self.title_label)

        meta_text = item.get("meta", "") or item.get("channel", "")
        if item.get("length") and item["length"] != "NA":
            meta_text = (meta_text + "  ·  " + item["length"]).strip(" ·")
        self.meta_label = QLabel(meta_text, self)
        self.meta_label.setObjectName("Meta")
        text_col.addWidget(self.meta_label)

        layout.addLayout(text_col, 1)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self._thumb_size[0],
            self._thumb_size[1],
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.thumb.setPixmap(scaled)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class ResultListView(QScrollArea):
    """A vertical list of :class:`ResultCard` widgets."""

    selection_changed = Signal()
    open_requested = Signal()

    def __init__(
        self,
        palette: theme.Palette,
        empty_text: str,
        thumb_size: tuple[int, int],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._empty_text = empty_text
        self._thumb_size = thumb_size
        self._cards: list[ResultCard] = []
        self._items: list[dict] = []
        self._selected: Optional[int] = None

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.setWidget(self._container)
        self._render_empty()

    # -- public API ----------------------------------------------------
    def set_items(self, items: list[dict]) -> None:
        self._items = list(items)
        self._selected = None
        self._render()

    def selected_item(self) -> Optional[dict]:
        if self._selected is not None and 0 <= self._selected < len(self._items):
            return self._items[self._selected]
        return None

    def selected_items(self) -> list[dict]:
        item = self.selected_item()
        return [item] if item else []

    def set_thumbnail(self, video_id: str, pixmap: QPixmap) -> None:
        for index, item in enumerate(self._items):
            if item.get("id") == video_id and index < len(self._cards):
                self._cards[index].set_thumbnail(pixmap)
                break

    def refresh_palette(self, palette: theme.Palette) -> None:
        self._palette = palette
        for card in self._cards:
            card.refresh_palette(palette)

    # -- internals -----------------------------------------------------
    def _clear(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        while self._layout.count():
            entry = self._layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _render_empty(self) -> None:
        self._clear()
        label = QLabel(self._empty_text, self._container)
        label.setObjectName("Meta")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumHeight(120)
        self._layout.addWidget(label)
        self._layout.addStretch(1)

    def _render(self) -> None:
        self._clear()
        if not self._items:
            self._render_empty()
            return
        for index, item in enumerate(self._items):
            card = ResultCard(self._palette, item, self._thumb_size, self._container)
            card.clicked.connect(lambda idx=index: self._select(idx))
            card.double_clicked.connect(lambda idx=index: self._open(idx))
            self._layout.addWidget(card)
            self._cards.append(card)
        self._layout.addStretch(1)
        self.verticalScrollBar().setValue(0)

    def _select(self, index: int) -> None:
        if self._selected is not None and self._selected < len(self._cards):
            self._cards[self._selected].set_selected(False)
        self._selected = index
        if 0 <= index < len(self._cards):
            self._cards[index].set_selected(True)
        self.selection_changed.emit()

    def _open(self, index: int) -> None:
        self._select(index)
        self.open_requested.emit()


# ---------------------------------------------------------------------------
# Animated progress bar
# ---------------------------------------------------------------------------
class AnimatedProgressBar(QProgressBar):
    """Progress bar that eases from the previous value to the next one."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(6)
        self._animation = QPropertyAnimation(self, b"value", self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    def set_target(self, value: float) -> None:
        target = int(max(0.0, min(100.0, value)))
        if abs(self.value() - target) <= 1:
            self.setValue(target)
            return
        self._animation.stop()
        self._animation.setStartValue(self.value())
        self._animation.setEndValue(target)
        self._animation.start()


# ---------------------------------------------------------------------------
# Job row
# ---------------------------------------------------------------------------
class JobRow(QFrame):
    """A single download job row in the Queue page."""

    def __init__(
        self,
        palette: theme.Palette,
        job: core.downloads.DownloadJob,
        callbacks: dict[str, Callable[[core.downloads.DownloadJob], None]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.job = job
        self._callbacks = callbacks
        self._palette = palette
        self.setObjectName("ResultCard")
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("Title")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.progress = AnimatedProgressBar(self)
        layout.addWidget(self.progress)

        self.info_label = QLabel(self)
        self.info_label.setObjectName("Meta")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        button_row.addStretch(1)
        self.primary_btn = QPushButton(self)
        self.primary_btn.setCursor(Qt.PointingHandCursor)
        self.primary_btn.clicked.connect(self._on_primary)
        button_row.addWidget(self.primary_btn)
        self.remove_btn = QPushButton("Remove", self)
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.clicked.connect(self._on_remove)
        button_row.addWidget(self.remove_btn)
        layout.addLayout(button_row)

        self.refresh()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QFrame#ResultCard { background-color: %s; border-radius: 10px; }"
            % self._palette.card
        )

    def refresh_palette(self, palette: theme.Palette) -> None:
        self._palette = palette
        self._apply_style()
        self.refresh()

    def _on_primary(self) -> None:
        if self.job.state in ("queued", "running"):
            self._callbacks["cancel"](self.job)
        else:
            self._callbacks["retry"](self.job)

    def _on_remove(self) -> None:
        self._callbacks["remove"](self.job)

    def refresh(self) -> None:
        prefix = "[V] " if self.job.kind == "video" else "[A] "
        self.title_label.setText(prefix + self.job.title)
        self.progress.set_target(self.job.pct or 0.0)
        state = self.job.state
        text = {
            "queued": "Queued",
            "running": self.job.info or "Starting…",
            "done": "✓ Done",
            "failed": "✗ " + (self.job.err or "Failed"),
            "cancelled": "Cancelled — retry resumes",
            "paused": "Interrupted — retry resumes",
        }.get(state, state)
        color = {
            "done": self._palette.success,
            "failed": self._palette.danger,
        }.get(state, self._palette.muted)
        self.info_label.setStyleSheet("color: %s; background: transparent;" % color)
        self.info_label.setText(text)
        if state == "done":
            self.primary_btn.hide()
        else:
            self.primary_btn.show()
            self.primary_btn.setText(
                "Cancel" if state in ("queued", "running") else "Retry"
            )


# ---------------------------------------------------------------------------
# Toasts
# ---------------------------------------------------------------------------
class Toast(QWidget):
    """A single rounded toast with a fade in/out animation."""

    def __init__(
        self,
        palette: theme.Palette,
        message: str,
        kind: str,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        colors = {
            "info": palette.accent,
            "ok": palette.success,
            "err": palette.danger,
            "warn": palette.warn,
        }
        color = colors.get(kind, palette.accent)
        self.setStyleSheet(
            "background-color: %s; border-radius: 10px; color: #ffffff;" % color
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)
        icon = QLabel(self)
        icon_name = {"ok": "check", "err": "error", "warn": "warning"}.get(kind, "info")
        icon.setPixmap(theme.svg_icon(icon_name, "#ffffff", 16))
        icon.setStyleSheet("background: transparent;")
        layout.addWidget(icon)
        label = QLabel(message, self)
        label.setStyleSheet("color: #ffffff; font-weight: 600; background: transparent;")
        label.setWordWrap(True)
        layout.addWidget(label, 1)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

    def fade_in(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def fade_out(self, on_done: Callable[[], None]) -> None:
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(on_done)
        self._fade.start()


class ToastManager:
    """Stacked toasts anchored at the bottom of *anchor*."""

    def __init__(self, palette: theme.Palette, anchor: QWidget) -> None:
        self._palette = palette
        self._anchor = anchor
        self._active: list[Toast] = []

    def refresh_palette(self, palette: theme.Palette) -> None:
        self._palette = palette

    def show(self, message: str, kind: str = "info", duration_ms: int = 2400) -> None:
        toast = Toast(self._palette, message, kind, self._anchor)
        toast.adjustSize()
        self._active.append(toast)
        self._layout()
        toast.show()
        toast.fade_in()
        QTimer.singleShot(duration_ms, lambda: self._dismiss(toast))

    def _dismiss(self, toast: Toast) -> None:
        if toast not in self._active:
            return

        def finish() -> None:
            if toast in self._active:
                self._active.remove(toast)
            toast.deleteLater()
            self._layout()

        toast.fade_out(finish)

    def _layout(self) -> None:
        if not self._anchor:
            return
        width = self._anchor.width()
        height = self._anchor.height()
        y = height - 40
        for toast in reversed(self._active):
            toast.adjustSize()
            tw = min(max(240, width - 120), 520)
            th = max(toast.height(), 36)
            toast.resize(tw, th)
            x = (width - tw) // 2
            y -= th + 8
            toast.move(x, y)


# ---------------------------------------------------------------------------
# Page stack with fade transition
# ---------------------------------------------------------------------------
class PageStack(QStackedWidget):
    """``QStackedWidget`` with an optional fade transition."""

    def __init__(
        self,
        reduce_animations: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._reduce = reduce_animations

    def set_reduce_animations(self, reduce: bool) -> None:
        self._reduce = reduce

    def slide_to(self, index: int) -> None:
        if index == self.currentIndex():
            return
        target = self.widget(index)
        if target is None or self._reduce:
            self.setCurrentIndex(index)
            return
        self.setCurrentIndex(index)
        effect = QGraphicsOpacityEffect(target)
        target.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", target)
        animation.setDuration(180)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(lambda: target.setGraphicsEffect(None))
        animation.start(QPropertyAnimation.DeleteWhenStopped)