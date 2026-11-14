"""Plain Tkinter UI for very low RAM devices.

Design goals: no images, no animations, minimal widget count, ttk
widgets only. All backend work is delegated to :mod:`sdlyt.core`.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from .. import core
from ..core import resolutions, system_profile

SLEEP_STEPS = (0, 15, 30, 45, 60, 90)

UI_LABELS = {
    "auto": "Auto",
    "tk": "Tkinter",
    "ctk": "CustomTkinter",
    "pyside6": "PySide6",
}
LABEL_TO_UI = {v: k for k, v in UI_LABELS.items()}


class App(tk.Tk):
    """The plain Tkinter application window."""

    def __init__(self, settings: core.settings.Settings):
        super().__init__()
        self.settings = settings
        self.title("Super Duper Lite YT (Tk)")

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.win_width = screen_w
        self.win_height = screen_h - max(20, min(60, int(screen_h * 0.06)))
        self.geometry("%dx%d+0+0" % (self.win_width, self.win_height))
        self.minsize(360, 240)
        self.bind("<Escape>", lambda _e: self.quit_app())

        self._init_style()

        self.history = core.history.History()
        self.thumbs = core.thumbs.ThumbService(enabled=False)
        self.player = core.player.Player(
            settings,
            on_status=self._on_player_status,
            on_error=self._on_player_error,
        )
        self.downloads = core.downloads.DownloadManager(
            settings,
            on_update=self._on_job_update,
            on_toast=self._on_toast,
            on_change=self._on_queue_changed,
        )

        self.recent = core.utils.jload(core.paths.RECENT, []) or []
        self.sleep_end = 0
        self.sleep_i = 0

        self._find_items: list[dict] = []
        self._hist_items: list[dict] = []
        self._lib_items: list[dict] = []

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.after(400, self._startup)
        self.after(1000, self._tick)

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------
    def _init_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Toolbar.TFrame", background="#171a21")
        style.configure("Toolbar.TLabel", background="#171a21", foreground="#e5e7eb")
        style.configure("Toolbar.TButton", padding=(8, 4))
        style.configure("TNotebook.Tab", padding=(10, 6))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self, style="Toolbar.TFrame", padding=(8, 4))
        top.pack(fill="x", side="top")
        ttk.Label(top, text="▶ Super Duper Lite YT (Tk)",
                  style="Toolbar.TLabel", font=("TkDefaultFont", 12, "bold")).pack(side="left")
        self.top_status = ttk.Label(top, text="Ready", style="Toolbar.TLabel")
        self.top_status.pack(side="left", padx=12)
        ttk.Button(top, text="✕", width=3, command=self.quit_app).pack(side="right")

        bottom = ttk.Frame(self, padding=(8, 4))
        bottom.pack(fill="x", side="bottom")
        ttk.Button(bottom, text="Stop", command=self.player.stop).pack(side="right", padx=4)
        self.zbtn = ttk.Button(bottom, text="Zzz off", command=self.cycle_sleep)
        self.zbtn.pack(side="right", padx=4)

        ttk.Label(bottom, text="Volume").pack(side="right", padx=(8, 2))
        self.vol_var = tk.IntVar(value=int(self.settings.get("volume", 100)))
        ttk.Scale(bottom, from_=0, to=100, orient="horizontal", length=120,
                  variable=self.vol_var, command=self._on_volume).pack(side="right", padx=4)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.notebook = nb

        self.tab_find = ttk.Frame(nb)
        self.tab_hist = ttk.Frame(nb)
        self.tab_lib = ttk.Frame(nb)
        self.tab_queue = ttk.Frame(nb)
        self.tab_set = ttk.Frame(nb)
        self.tab_acct = ttk.Frame(nb)
        nb.add(self.tab_find, text="Find")
        nb.add(self.tab_hist, text="Hist")
        nb.add(self.tab_lib, text="Lib")
        nb.add(self.tab_queue, text="Queue")
        nb.add(self.tab_set, text="Set")
        nb.add(self.tab_acct, text="Acct")

        self._build_find(self.tab_find)
        self._build_hist(self.tab_hist)
        self._build_lib(self.tab_lib)
        self._build_queue(self.tab_queue)
        self._build_settings(self.tab_set)
        self._build_account(self.tab_acct)

    # -- Find ----------------------------------------------------------
    def _build_find(self, parent) -> None:
        bar = ttk.Frame(parent, padding=(4, 4))
        bar.pack(fill="x")
        self.q = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.q)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.search())
        ttk.Button(bar, text="Go", command=self.search).pack(side="left", padx=4)

        self.audio_var = tk.BooleanVar(value=bool(self.settings.get("audio_only")))
        ttk.Checkbutton(bar, text="Audio only", variable=self.audio_var,
                        command=self._save_audio_only).pack(side="left", padx=4)

        actions = ttk.Frame(parent, padding=(4, 2))
        actions.pack(fill="x")
        ttk.Button(actions, text="Play", command=lambda: self._do_play("find", False)).pack(side="left", padx=2)
        ttk.Button(actions, text="Listen", command=lambda: self._do_play("find", True)).pack(side="left", padx=2)
        ttk.Button(actions, text="Download video", command=lambda: self._do_dl("find", "video")).pack(side="left", padx=2)
        ttk.Button(actions, text="Download audio", command=lambda: self._do_dl("find", "audio")).pack(side="left", padx=2)

        self.find_tree = self._make_tree(parent, ("title", "meta"))
        self.find_tree.bind("<Double-1>", lambda _e: self._do_play("find", self.audio_var.get()))

    def _make_tree(self, parent, columns: tuple[str, ...]) -> ttk.Treeview:
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill="both", expand=True, padx=4, pady=4)
        tree = ttk.Treeview(wrapper, columns=columns, show="tree headings", selectmode="browse")
        tree.heading("#0", text="")
        tree.column("#0", width=0, stretch=False)
        for col in columns:
            tree.heading(col, text=col.capitalize())
            tree.column(col, anchor="w")
        scrollbar = ttk.Scrollbar(wrapper, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def _fill_tree(self, tree: ttk.Treeview, items: list[dict]) -> None:
        tree.delete(*tree.get_children())
        for index, item in enumerate(items):
            tree.insert("", "end", iid=str(index), text="",
                        values=(item.get("title", "?"),
                                item.get("meta", "") or item.get("channel", "")))

    def _tree_selection(self, tree: ttk.Treeview, items: list[dict]) -> dict | None:
        selection = tree.selection()
        if not selection:
            return None
        try:
            index = int(selection[0])
        except (TypeError, ValueError):
            return None
        if 0 <= index < len(items):
            return items[index]
        return None

    def _save_audio_only(self) -> None:
        self.settings.set("audio_only", bool(self.audio_var.get()))

    # -- History -------------------------------------------------------
    def _build_hist(self, parent) -> None:
        self.hist_tree = self._make_tree(parent, ("title", "meta"))
        ttk.Button(parent, text="Clear history", command=self._clear_history).pack(pady=4)
        self._refresh_history()

    def _refresh_history(self) -> None:
        self._hist_items = []
        for entry in list(self.history)[:80]:
            item = dict(entry)
            item["meta"] = "  ·  ".join(
                part for part in (entry.get("channel", ""), entry.get("when", "")) if part
            )
            self._hist_items.append(item)
        self._fill_tree(self.hist_tree, self._hist_items)

    def _clear_history(self) -> None:
        if messagebox.askyesno("Clear history", "Delete all play history?"):
            self.history.clear()
            self._refresh_history()

    # -- Library -------------------------------------------------------
    def _build_lib(self, parent) -> None:
        head = ttk.Frame(parent)
        head.pack(fill="x", padx=4, pady=4)
        ttk.Button(head, text="Refresh", command=self._refresh_library).pack(side="right")
        ttk.Button(head, text="Play selected",
                   command=self._play_library_item).pack(side="left")
        self.lib_summary = tk.StringVar(value="")
        ttk.Label(head, textvariable=self.lib_summary).pack(side="left", padx=8)

        self.lib_tree = self._make_tree(parent, ("title", "meta"))
        self.lib_tree.bind("<Double-1>", lambda _e: self._play_library_item())
        self._refresh_library()

    def _refresh_library(self) -> None:
        out = str(self.settings.get("out_dir", core.paths.DEFAULT_OUT))
        try:
            os.makedirs(out, exist_ok=True)
        except OSError:
            pass
        audio_ext = {".m4a", ".mp3", ".opus", ".ogg", ".wav", ".aac"}
        video_ext = {".mp4", ".mkv", ".webm"}
        items: list[dict] = []
        try:
            for name in os.listdir(out):
                full = os.path.join(out, name)
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
                    "title": re.sub(r"\s*\[[\w-]{11}\]", "", os.path.splitext(name)[0]),
                    "meta": "%s  ·  %s" % (kind, core.utils.human(size)),
                })
        except OSError:
            pass
        items.sort(key=lambda row: row["mtime"], reverse=True)
        self._lib_items = items
        self._fill_tree(self.lib_tree, items)
        try:
            free = core.utils.human(__import__("shutil").disk_usage(out).free)
        except Exception:
            free = "?"
        self.lib_summary.set("%d files · %s free" % (len(items), free))

    def _play_library_item(self) -> None:
        item = self._tree_selection(self.lib_tree, self._lib_items)
        if not item:
            self._toast("Select a file first", "warn")
            return
        self.player.play_local(item["path"], item["kind"] == "Audio",
                               "Playing: " + item["title"][:40])

    # -- Queue ---------------------------------------------------------
    def _build_queue(self, parent) -> None:
        bar = ttk.Frame(parent, padding=(4, 4))
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel", command=self._cancel_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="Retry", command=self._retry_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="Remove", command=self._remove_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="Clear done",
                   command=self.downloads.clear_done).pack(side="left", padx=2)
        ttk.Button(bar, text="Retry all",
                   command=self.downloads.retry_all).pack(side="left", padx=2)
        self.q_summary = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.q_summary).pack(side="right")

        wrapper = ttk.Frame(parent)
        wrapper.pack(fill="both", expand=True, padx=4, pady=4)
        columns = ("state", "pct")
        self.q_tree = ttk.Treeview(wrapper, columns=columns, show="tree headings",
                                   selectmode="browse")
        self.q_tree.heading("#0", text="Title")
        self.q_tree.column("#0", anchor="w", width=320)
        self.q_tree.heading("state", text="State")
        self.q_tree.heading("pct", text="%")
        scrollbar = ttk.Scrollbar(wrapper, orient="vertical", command=self.q_tree.yview)
        self.q_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.q_tree.pack(side="left", fill="both", expand=True)
        self._refresh_queue_summary()

    def _refresh_queue_summary(self) -> None:
        self.q_tree.delete(*self.q_tree.get_children())
        for job in self.downloads.jobs:
            prefix = "[V] " if job.kind == "video" else "[A] "
            self.q_tree.insert(
                "", "end", iid=str(job.uid),
                text=prefix + job.title,
                values=(job.state, "%.0f" % (job.pct or 0.0)),
            )
        counts: dict[str, int] = {}
        for job in self.downloads.jobs:
            counts[job.state] = counts.get(job.state, 0) + 1
        text = "  ·  ".join("%d %s" % (count, state) for state, count in counts.items())
        self.q_summary.set(text or "Queue is empty")

    def _selected_job(self) -> core.downloads.DownloadJob | None:
        selection = self.q_tree.selection()
        if not selection:
            return None
        try:
            uid = int(selection[0])
        except ValueError:
            return None
        return next((job for job in self.downloads.jobs if job.uid == uid), None)

    def _cancel_selected(self) -> None:
        job = self._selected_job()
        if job:
            self.downloads.cancel(job)

    def _retry_selected(self) -> None:
        job = self._selected_job()
        if job:
            self.downloads.retry(job)

    def _remove_selected(self) -> None:
        job = self._selected_job()
        if job:
            self.downloads.remove(job)

    def _on_queue_changed(self) -> None:
        self.after(0, self._refresh_queue_summary)

    def _on_job_update(self, job: core.downloads.DownloadJob) -> None:
        self.after(0, lambda: self._apply_job_update(job))

    def _apply_job_update(self, job: core.downloads.DownloadJob) -> None:
        try:
            iid = str(job.uid)
            if self.q_tree.exists(iid):
                self.q_tree.item(iid, values=(job.state, "%.0f" % (job.pct or 0.0)))
        except tk.TclError:
            pass

    # -- Settings ------------------------------------------------------
    def _build_settings(self, parent) -> None:
        canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
        inner = ttk.Frame(canvas)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))

        def head(text: str) -> None:
            ttk.Label(inner, text=text, font=("TkDefaultFont", 11, "bold")).pack(
                anchor="w", pady=(10, 2), padx=6
            )

        head("Interface")
        self._build_ui_selector(inner)

        head("Playback")
        self._build_resolution_option(inner, "Play quality", "play_res")
        self._combobox(inner, "Speed", "speed", (0.75, 1.0, 1.25, 1.5))
        self._check(inner, "Fullscreen playback", "fs")
        self._check(inner, "Hardware decode", "hwdec")

        head("Downloads")
        self._build_resolution_option(inner, "Download quality", "dl_res")
        ttk.Label(inner, text=resolutions.container_note(
            int(self.settings.get("dl_res", 720))
        )).pack(anchor="w", padx=6)
        self._combobox(inner, "Audio format", "audio_fmt", ("m4a", "mp3"))
        self._combobox(inner, "Parallel downloads", "parallel", (1, 2, 3))
        self._out_dir_row(inner)
        self._check(inner, "Embed thumbnail + metadata", "embed")

        head("Subtitles")
        self._check(inner, "Show / download subtitles", "subs")
        self._combobox(inner, "Language", "sub_lang",
                       ("en", "ar", "fr", "es", "de", "tr", "ur", "hi", "pt", "ru", "id"))

        head("Appearance")
        self._combobox(inner, "Mode", "appearance", ("dark", "light", "system"))
        self._combobox(inner, "Text size", "font_scale", (0.85, 1.0, 1.15, 1.3))
        self._check(inner, "Show thumbnails", "thumbs")
        self._check(inner, "Compact layout", "compact")
        self._check(inner, "Audio-only by default", "audio_only")

        head("Tools")
        self.tool_labels: dict[str, tk.StringVar] = {}
        for key, label in (("mpv", "mpv"), ("ffmpeg", "ffmpeg"), ("yt-dlp", "yt-dlp"),
                           ("vlc", "VLC"), ("pillow", "Pillow"), ("osk", "On-screen keyboard")):
            row = ttk.Frame(inner)
            row.pack(fill="x", padx=6, pady=1)
            ttk.Label(row, text=label, width=18).pack(side="left")
            status = tk.StringVar(value="checking…")
            ttk.Label(row, textvariable=status).pack(side="left")
            self.tool_labels[key] = status
        ttk.Button(inner, text="Refresh status",
                   command=self._refresh_tool_status).pack(anchor="w", padx=6, pady=6)
        self._check(inner, "Auto-update yt-dlp on launch", "auto_update")

        head("Storage")
        self.cache_var = tk.StringVar(value="")
        ttk.Label(inner, textvariable=self.cache_var).pack(anchor="w", padx=6)
        ttk.Button(inner, text="Clear thumbnails",
                   command=self._clear_thumb_cache).pack(anchor="w", padx=6, pady=4)
        ttk.Button(inner, text="Reset warnings",
                   command=self._reset_warnings).pack(anchor="w", padx=6, pady=(0, 10))

        head("About")
        profile = system_profile.describe()
        ttk.Label(inner, text="Super Duper Lite YT 1.1.0 — 2026-11-13").pack(
            anchor="w", padx=6
        )
        ttk.Label(inner, text="RAM %d MB · %d cores · recommended: %s · Python %s" % (
            profile["ram_mb"], profile["cores"],
            profile["recommended_ui"], profile["python"],
        )).pack(anchor="w", padx=6, pady=(0, 6))
        ttk.Label(inner, text="Not affiliated with YouTube or Google.").pack(
            anchor="w", padx=6, pady=(0, 8)
        )
        self._refresh_cache_label()

    def _build_ui_selector(self, parent) -> None:
        resolved = system_profile.recommended_ui()
        ttk.Label(parent, text="Auto will use: %s" % resolved).pack(anchor="w", padx=6)
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=6, pady=2)
        current = str(self.settings.get("ui", "auto"))
        for value in ("auto", "tk", "ctk", "pyside6"):
            ttk.Radiobutton(
                frame, text=UI_LABELS[value], value=value,
                variable=tk.StringVar(value=current),
                command=lambda v=value: self._apply_ui_choice(v),
            ).pack(side="left", padx=4)

    def _apply_ui_choice(self, value: str) -> None:
        if value != "auto":
            if not system_profile.ui_supported(value):
                self._toast("%s is not available on this system." % UI_LABELS.get(value, value),
                            "err")
                return
            if system_profile.ui_too_heavy(value):
                if not messagebox.askyesno(
                    "Warning — heavy UI",
                    "The %s interface may be slow or unstable on this device.\n\nContinue anyway?"
                    % UI_LABELS.get(value, value),
                ):
                    return
        self.settings.set("ui", value)
        if messagebox.askyesno("Restart required", "Restart now to apply?"):
            self._restart_app()

    def _build_resolution_option(self, parent, label: str, key: str) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text=label, width=18).pack(side="left")
        current = int(self.settings.get(key, 720))
        if current not in resolutions.RESOLUTIONS:
            current = resolutions.RESOLUTIONS[0]
        values = [resolutions.label(h) for h in resolutions.RESOLUTIONS]
        var = tk.StringVar(value=resolutions.label(current))
        combo = ttk.Combobox(row, textvariable=var, values=values, state="readonly")
        combo.pack(side="left", fill="x", expand=True)

        def on_select(_event, k=key):
            text = var.get()
            for height in resolutions.RESOLUTIONS:
                if resolutions.label(height) == text:
                    self._set_resolution(k, height)
                    break

        combo.bind("<<ComboboxSelected>>", on_select)

    def _set_resolution(self, key: str, height: int) -> None:
        threshold = 720 if key == "play_res" else 1080
        if height > threshold and system_profile.is_weak_system():
            warn_key = "%s_high_%d" % (key, height)
            if not self.settings.was_warned(warn_key):
                self.settings.mark_warned(warn_key)
                messagebox.showwarning(
                    "Warning",
                    resolutions.weak_system_warning(height) +
                    "\n\nThis warning will not be shown again.",
                )
        self.settings.set(key, height)

    def _combobox(self, parent, label: str, key: str, values: tuple) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text=label, width=18).pack(side="left")
        current = self.settings.get(key)
        var = tk.StringVar(value=str(current))
        combo = ttk.Combobox(row, textvariable=var, values=[str(v) for v in values],
                             state="readonly")
        combo.pack(side="left", fill="x", expand=True)

        def on_select(_event, k=key, v=var):
            self._set_opt(k, v.get())

        combo.bind("<<ComboboxSelected>>", on_select)

    def _set_opt(self, key: str, value: str) -> None:
        current = self.settings.get(key)
        try:
            if isinstance(current, bool):
                coerced = value.lower() in ("true", "1", "yes")
            elif isinstance(current, int):
                coerced = int(value)
            elif isinstance(current, float):
                coerced = float(value)
            else:
                coerced = value
        except (TypeError, ValueError):
            coerced = value
        self.settings.set(key, coerced)
        if key == "appearance" and coerced in ("light", "dark"):
            # The plain Tk UI does not re-theme; the setting still applies
            # when the CTk UI is next used.
            pass

    def _check(self, parent, label: str, key: str) -> None:
        var = tk.BooleanVar(value=bool(self.settings.get(key)))
        ttk.Checkbutton(
            parent, text=label, variable=var,
            command=lambda k=key, v=var: self._set_opt(k, "true" if v.get() else "false"),
        ).pack(anchor="w", padx=6)

    def _out_dir_row(self, parent) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="Folder", width=18).pack(side="left")
        self.out_var = tk.StringVar(value=str(self.settings.get("out_dir", "")))
        ttk.Entry(row, textvariable=self.out_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="…", width=3, command=self._pick_out_dir).pack(side="left", padx=2)
        ttk.Button(row, text="Apply", command=self._apply_out_dir).pack(side="left")

    def _pick_out_dir(self) -> None:
        path = filedialog.askdirectory(title="Choose download folder",
                                       initialdir=str(self.settings.get("out_dir", "")))
        if path:
            self.out_var.set(path)

    def _apply_out_dir(self) -> None:
        path = self.out_var.get().strip()
        if path and os.path.isdir(path):
            self.settings.set("out_dir", path)
            self._refresh_library()
            self._toast("Download folder: " + path, "ok")

    def _refresh_tool_status(self) -> None:
        threading.Thread(target=self._tool_status_worker, daemon=True).start()

    def _tool_status_worker(self) -> None:
        status = core.tools.check_tools()
        self.after(0, lambda: self._apply_tool_status(status))

    def _apply_tool_status(self, status: dict) -> None:
        for key, entry in status.items():
            label = self.tool_labels.get(key)
            if label is None:
                continue
            try:
                if entry.get("ok"):
                    label.set("✓ " + (entry.get("version") or "installed"))
                else:
                    label.set("✗ not installed")
            except Exception:
                pass

    def _refresh_cache_label(self) -> None:
        count, size = self.thumbs.cache_stats()
        try:
            self.cache_var.set("Thumbnails: %d files · %s" % (count, core.utils.human(size)))
        except Exception:
            pass

    def _clear_thumb_cache(self) -> None:
        self.thumbs.clear()
        self._refresh_cache_label()
        self._toast("Thumbnail cache cleared", "ok")

    def _reset_warnings(self) -> None:
        self.settings.set("warned", [])
        self._toast("Warnings reset", "ok")

    # -- Account -------------------------------------------------------
    def _build_account(self, parent) -> None:
        frame = ttk.Frame(parent, padding=8)
        frame.pack(fill="x")
        self.acc_var = tk.StringVar()
        ttk.Label(frame, textvariable=self.acc_var, font=("TkDefaultFont", 11, "bold")).pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(frame, text="Optional: import cookies.txt from a browser logged in to "
                              "YouTube.").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Import", command=self._import_cookies).pack(side="left")
        ttk.Button(row, text="Log out", command=self._remove_cookies).pack(side="left", padx=4)
        self._update_account_label()

    def _update_account_label(self) -> None:
        try:
            self.acc_var.set("✓ Logged in (cookies)" if os.path.exists(core.paths.COOKIES)
                             else "Not logged in")
        except Exception:
            pass

    def _import_cookies(self) -> None:
        path = filedialog.askopenfilename(title="Select cookies.txt")
        if not path:
            return
        try:
            import shutil as _shutil

            _shutil.copy(path, core.paths.COOKIES)
            os.chmod(core.paths.COOKIES, 0o600)
            self._update_account_label()
            self._toast("Cookies imported", "ok")
        except OSError as exc:
            self._toast("Import failed: %s" % exc, "err")

    def _remove_cookies(self) -> None:
        try:
            if os.path.exists(core.paths.COOKIES):
                os.remove(core.paths.COOKIES)
            self._update_account_label()
            self._toast("Cookies removed", "info")
        except OSError as exc:
            self._toast("Remove failed: %s" % exc, "err")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def search(self, query: str | None = None) -> None:
        text = (query or self.q.get()).strip()
        if not text:
            return
        if text not in self.recent:
            self.recent.insert(0, text)
            self.recent = self.recent[:20]
            core.utils.jsave(core.paths.RECENT, self.recent)
        self._set_status("Searching: " + text[:40])
        threading.Thread(target=self._search_worker, args=(text,), daemon=True).start()

    def _search_worker(self, query: str) -> None:
        try:
            items = core.ytdlp.search(query)
        except core.ytdlp.YtDlpError as exc:
            message = str(exc)
            self.after(0, lambda: self._toast(message, "warn"))
            self.after(0, lambda: self._set_status("Search failed"))
            return
        self.after(0, lambda: self._fill_results(items))

    def _fill_results(self, items: list[dict]) -> None:
        self._find_items = items
        self._fill_tree(self.find_tree, items)
        self._set_status("%d results" % len(items) if items else "No results")

    def _do_play(self, which: str, audio_only: bool) -> None:
        item = self._pick_item(which)
        if not item:
            self._toast("Select an item first", "warn")
            return
        self.history.add(item)
        self._refresh_history()
        self.player.play_url(item["id"], audio_only, item.get("title", ""))

    def _pick_item(self, which: str) -> dict | None:
        if which == "find":
            return self._tree_selection(self.find_tree, self._find_items)
        if which == "hist":
            return self._tree_selection(self.hist_tree, self._hist_items)
        return None

    def _do_dl(self, which: str, kind: str) -> None:
        item = self._pick_item(which)
        if not item:
            self._toast("Select an item first", "warn")
            return

        res = int(self.settings.get("dl_res", 720))
        if kind == "video" and resolutions.is_above_1080(res) and system_profile.is_weak_system():
            warn_key = "dl_high_%d" % res
            if not self.settings.was_warned(warn_key):
                self.settings.mark_warned(warn_key)
                if not messagebox.askyesno(
                    "Warning",
                    "Downloading %s may use significant disk space and RAM.\n\nContinue?"
                    % resolutions.label(res),
                ):
                    return

        if self.downloads.add(item, kind):
            self._toast("Queued 1 download", "ok")

    # ------------------------------------------------------------------
    # Player callbacks
    # ------------------------------------------------------------------
    def _on_player_status(self, message: str) -> None:
        self.after(0, lambda: self._set_status(message))

    def _on_player_error(self, message: str) -> None:
        self.after(0, lambda: self._toast(message, "err"))

    def _on_toast(self, message: str, kind: str) -> None:
        self.after(0, lambda: self._toast(message, kind))

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _toast(self, message: str, kind: str = "info") -> None:
        # The plain Tk UI has no toast window; use the status label so
        # the user still sees the message.
        self._set_status(("[%s] " % kind.upper() if kind != "info" else "") + message)

    def _set_status(self, message: str) -> None:
        try:
            self.top_status.configure(text=message[:120])
        except Exception:
            pass

    def _on_volume(self, _value) -> None:
        try:
            self.settings.set("volume", int(float(self.vol_var.get())))
        except Exception:
            pass

    def cycle_sleep(self) -> None:
        self.sleep_i = (self.sleep_i + 1) % len(SLEEP_STEPS)
        minutes = SLEEP_STEPS[self.sleep_i]
        self.sleep_end = time.time() + minutes * 60 if minutes else 0
        try:
            self.zbtn.configure(text="Zzz %d:00" % minutes if minutes else "Zzz off")
        except Exception:
            pass
        self._set_status("Sleep timer: %d min" % minutes if minutes else "Sleep timer off")

    def _tick(self) -> None:
        try:
            if self.sleep_end:
                left = int(self.sleep_end - time.time())
                if left <= 0:
                    self.player.stop()
                    self.sleep_end = 0
                    self.sleep_i = 0
                    try:
                        self.zbtn.configure(text="Zzz off")
                    except Exception:
                        pass
                    self._set_status("Sleep timer: playback stopped")
                else:
                    try:
                        self.zbtn.configure(text="Zzz %d:%02d" % divmod(left, 60))
                    except Exception:
                        pass
            self.after(1000, self._tick)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------
    def _startup(self) -> None:
        threading.Thread(target=self._startup_worker, daemon=True).start()
        self._refresh_tool_status()

    def _startup_worker(self) -> None:
        status = core.tools.check_tools()
        missing = [
            name for name in ("mpv", "ffmpeg", "yt-dlp")
            if not status.get(name, {}).get("ok")
        ]
        self.after(0, lambda: self._apply_startup_status(status, missing))

    def _apply_startup_status(self, status: dict, missing: list[str]) -> None:
        self._apply_tool_status(status)
        if not missing:
            return
        warned = list(self.settings.get("warned", []))
        new_missing = [name for name in missing if ("missing_" + name) not in warned]
        if new_missing:
            warned.extend("missing_" + name for name in new_missing)
            self.settings.set("warned", warned)
            self._set_status("Missing: %s — see Settings" % ", ".join(new_missing))

    # ------------------------------------------------------------------
    # Quit / restart
    # ------------------------------------------------------------------
    def quit_app(self) -> None:
        try:
            self.player.stop()
            self.downloads.stop_all()
        finally:
            try:
                self.destroy()
            except Exception:
                pass

    def _restart_app(self) -> None:
        self.quit_app()
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except OSError:
            pass


def run(settings: core.settings.Settings) -> None:
    """Launch the plain Tkinter UI (blocking until the window is closed)."""
    app = App(settings)
    app.mainloop()