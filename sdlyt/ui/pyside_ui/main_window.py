"""The PySide6 main window for Super Duper Lite YT.

Contains only view logic. Search, downloads, playback, thumbnails,
history, settings and tool detection are all delegated to
:mod:`sdlyt.core`, with worker threads and bridge signals in
:mod:`sdlyt.ui.pyside_ui.workers`.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from tkinter import filedialog, messagebox  # reused only for file/ask dialogs

from PySide6.QtCore import QSize, Qt, QTimer, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ... import core
from ...core import resolutions, system_profile
from . import theme, widgets, workers

UI_LABELS = {
    "auto": "Auto",
    "tk": "Tkinter",
    "ctk": "CustomTkinter",
    "pyside6": "PySide6",
}
LABEL_TO_UI = {v: k for k, v in UI_LABELS.items()}
SLEEP_STEPS = (0, 15, 30, 45, 60, 90)
PAGES = ("Find", "Hist", "Lib", "Queue", "Set", "Acct")


def _human(size: float) -> str:
    return core.utils.human(size)


class MainWindow(QMainWindow):
    """Top-level window."""

    def __init__(self, settings: core.settings.Settings) -> None:
        super().__init__()
        self.settings = settings
        self.palette = theme.palette_for(str(settings.get("appearance", "dark")))
        self.reduce_animations = bool(settings.get("reduce_animations"))

        self.setWindowTitle("Super Duper Lite YT")
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available is not None:
            width = available.width()
            height = available.height()
        else:
            width, height = 1024, 720
        self.win_width = width
        self.win_height = height
        self.resize(width, height)
        self.setMinimumSize(360, 240)

        self.compact = system_profile.is_low_ram() or width < 600
        self.thumb_size = self._compute_thumb(width)

        # Services ----------------------------------------------------
        self.history = core.history.History()
        self.thumbs = core.thumbs.ThumbService(
            size=self.thumb_size,
            enabled=bool(settings.get("thumbs")) and core.thumbs.HAVE_PIL,
        )
        self.player = core.player.Player(settings)
        self.downloads = core.downloads.DownloadManager(settings)

        # Bridges -----------------------------------------------------
        self.thumb_bridge = workers.ThumbBridge(self.thumbs, self)
        self.dl_bridge = workers.DownloadBridge(self.downloads, self)
        self.player_bridge = workers.PlayerBridge(self.player, self)

        # State -------------------------------------------------------
        self.recent: list[str] = core.utils.jload(core.paths.RECENT, []) or []
        self.sleep_end = 0
        self.sleep_i = 0
        self.job_rows: dict[int, widgets.JobRow] = {}
        self._search_worker: workers.SearchWorker | None = None
        self._tools_worker: workers.ToolsWorker | None = None
        self._tool_labels: dict[str, QLabel] = {}

        # Build & wire ------------------------------------------------
        self._build_ui()
        self._connect_signals()
        self._apply_theme()
        self._refresh_history()
        self._refresh_library()
        self._sync_queue_rows()

        QTimer.singleShot(400, self._startup)
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)

    # ------------------------------------------------------------------
    # Theme / sizing
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_thumb(screen_w: int) -> tuple[int, int]:
        if screen_w < 480:
            return (56, 32)
        if screen_w < 768:
            return (72, 40)
        if screen_w < 1280:
            return (96, 54)
        return (112, 63)

    def _apply_theme(self) -> None:
        self.palette = theme.palette_for(str(self.settings.get("appearance", "dark")))
        self.setStyleSheet(theme.build_qss(self.palette, compact=self.compact))
        self.toasts.refresh_palette(self.palette)
        for widget in self.findChildren(QWidget):
            refresh = getattr(widget, "refresh_palette", None)
            if callable(refresh):
                try:
                    refresh(self.palette)
                except Exception:
                    pass

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_sidebar_width()

    def _update_sidebar_width(self) -> None:
        if not hasattr(self, "sidebar"):
            return
        if self.width() < 700:
            self.sidebar.setFixedWidth(64)
            for button in self.sidebar_buttons.values():
                button.setText("")
                button.setToolTip(next(
                    name for name, b in self.sidebar_buttons.items() if b is button
                ))
        else:
            self.sidebar.setFixedWidth(180)
            for name, button in self.sidebar_buttons.items():
                button.setText(name)
                button.setToolTip("")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Sidebar -----------------------------------------------------
        self.sidebar = QFrame(root)
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(180)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        sidebar_layout.setSpacing(4)

        title = QLabel("▶ SDLYT", self.sidebar)
        title.setObjectName("Header")
        sidebar_layout.addWidget(title)
        sidebar_layout.addSpacing(8)

        self.sidebar_buttons: dict[str, widgets.SidebarButton] = {}
        self.sidebar_group = QButtonGroup(self)
        self.sidebar_group.setExclusive(True)
        icons = {
            "Find": "search",
            "Hist": "history",
            "Lib": "library",
            "Queue": "queue",
            "Set": "settings",
            "Acct": "account",
        }
        for name in PAGES:
            button = widgets.SidebarButton(icons[name], name, self.palette, self.sidebar)
            button.clicked.connect(lambda _checked=False, n=name: self._navigate_to(n))
            sidebar_layout.addWidget(button)
            self.sidebar_buttons[name] = button
            self.sidebar_group.addButton(button)
        sidebar_layout.addStretch(1)

        outer.addWidget(self.sidebar)

        # Main column -------------------------------------------------
        main_column = QWidget(root)
        main_layout = QVBoxLayout(main_column)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Top bar
        self.topbar = QFrame(main_column)
        self.topbar.setObjectName("TopBar")
        top_layout = QHBoxLayout(self.topbar)
        top_layout.setContentsMargins(10, 6, 10, 6)
        top_layout.setSpacing(8)
        self.search_field = QLineEdit(self.topbar)
        self.search_field.setObjectName("SearchField")
        self.search_field.setPlaceholderText("Search YouTube…")
        self.search_field.returnPressed.connect(self._on_search_enter)
        top_layout.addWidget(self.search_field, 1)
        self.status_label = QLabel("Ready", self.topbar)
        self.status_label.setObjectName("Meta")
        top_layout.addWidget(self.status_label)
        main_layout.addWidget(self.topbar)

        # Page stack
        self.pages = widgets.PageStack(self.reduce_animations, main_column)
        main_layout.addWidget(self.pages, 1)

        # Bottom bar
        self.bottombar = QFrame(main_column)
        self.bottombar.setObjectName("BottomBar")
        bottom_layout = QHBoxLayout(self.bottombar)
        bottom_layout.setContentsMargins(10, 6, 10, 6)
        bottom_layout.setSpacing(8)

        self.sleep_btn = QPushButton("Zzz off", self.bottombar)
        self.sleep_btn.clicked.connect(self._cycle_sleep)
        bottom_layout.addWidget(self.sleep_btn)

        bottom_layout.addStretch(1)

        volume_icon = QLabel(self.bottombar)
        volume_icon.setPixmap(theme.svg_icon("volume", self.palette.fg, 16))
        bottom_layout.addWidget(volume_icon)
        self.volume_slider = QSlider(Qt.Horizontal, self.bottombar)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.settings.get("volume", 100)))
        self.volume_slider.setFixedWidth(140)
        self.volume_slider.valueChanged.connect(self._on_volume)
        bottom_layout.addWidget(self.volume_slider)

        stop_btn = QPushButton("Stop", self.bottombar)
        stop_btn.setIcon(theme.svg_icon_qicon("stop", self.palette.fg, 14))
        stop_btn.clicked.connect(self.player.stop)
        bottom_layout.addWidget(stop_btn)

        main_layout.addWidget(self.bottombar)

        outer.addWidget(main_column, 1)

        # Pages -------------------------------------------------------
        self.find_page = self._build_find_page()
        self.hist_page = self._build_hist_page()
        self.lib_page = self._build_lib_page()
        self.queue_page = self._build_queue_page()
        self.set_page = self._build_settings_page()
        self.acct_page = self._build_account_page()

        for page in (
            self.find_page, self.hist_page, self.lib_page,
            self.queue_page, self.set_page, self.acct_page,
        ):
            self.pages.addWidget(page)

        # Toast manager
        self.toasts = widgets.ToastManager(self.palette, self)

        # Initial page
        self._navigate_to("Find")

    # -- Find ----------------------------------------------------------
    def _build_find_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        for text, command, primary in (
            ("▶ Play", lambda: self._do_play(self._current_list(), False), True),
            ("♪ Listen", lambda: self._do_play(self._current_list(), True), False),
            ("Download video", lambda: self._do_dl(self._current_list(), "video"), False),
            ("Download audio", lambda: self._do_dl(self._current_list(), "audio"), False),
        ):
            button = QPushButton(text)
            if primary:
                button.setObjectName("Primary")
            button.clicked.connect(command)
            actions.addWidget(button)
        actions.addStretch(1)

        self.audio_only_cb = QCheckBox("Audio only")
        self.audio_only_cb.setChecked(bool(self.settings.get("audio_only")))
        self.audio_only_cb.toggled.connect(
            lambda checked: self.settings.set("audio_only", bool(checked))
        )
        actions.addWidget(self.audio_only_cb)
        layout.addLayout(actions)

        self.find_list = widgets.ResultListView(
            self.palette,
            "Search for a video, song or channel.\n"
            "Click once to select, double-click to play.",
            self.thumb_size,
            page,
        )
        self.find_list.open_requested.connect(
            lambda: self._do_play(self.find_list, self.audio_only_cb.isChecked())
        )
        layout.addWidget(self.find_list, 1)
        return page

    # -- Hist ----------------------------------------------------------
    def _build_hist_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        clear = QPushButton("Clear history")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear_history)
        header.addWidget(clear)
        header.addStretch(1)
        layout.addLayout(header)

        self.hist_list = widgets.ResultListView(
            self.palette, "Nothing played yet.", self.thumb_size, page,
        )
        self.hist_list.open_requested.connect(
            lambda: self._do_play(self.hist_list, self.audio_only_cb.isChecked())
        )
        layout.addWidget(self.hist_list, 1)
        return page

    # -- Lib -----------------------------------------------------------
    def _build_lib_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.lib_summary = QLabel("")
        self.lib_summary.setObjectName("Meta")
        header.addWidget(self.lib_summary, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_library)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.lib_list = widgets.ResultListView(
            self.palette,
            "No downloads yet.\nUse Download video or Download audio on a result.",
            self.thumb_size,
            page,
        )
        self.lib_list.open_requested.connect(self._play_library_item)
        layout.addWidget(self.lib_list, 1)
        return page

    # -- Queue ---------------------------------------------------------
    def _build_queue_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        clear_done = QPushButton("Clear done")
        clear_done.clicked.connect(self.downloads.clear_done)
        header.addWidget(clear_done)
        retry_all = QPushButton("Retry all")
        retry_all.clicked.connect(self.downloads.retry_all)
        header.addWidget(retry_all)
        header.addStretch(1)
        self.queue_summary = QLabel("Queue is empty")
        self.queue_summary.setObjectName("Meta")
        header.addWidget(self.queue_summary)
        layout.addLayout(header)

        self.queue_scroll = QScrollArea(page)
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setFrameShape(QFrame.NoFrame)
        self.queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.queue_container = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_container)
        self.queue_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_layout.setSpacing(6)
        self.queue_layout.addStretch(1)
        self.queue_scroll.setWidget(self.queue_container)
        layout.addWidget(self.queue_scroll, 1)

        return page

    # -- Settings ------------------------------------------------------
    def _build_settings_page(self) -> QWidget:
        page = QWidget(self)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        def header(text: str) -> None:
            label = QLabel(text)
            label.setObjectName("Header")
            layout.addWidget(label)

        def add_row(label_text: str, widget: QWidget) -> None:
            row = QHBoxLayout()
            row.setSpacing(6)
            label = QLabel(label_text)
            label.setMinimumWidth(140)
            row.addWidget(label)
            row.addWidget(widget, 1)
            layout.addLayout(row)

        # Interface
        header("Interface")
        self.interface_combo = QComboBox()
        for value, label in UI_LABELS.items():
            self.interface_combo.addItem(label, value)
        current = str(self.settings.get("ui", "auto"))
        for index in range(self.interface_combo.count()):
            if self.interface_combo.itemData(index) == current:
                self.interface_combo.setCurrentIndex(index)
                break
        self.interface_combo.currentIndexChanged.connect(self._on_interface_changed)
        add_row("UI", self.interface_combo)

        restart_btn = QPushButton("Restart to apply")
        restart_btn.clicked.connect(self._restart_app)
        layout.addWidget(restart_btn)

        # Playback
        header("Playback")
        self.play_res_combo = self._make_resolution_combo("play_res")
        add_row("Play quality", self.play_res_combo)
        self.speed_combo = self._make_options_combo("speed", (0.75, 1.0, 1.25, 1.5))
        add_row("Speed", self.speed_combo)
        self.fs_cb = QCheckBox("Fullscreen playback")
        self.fs_cb.setChecked(bool(self.settings.get("fs")))
        self.fs_cb.toggled.connect(lambda v: self.settings.set("fs", bool(v)))
        layout.addWidget(self.fs_cb)
        self.hwdec_cb = QCheckBox("Hardware decode")
        self.hwdec_cb.setChecked(bool(self.settings.get("hwdec")))
        self.hwdec_cb.toggled.connect(lambda v: self.settings.set("hwdec", bool(v)))
        layout.addWidget(self.hwdec_cb)

        # Downloads
        header("Downloads")
        self.dl_res_combo = self._make_resolution_combo("dl_res")
        add_row("Download quality", self.dl_res_combo)
        self.container_note = QLabel("")
        self.container_note.setObjectName("Meta")
        self.container_note.setWordWrap(True)
        layout.addWidget(self.container_note)
        self._refresh_container_note()

        self.afmt_combo = self._make_options_combo("audio_fmt", ("m4a", "mp3"))
        add_row("Audio format", self.afmt_combo)
        self.parallel_combo = self._make_options_combo("parallel", (1, 2, 3))
        add_row("Parallel downloads", self.parallel_combo)

        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        out_row.addWidget(QLabel("Folder"))
        self.out_dir_label = QLabel(str(self.settings.get("out_dir", "")))
        self.out_dir_label.setObjectName("Meta")
        self.out_dir_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        out_row.addWidget(self.out_dir_label, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_out_dir)
        out_row.addWidget(browse)
        layout.addLayout(out_row)

        self.embed_cb = QCheckBox("Embed thumbnail + metadata")
        self.embed_cb.setChecked(bool(self.settings.get("embed")))
        self.embed_cb.toggled.connect(lambda v: self.settings.set("embed", bool(v)))
        layout.addWidget(self.embed_cb)

        # Subtitles
        header("Subtitles")
        self.subs_cb = QCheckBox("Show / download subtitles")
        self.subs_cb.setChecked(bool(self.settings.get("subs")))
        self.subs_cb.toggled.connect(lambda v: self.settings.set("subs", bool(v)))
        layout.addWidget(self.subs_cb)
        self.lang_combo = self._make_options_combo(
            "sub_lang",
            ("en", "ar", "fr", "es", "de", "tr", "ur", "hi", "pt", "ru", "id"),
        )
        add_row("Language", self.lang_combo)

        # Appearance
        header("Appearance")
        self.mode_combo = self._make_options_combo(
            "appearance", ("dark", "light", "system")
        )
        add_row("Mode", self.mode_combo)
        self.font_combo = self._make_options_combo(
            "font_scale", (0.85, 1.0, 1.15, 1.3)
        )
        add_row("Text size", self.font_combo)
        self.thumbs_cb = QCheckBox("Show thumbnails")
        self.thumbs_cb.setChecked(bool(self.settings.get("thumbs")))
        self.thumbs_cb.toggled.connect(self._on_thumbs_toggled)
        layout.addWidget(self.thumbs_cb)
        self.compact_cb = QCheckBox("Compact layout")
        self.compact_cb.setChecked(bool(self.settings.get("compact")))
        self.compact_cb.toggled.connect(lambda v: self.settings.set("compact", bool(v)))
        layout.addWidget(self.compact_cb)
        self.reduce_cb = QCheckBox("Reduce animations")
        self.reduce_cb.setChecked(bool(self.settings.get("reduce_animations")))
        self.reduce_cb.toggled.connect(self._on_reduce_animations_toggled)
        layout.addWidget(self.reduce_cb)
        self.audio_default_cb = QCheckBox("Audio-only by default")
        self.audio_default_cb.setChecked(bool(self.settings.get("audio_only")))
        self.audio_default_cb.toggled.connect(
            lambda v: self.settings.set("audio_only", bool(v))
        )
        layout.addWidget(self.audio_default_cb)

        # Tools
        header("Tools & dependencies")
        for key, label_text in (
            ("mpv", "mpv"),
            ("ffmpeg", "ffmpeg"),
            ("yt-dlp", "yt-dlp"),
            ("vlc", "VLC (optional)"),
            ("pillow", "Pillow"),
            ("osk", "On-screen keyboard (optional)"),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label_text))
            status = QLabel("checking…")
            status.setObjectName("Meta")
            row.addWidget(status, 1)
            self._tool_labels[key] = status
            layout.addLayout(row)
        refresh_tools = QPushButton("Refresh status")
        refresh_tools.clicked.connect(self._refresh_tools)
        layout.addWidget(refresh_tools)
        self.auto_update_cb = QCheckBox("Auto-update yt-dlp on launch")
        self.auto_update_cb.setChecked(bool(self.settings.get("auto_update")))
        self.auto_update_cb.toggled.connect(
            lambda v: self.settings.set("auto_update", bool(v))
        )
        layout.addWidget(self.auto_update_cb)

        # Storage
        header("Storage")
        self.cache_label = QLabel("")
        self.cache_label.setObjectName("Meta")
        layout.addWidget(self.cache_label)
        clear_cache = QPushButton("Clear thumbnails")
        clear_cache.clicked.connect(self._clear_thumb_cache)
        layout.addWidget(clear_cache)
        reset_warnings = QPushButton("Reset warnings")
        reset_warnings.clicked.connect(self._reset_warnings)
        layout.addWidget(reset_warnings)

        # About
        header("About")
        profile = system_profile.describe()
        about = QLabel(
            "Super Duper Lite YT 1.1.0 — 2026-11-13\n"
            "Tiny, fast, touch-friendly YouTube for Pi and small screens.\n"
            "RAM %d MB · %d cores · recommended UI: %s · Python %s\n"
            "Not affiliated with YouTube or Google. Only download content "
            "you have the right to."
            % (profile["ram_mb"], profile["cores"],
               profile["recommended_ui"], profile["python"])
        )
        about.setObjectName("About")
        about.setWordWrap(True)
        layout.addWidget(about)

        layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        self._refresh_cache_label()
        return page

    def _make_resolution_combo(self, key: str) -> QComboBox:
        combo = QComboBox()
        for height in resolutions.RESOLUTIONS:
            combo.addItem(resolutions.label(height), height)
        current = int(self.settings.get(key, 720))
        for index in range(combo.count()):
            if combo.itemData(index) == current:
                combo.setCurrentIndex(index)
                break
        combo.currentIndexChanged.connect(
            lambda _index, k=key, c=combo: self._on_resolution_changed(k, c)
        )
        return combo

    def _make_options_combo(self, key: str, values: tuple) -> QComboBox:
        combo = QComboBox()
        for value in values:
            combo.addItem(str(value), value)
        current = self.settings.get(key)
        for index in range(combo.count()):
            if combo.itemData(index) == current:
                combo.setCurrentIndex(index)
                break
        combo.currentIndexChanged.connect(
            lambda _index, k=key, c=combo: self._set_option(k, c.currentData())
        )
        return combo

    def _set_option(self, key: str, value) -> None:
        if value is None:
            return
        current = self.settings.get(key)
        try:
            if isinstance(current, bool):
                coerced = bool(value)
            elif isinstance(current, int):
                coerced = int(value)
            elif isinstance(current, float):
                coerced = float(value)
            else:
                coerced = value
        except (TypeError, ValueError):
            return
        self.settings.set(key, coerced)
        if key == "appearance":
            self._apply_theme()
        elif key == "dl_res":
            self._refresh_container_note()

    def _on_resolution_changed(self, key: str, combo: QComboBox) -> None:
        height = combo.currentData()
        if height is None:
            return
        threshold = 720 if key == "play_res" else 1080
        if height > threshold and system_profile.is_weak_system():
            warn_key = "%s_high_%d" % (key, height)
            if not self.settings.was_warned(warn_key):
                self.settings.mark_warned(warn_key)
                QMessageBox.warning(
                    self,
                    "Warning",
                    resolutions.weak_system_warning(height)
                    + "\n\nThis warning will not be shown again.",
                )
        self.settings.set(key, int(height))
        if key == "dl_res":
            self._refresh_container_note()

    def _refresh_container_note(self) -> None:
        height = int(self.settings.get("dl_res", 720))
        self.container_note.setText(resolutions.container_note(height))

    def _on_interface_changed(self, _index: int) -> None:
        value = self.interface_combo.currentData()
        if value is None:
            return
        if value != "auto":
            if not system_profile.ui_supported(value):
                self.toasts.show(
                    "%s is not available on this system." % UI_LABELS.get(value, value),
                    "err",
                )
                return
            if system_profile.ui_too_heavy(value):
                ok = QMessageBox.question(
                    self,
                    "Warning — heavy UI",
                    "The %s interface may be slow or unstable on this device "
                    "(%d MB RAM, %d cores).\n\nContinue anyway?"
                    % (UI_LABELS.get(value, value),
                       system_profile.total_ram_mb(), system_profile.cpu_cores()),
                )
                if ok != QMessageBox.Yes:
                    return
        self.settings.set("ui", value)
        self.toasts.show("Saved. Restart to apply.", "info")

    def _on_thumbs_toggled(self, checked: bool) -> None:
        self.settings.set("thumbs", bool(checked))
        self.thumbs.enabled = bool(checked) and core.thumbs.HAVE_PIL

    def _on_reduce_animations_toggled(self, checked: bool) -> None:
        self.reduce_animations = bool(checked)
        self.settings.set("reduce_animations", self.reduce_animations)
        self.pages.set_reduce_animations(self.reduce_animations)

    def _pick_out_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose download folder", str(self.settings.get("out_dir", ""))
        )
        if path and os.path.isdir(path):
            self.settings.set("out_dir", path)
            self.out_dir_label.setText(path)
            self._refresh_library()
            self.toasts.show("Download folder: " + path, "ok")

    def _refresh_tools(self) -> None:
        if self._tools_worker is not None and self._tools_worker.isRunning():
            return
        self._tools_worker = workers.ToolsWorker(self)
        self._tools_worker.finished.connect(self._apply_tool_status)
        self._tools_worker.start()

    @Slot(dict)
    def _apply_tool_status(self, status: dict) -> None:
        for key, label in self._tool_labels.items():
            entry = status.get(key, {})
            if entry.get("ok"):
                label.setText("✓ " + (entry.get("version") or "installed"))
            else:
                label.setText("✗ not installed")

    def _refresh_cache_label(self) -> None:
        count, size = self.thumbs.cache_stats()
        self.cache_label.setText(
            "Thumbnails: %d files · %s" % (count, _human(size))
        )

    def _clear_thumb_cache(self) -> None:
        self.thumbs.clear()
        self._refresh_cache_label()
        self.toasts.show("Thumbnail cache cleared", "ok")

    def _reset_warnings(self) -> None:
        self.settings.set("warned", [])
        self.toasts.show("Warnings reset", "ok")

    # -- Account -------------------------------------------------------
    def _build_account_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.acc_status = QLabel("")
        self.acc_status.setObjectName("Header")
        layout.addWidget(self.acc_status)

        note = QLabel(
            "Optional: import cookies.txt from a browser logged in to YouTube.\n"
            "Used for age-restricted or private videos. Use a secondary account."
        )
        note.setObjectName("Meta")
        note.setWordWrap(True)
        layout.addWidget(note)

        row = QHBoxLayout()
        import_btn = QPushButton("Import cookies")
        import_btn.setObjectName("Primary")
        import_btn.clicked.connect(self._import_cookies)
        row.addWidget(import_btn)
        logout = QPushButton("Log out")
        logout.setObjectName("Danger")
        logout.clicked.connect(self._remove_cookies)
        row.addWidget(logout)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

        self._update_account_label()
        return page

    def _update_account_label(self) -> None:
        self.acc_status.setText(
            "✓ Logged in (cookies)"
            if os.path.exists(core.paths.COOKIES)
            else "Not logged in"
        )

    def _import_cookies(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select cookies.txt", filter="Text files (*.txt);;All files (*)"
        )
        if not path:
            return
        try:
            shutil.copy(path, core.paths.COOKIES)
            os.chmod(core.paths.COOKIES, 0o600)
        except OSError as exc:
            self.toasts.show("Import failed: %s" % exc, "err")
            return
        self._update_account_label()
        self.toasts.show("Cookies imported", "ok")

    def _remove_cookies(self) -> None:
        try:
            if os.path.exists(core.paths.COOKIES):
                os.remove(core.paths.COOKIES)
        except OSError as exc:
            self.toasts.show("Remove failed: %s" % exc, "err")
            return
        self._update_account_label()
        self.toasts.show("Cookies removed", "info")

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        self.thumb_bridge.ready.connect(self._on_thumb_ready)
        self.dl_bridge.job_updated.connect(self._on_job_updated)
        self.dl_bridge.queue_changed.connect(self._on_queue_changed)
        self.dl_bridge.toast.connect(self._on_toast)
        self.player_bridge.status.connect(self._set_status)
        self.player_bridge.error.connect(lambda msg: self._on_toast(msg, "err"))

    @Slot(str, object)
    def _on_thumb_ready(self, video_id: str, pixmap) -> None:
        self.find_list.set_thumbnail(video_id, pixmap)
        self.hist_list.set_thumbnail(video_id, pixmap)
        self.lib_list.set_thumbnail(video_id, pixmap)

    @Slot(object)
    def _on_job_updated(self, job) -> None:
        row = self.job_rows.get(job.uid)
        if row is not None:
            row.refresh()
        self._refresh_queue_summary()

    @Slot()
    def _on_queue_changed(self) -> None:
        self._sync_queue_rows()

    @Slot(str, str)
    def _on_toast(self, message: str, kind: str) -> None:
        self.toasts.show(message, kind)

    @Slot(str)
    def _set_status(self, message: str) -> None:
        self.status_label.setText(message[:120])

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _navigate_to(self, name: str) -> None:
        index = PAGES.index(name)
        self.pages.slide_to(index)
        if name in self.sidebar_buttons:
            self.sidebar_buttons[name].setChecked(True)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _on_search_enter(self) -> None:
        query = self.search_field.text().strip()
        if not query:
            return
        if query not in self.recent:
            self.recent.insert(0, query)
            self.recent = self.recent[:20]
            core.utils.jsave(core.paths.RECENT, self.recent)
        self._navigate_to("Find")
        self._set_status("Searching: " + query[:40])
        self.find_list.set_items([])

        if self._search_worker is not None and self._search_worker.isRunning():
            self._search_worker.finished.disconnect()
            self._search_worker.failed.disconnect()

        self._search_worker = workers.SearchWorker(query)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.failed.connect(self._on_search_failed)
        self._search_worker.start()

    @Slot(list)
    def _on_search_finished(self, items: list) -> None:
        self.find_list.set_items(items)
        self._set_status("%d results" % len(items) if items else "No results")
        if self.settings.get("thumbs") and self.thumbs.enabled:
            for item in items:
                video_id = item.get("id", "")
                if video_id:
                    self.thumb_bridge.request(video_id)

    @Slot(str)
    def _on_search_failed(self, message: str) -> None:
        self._set_status("Search failed")
        self.toasts.show(message, "warn")

    def _current_list(self) -> widgets.ResultListView | None:
        current = self.pages.currentWidget()
        if current is self.find_page:
            return self.find_list
        if current is self.hist_page:
            return self.hist_list
        if current is self.lib_page:
            return self.lib_list
        return None

    def _do_play(self, result_list: widgets.ResultListView | None,
                 audio_only: bool) -> None:
        item = result_list.selected_item() if result_list else None
        if not item:
            self.toasts.show("Select an item first", "warn")
            return
        if "path" in item:
            self.player.play_local(item["path"], item.get("kind", "") == "Audio",
                                   "Playing: " + item.get("title", "")[:40])
            return
        self.history.add(item)
        self._refresh_history()
        self.player.play_url(item["id"], audio_only, item.get("title", ""))

    def _do_dl(self, result_list: widgets.ResultListView | None, kind: str) -> None:
        items = result_list.selected_items() if result_list else []
        if not items:
            self.toasts.show("Select an item first", "warn")
            return

        res = int(self.settings.get("dl_res", 720))
        if (
            kind == "video"
            and resolutions.is_above_1080(res)
            and system_profile.is_weak_system()
        ):
            warn_key = "dl_high_%d" % res
            if not self.settings.was_warned(warn_key):
                self.settings.mark_warned(warn_key)
                ok = QMessageBox.question(
                    self,
                    "Warning",
                    "Downloading %s may use significant disk space, RAM and "
                    "bandwidth.\n\nThis warning will not be shown again.\n\n"
                    "Continue?" % resolutions.label(res),
                )
                if ok != QMessageBox.Yes:
                    return

        added = 0
        for item in items:
            if self.downloads.add(item, kind):
                added += 1
        if added:
            self.toasts.show(
                "Queued %d download%s" % (added, "s" if added > 1 else ""),
                "ok",
            )
        self._sync_queue_rows()

    def _refresh_history(self) -> None:
        items = []
        for entry in list(self.history)[:80]:
            item = dict(entry)
            item["meta"] = "  ·  ".join(
                part for part in (entry.get("channel", ""), entry.get("when", "")) if part
            )
            items.append(item)
        self.hist_list.set_items(items)
        if self.settings.get("thumbs") and self.thumbs.enabled:
            for item in items:
                video_id = item.get("id", "")
                if video_id:
                    self.thumb_bridge.request(video_id)

    def _clear_history(self) -> None:
        answer = QMessageBox.question(
            self, "Clear history", "Delete all play history?"
        )
        if answer == QMessageBox.Yes:
            self.history.clear()
            self._refresh_history()

    def _refresh_library(self) -> None:
        out_dir = str(self.settings.get("out_dir", core.paths.DEFAULT_OUT))
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError:
            pass

        audio_ext = {".m4a", ".mp3", ".opus", ".ogg", ".wav", ".aac"}
        video_ext = {".mp4", ".mkv", ".webm"}
        items: list[dict] = []
        try:
            for name in os.listdir(out_dir):
                full = os.path.join(out_dir, name)
                if not os.path.isfile(full):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in audio_ext | video_ext:
                    continue
                import re

                match = re.search(r"\[([\w-]{11})\]", name)
                kind = "Audio" if ext in audio_ext else "Video"
                size = os.path.getsize(full)
                items.append({
                    "path": full,
                    "kind": kind,
                    "mtime": os.path.getmtime(full),
                    "id": match.group(1) if match else "",
                    "title": re.sub(r"\s*\[[\w-]{11}\]", "", os.path.splitext(name)[0]),
                    "meta": "%s  ·  %s" % (kind, _human(size)),
                })
        except OSError:
            pass

        items.sort(key=lambda row: row["mtime"], reverse=True)
        self.lib_list.set_items(items)

        try:
            free = _human(shutil.disk_usage(out_dir).free)
        except Exception:
            free = "?"
        self.lib_summary.setText(
            "%d files · %s free · %s" % (len(items), free, out_dir)
        )

        if self.settings.get("thumbs") and self.thumbs.enabled:
            for item in items:
                video_id = item.get("id", "")
                if video_id:
                    self.thumb_bridge.request(video_id)

    def _play_library_item(self) -> None:
        item = self.lib_list.selected_item()
        if not item or "path" not in item:
            self.toasts.show("Select a file first", "warn")
            return
        self.player.play_local(
            item["path"],
            item.get("kind") == "Audio",
            "Playing: " + item.get("title", "")[:40],
        )

    def _sync_queue_rows(self) -> None:
        live = {job.uid for job in self.downloads.jobs}
        for job in self.downloads.jobs:
            if job.uid not in self.job_rows:
                row = widgets.JobRow(
                    self.palette,
                    job,
                    {
                        "cancel": self.downloads.cancel,
                        "retry": self.downloads.retry,
                        "remove": self._remove_job,
                    },
                    self.queue_container,
                )
                self.queue_layout.insertWidget(self.queue_layout.count() - 1, row)
                self.job_rows[job.uid] = row
        for uid in list(self.job_rows.keys()):
            if uid not in live:
                row = self.job_rows.pop(uid)
                row.setParent(None)
                row.deleteLater()
        self._refresh_queue_summary()

    def _remove_job(self, job: core.downloads.DownloadJob) -> None:
        self.downloads.remove(job)
        self._sync_queue_rows()

    def _refresh_queue_summary(self) -> None:
        counts: dict[str, int] = {}
        for job in self.downloads.jobs:
            counts[job.state] = counts.get(job.state, 0) + 1
        text = "  ·  ".join("%d %s" % (n, s) for s, n in counts.items())
        self.queue_summary.setText(text or "Queue is empty")

    def _on_volume(self, value: int) -> None:
        self.settings.set("volume", int(value))

    def _cycle_sleep(self) -> None:
        self.sleep_i = (self.sleep_i + 1) % len(SLEEP_STEPS)
        minutes = SLEEP_STEPS[self.sleep_i]
        self.sleep_end = time.time() + minutes * 60 if minutes else 0
        self.sleep_btn.setText("Zzz %d:00" % minutes if minutes else "Zzz off")
        self._set_status(
            "Sleep timer: %d min" % minutes if minutes else "Sleep timer off"
        )

    def _tick(self) -> None:
        if not self.sleep_end:
            return
        left = int(self.sleep_end - time.time())
        if left <= 0:
            self.player.stop()
            self.sleep_end = 0
            self.sleep_i = 0
            self.sleep_btn.setText("Zzz off")
            self._set_status("Sleep timer: playback stopped")
        else:
            self.sleep_btn.setText("Zzz %d:%02d" % divmod(left, 60))

    # ------------------------------------------------------------------
    # Startup / quit / restart
    # ------------------------------------------------------------------
    def _startup(self) -> None:
        self._refresh_tools()
        if self.settings.get("auto_update") and os.path.exists(core.paths.YT):
            import subprocess

            def worker() -> None:
                try:
                    subprocess.run(
                        [core.paths.YT, "-U"], capture_output=True, timeout=180
                    )
                except Exception:
                    pass

            import threading

            threading.Thread(target=worker, daemon=True).start()

    def _restart_app(self) -> None:
        self.player.stop()
        self.downloads.stop_all()
        self.close()
        args = [sys.executable]
        if sys.argv and sys.argv[0].endswith("__main__.py"):
            args.extend(["-m", "sdlyt"])
        else:
            args.extend(sys.argv)
        try:
            os.execv(sys.executable, args)
        except OSError:
            pass

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.player.stop()
            self.downloads.stop_all()
        except Exception:
            pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run(settings: core.settings.Settings) -> None:
    """Launch the PySide6 UI (blocking until the window is closed)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("Super Duper Lite YT")
    app.setOrganizationName("sdlyt")
    window = MainWindow(settings)
    window.show()
    app.exec()