"""CustomTkinter UI for Super Duper Lite YT.

Contains only view logic. All backend work (search, downloads, playback,
thumbnails, history, settings) is delegated to :mod:`sdlyt.core`.
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .. import core
from ..core import resolutions, system_profile
from ..core.thumbs import HAVE_PIL

# ----------------------------------------------------------------------
# Palette (light, dark) — from the original sdlyt.py
# ----------------------------------------------------------------------
BG = ("#f5f6f8", "#0f1115")
PANEL = ("#ffffff", "#171a21")
CARD = ("#ffffff", "#1d2129")
CARD_HOV = ("#eef2f7", "#262b35")
SEL = ("#dbeafe", "#243044")
FG = ("#111827", "#e5e7eb")
MUTED = ("#6b7280", "#8b93a1")
ACCENT = ("#2563eb", "#3b82f6")
ACCENT_H = ("#1d4ed8", "#2563eb")
SUCCESS = ("#059669", "#10b981")
DANGER = ("#dc2626", "#f87171")
WARN = ("#d97706", "#fbbf24")
LINE = ("#e5e7eb", "#232833")

SLEEP_STEPS = (0, 15, 30, 45, 60, 90)

UI_LABELS = {
    "auto": "Auto",
    "tk": "Tkinter",
    "ctk": "CustomTkinter",
    "pyside6": "PySide6",
}
LABEL_TO_UI = {v: k for k, v in UI_LABELS.items()}


# ----------------------------------------------------------------------
# Toast
# ----------------------------------------------------------------------
class Toast(ctk.CTkToplevel):
    """Brief, non-blocking notification stacked near the bottom."""

    _stack: int = 0

    def __init__(self, parent: ctk.CTk, message: str, kind: str = "info", duration: int = 2400):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        color = {"info": ACCENT, "ok": SUCCESS, "err": DANGER, "warn": WARN}.get(kind, ACCENT)

        frame = ctk.CTkFrame(self, fg_color=color, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=1, pady=1)
        ctk.CTkLabel(
            frame,
            text=message,
            text_color="#ffffff",
            font=ctk.CTkFont(size=12, weight="bold"),
            wraplength=max(280, parent.winfo_width() - 120),
            justify="center",
        ).pack(padx=18, pady=12)

        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        offset = 90 + Toast._stack * (h + 8)
        x = px + (pw - w) // 2
        y = py + ph - h - offset
        self.geometry("+%d+%d" % (x, y))
        Toast._stack += 1
        self.after(duration, self._dismiss)

    def _dismiss(self) -> None:
        Toast._stack = max(0, Toast._stack - 1)
        try:
            self.destroy()
        except Exception:
            pass


# ----------------------------------------------------------------------
# Result list
# ----------------------------------------------------------------------
class CardList(ctk.CTkScrollableFrame):
    """Scrollable list of rounded cards with an optional thumbnail."""

    def __init__(self, parent, app: "App", empty_text: str = "Nothing here yet"):
        super().__init__(parent, fg_color="transparent", corner_radius=0,
                         scrollbar_button_color=MUTED, scrollbar_button_hover_color=FG)
        self.app = app
        self.empty_text = empty_text
        self.items: list[dict] = []
        self.cards: list[ctk.CTkFrame] = []
        self.selected: int | None = None
        self.multi: set[int] = set()
        self.multi_mode = False
        self.on_open = None
        self.on_select = None
        self._thumb_size = app.thumb_size
        self.paint_empty()

    # -- public API --
    def paint_empty(self) -> None:
        for widget in self.winfo_children():
            widget.destroy()
        self.cards = []
        ctk.CTkLabel(self, text=self.empty_text, text_color=MUTED,
                     font=self.app.font("meta"), justify="center").pack(pady=60)

    def set_items(self, items: list[dict], multi_mode: bool = False) -> None:
        self.items = items
        self.multi = set()
        self.multi_mode = multi_mode
        self.selected = None
        self.render()
        try:
            self._parent_canvas.yview_moveto(0)
        except Exception:
            pass

    def selected_item(self) -> dict | None:
        if self.selected is not None and self.selected < len(self.items):
            return self.items[self.selected]
        return None

    def selected_items(self) -> list[dict]:
        if self.multi_mode:
            return [self.items[i] for i in sorted(self.multi) if i < len(self.items)]
        item = self.selected_item()
        return [item] if item else []

    def render(self) -> None:
        for widget in self.winfo_children():
            widget.destroy()
        self.cards = []
        if not self.items:
            self.paint_empty()
            return
        for index, item in enumerate(self.items):
            self.cards.append(self._make_card(index, item))
        if self.selected is not None and self.selected < len(self.cards):
            self._paint(self.selected, True)

    # -- internals --
    def _make_card(self, index: int, item: dict) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, height=80)
        card.pack(fill="x", padx=6, pady=(6, 0))
        card.pack_propagate(False)

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=8)

        thumb = ctk.CTkLabel(body, text="", width=self._thumb_size[0],
                             height=self._thumb_size[1], fg_color=PANEL, corner_radius=8)
        thumb.pack(side="left")
        if self.app.settings.get("thumbs") and item.get("id"):
            self.app.thumbs.request(
                item["id"],
                lambda pil, lbl=thumb: self.app.after(0, lambda: self._apply_thumb(lbl, pil)),
            )

        column = ctk.CTkFrame(body, fg_color="transparent")
        column.pack(side="left", fill="both", expand=True, padx=(10, 0))

        title = ctk.CTkLabel(column, text=item.get("title", "?"), text_color=FG,
                             font=self.app.font("title"), anchor="w", justify="left",
                             wraplength=max(120, self.app.win_width - self._thumb_size[0] - 90))
        title.pack(anchor="w", fill="x")

        meta_text = item.get("meta", "") or item.get("channel", "")
        if item.get("length") and item["length"] != "NA":
            meta_text = (meta_text + "  ·  " + item["length"]).strip(" ·")
        meta = ctk.CTkLabel(column, text=meta_text, text_color=MUTED,
                            font=self.app.font("meta"), anchor="w", justify="left")
        meta.pack(anchor="w", fill="x", pady=(2, 0))

        if self.multi_mode:
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(card, text="", width=24, variable=var,
                                 command=lambda idx=index, v=var: self._toggle(idx, v.get()))
            cb.place(relx=1.0, rely=0.5, anchor="e", x=-8)
            card._checkvar = var

        for widget in (card, body, thumb, column, title, meta):
            widget.bind("<Button-1>", lambda _e, idx=index: self._select(idx))
            widget.bind("<Double-Button-1>", lambda _e, idx=index: self._open(idx))

        card._parts = (card, title, meta, thumb)
        return card

    def _apply_thumb(self, label: ctk.CTkLabel, pil) -> None:
        if pil is None:
            return
        try:
            width, height = self._thumb_size
            image = ctk.CTkImage(light_image=pil, dark_image=pil, size=(width, height))
            label.configure(image=image, text="")
            label._img = image
        except Exception:
            pass

    def _paint(self, index: int, on: bool) -> None:
        if index >= len(self.cards):
            return
        card = self.cards[index]._parts[0]
        try:
            card.configure(fg_color=SEL if on else CARD)
        except Exception:
            pass

    def _select(self, index: int) -> None:
        if self.selected is not None and self.selected < len(self.cards):
            self._paint(self.selected, False)
        self.selected = index
        self._paint(index, True)
        if self.on_select:
            self.on_select()

    def _open(self, index: int) -> None:
        self._select(index)
        if self.on_open:
            self.on_open()

    def _toggle(self, index: int, on: bool) -> None:
        if on:
            self.multi.add(index)
        else:
            self.multi.discard(index)


# ----------------------------------------------------------------------
# Queue row
# ----------------------------------------------------------------------
class JobRow:
    """One download job with progress, info and action buttons."""

    def __init__(self, app: "App", job: core.downloads.DownloadJob, parent):
        self.app = app
        self.job = job
        self.frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        self.frame.pack(fill="x", padx=6, pady=(6, 0))

        inner = ctk.CTkFrame(self.frame, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=10)

        self.title = ctk.CTkLabel(inner, text="", text_color=FG,
                                  font=app.font("title"), anchor="w", justify="left",
                                  wraplength=max(180, app.win_width - 80))
        self.title.pack(fill="x")

        self.bar = ctk.CTkProgressBar(inner, height=6, corner_radius=3,
                                      progress_color=ACCENT, fg_color=LINE)
        self.bar.pack(fill="x", pady=6)
        self.bar.set(0)

        self.info = ctk.CTkLabel(inner, text="", text_color=MUTED,
                                 font=app.font("small"), anchor="w", justify="left",
                                 wraplength=max(180, app.win_width - 80))
        self.info.pack(fill="x")

        buttons = ctk.CTkFrame(inner, fg_color="transparent")
        buttons.pack(anchor="e", pady=(6, 0))
        self.primary = ctk.CTkButton(buttons, text="Cancel", width=80, height=28,
                                     fg_color=PANEL, text_color=FG, command=self._act)
        self.primary.pack(side="right", padx=(4, 0))
        self.secondary = ctk.CTkButton(buttons, text="Remove", width=80, height=28,
                                       fg_color="transparent", text_color=MUTED,
                                       command=lambda: self.app.downloads.remove(self.job))
        self.secondary.pack(side="right")

        self.refresh()

    def _act(self) -> None:
        if self.job.state in ("queued", "running"):
            self.app.downloads.cancel(self.job)
        else:
            self.app.downloads.retry(self.job)

    def refresh(self) -> None:
        job = self.job
        prefix = "[V] " if job.kind == "video" else "[A] "
        try:
            self.title.configure(text=prefix + job.title)
        except Exception:
            pass
        try:
            self.bar.set((job.pct or 0.0) / 100.0)
        except Exception:
            pass

        text = {
            "queued": "Queued",
            "running": job.info or "Starting…",
            "done": "✓ Done",
            "failed": "✗ " + (job.err or "Failed"),
            "cancelled": "Cancelled — retry resumes",
            "paused": "Interrupted — retry resumes",
        }.get(job.state, job.state)
        color = {"done": SUCCESS, "failed": DANGER}.get(job.state, MUTED)

        try:
            self.info.configure(text=text, text_color=color)
            if job.state == "done":
                self.primary.pack_forget()
            else:
                self.primary.configure(
                    text="Cancel" if job.state in ("queued", "running") else "Retry"
                )
                try:
                    self.primary.pack(side="right", padx=(4, 0), before=self.secondary)
                except Exception:
                    pass
        except Exception:
            pass


# ----------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------
class App(ctk.CTk):
    """The CustomTkinter application window."""

    def __init__(self, settings: core.settings.Settings):
        super().__init__()
        self.settings = settings

        self.title("Super Duper Lite YT (CustomTkinter)")
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.win_width = screen_w
        self.win_height = screen_h - max(20, min(60, int(screen_h * 0.06)))
        self.geometry("%dx%d+0+0" % (self.win_width, self.win_height))
        self.minsize(360, 240)
        self.bind("<Escape>", lambda _e: self.quit_app())
        self.bind("<Configure>", self._on_resize)

        self.thumb_size = self._compute_thumb(screen_w)
        self.compact = system_profile.is_low_ram() or screen_w < 600

        # -- services --------------------------------------------------
        self.history = core.history.History()
        self.thumbs = core.thumbs.ThumbService(
            size=self.thumb_size,
            enabled=bool(settings.get("thumbs")) and HAVE_PIL,
        )
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

        # -- state -----------------------------------------------------
        self.rows: dict[int, JobRow] = {}
        self.recent: list[str] = core.utils.jload(core.paths.RECENT, []) or []
        self.sleep_end = 0
        self.sleep_i = 0

        # -- appearance ------------------------------------------------
        ctk.set_appearance_mode(str(settings.get("appearance", "dark")))
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=BG)
        self._init_fonts()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.after(400, self._startup)
        self.after(1000, self._tick)

    # ------------------------------------------------------------------
    # Fonts / sizing
    # ------------------------------------------------------------------
    def _init_fonts(self) -> None:
        scale = float(self.settings.get("font_scale", 1.0))
        base = 12 * scale
        self._fonts = {
            "title": ctk.CTkFont(size=int(base), weight="bold"),
            "meta": ctk.CTkFont(size=int(base - 2)),
            "head": ctk.CTkFont(size=int(base + 3), weight="bold"),
            "body": ctk.CTkFont(size=int(base)),
            "small": ctk.CTkFont(size=int(base - 3)),
        }

    def font(self, kind: str) -> ctk.CTkFont:
        return self._fonts.get(kind, self._fonts["body"])

    @staticmethod
    def _compute_thumb(screen_w: int) -> tuple[int, int]:
        if screen_w < 480:
            return (56, 32)
        if screen_w < 768:
            return (72, 40)
        if screen_w < 1280:
            return (96, 54)
        return (112, 63)

    def _on_resize(self, event) -> None:
        if event.widget is not self:
            return
        bucket = self._compute_thumb(event.width)
        if bucket == self.thumb_size:
            return
        self.thumb_size = bucket
        if hasattr(self, "find_list"):
            self.find_list._thumb_size = bucket
        self.after(200, self._rerender_lists)

    def _rerender_lists(self) -> None:
        for name in ("find_list", "hist_list", "lib_list"):
            lst = getattr(self, name, None)
            if lst is not None and lst.items:
                lst.render()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # top bar
        self.topbar = ctk.CTkFrame(self, fg_color=PANEL, height=48, corner_radius=0)
        self.topbar.pack(fill="x", side="top")
        self.topbar.pack_propagate(False)
        ctk.CTkLabel(self.topbar, text="▶ Super Duper Lite YT", text_color=FG,
                     font=self.font("head")).pack(side="left", padx=14)
        self.top_status = ctk.CTkLabel(self.topbar, text="Ready", text_color=MUTED,
                                       font=self.font("small"))
        self.top_status.pack(side="left", padx=12)
        ctk.CTkButton(self.topbar, text="✕", width=34, height=30,
                      fg_color="transparent", hover_color=CARD_HOV, text_color=FG,
                      command=self.quit_app).pack(side="right", padx=6)

        # bottom bar
        self.bottombar = ctk.CTkFrame(self, fg_color=PANEL, height=52, corner_radius=0)
        self.bottombar.pack(fill="x", side="bottom")
        self.bottombar.pack_propagate(False)
        ctk.CTkButton(self.bottombar, text="⏹ Stop", width=80, height=34,
                      fg_color="transparent", hover_color=CARD_HOV, text_color=FG,
                      command=self.player.stop).pack(side="right", padx=6, pady=9)
        self.zbtn = ctk.CTkButton(self.bottombar, text="Zzz off", width=90, height=34,
                                  fg_color="transparent", hover_color=CARD_HOV,
                                  text_color=FG, command=self.cycle_sleep)
        self.zbtn.pack(side="right", padx=6, pady=9)
        ctk.CTkLabel(self.bottombar, text="🔊", text_color=FG).pack(side="right", padx=(8, 0))
        self.vol_var = ctk.IntVar(value=int(self.settings.get("volume", 100)))
        ctk.CTkSlider(self.bottombar, from_=0, to=100, number_of_steps=20, width=110,
                      variable=self.vol_var,
                      command=self._on_volume).pack(side="right", padx=4)

        # tabs
        self.tabview = ctk.CTkTabview(
            self, fg_color=BG,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_H,
            segmented_button_unselected_color=PANEL,
            segmented_button_unselected_hover_color=CARD_HOV,
            text_color=FG,
        )
        self.tabview.pack(fill="both", expand=True, padx=8, pady=(4, 4))
        self.tabs = {}
        for name in ("Find", "Hist", "Lib", "Queue", "Set", "Acct"):
            self.tabview.add(name)
            self.tabs[name] = self.tabview.tab(name)

        self._build_find(self.tabs["Find"])
        self._build_hist(self.tabs["Hist"])
        self._build_lib(self.tabs["Lib"])
        self._build_queue(self.tabs["Queue"])
        self._build_settings(self.tabs["Set"])
        self._build_account(self.tabs["Acct"])

    # -- Find ----------------------------------------------------------
    def _build_find(self, parent) -> None:
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", pady=(4, 6))
        self.q = ctk.CTkEntry(bar, placeholder_text="Search YouTube…", height=40,
                              font=self.font("body"), fg_color=PANEL, text_color=FG)
        self.q.pack(side="left", fill="x", expand=True)
        self.q.bind("<Return>", lambda _e: self.search())
        ctk.CTkButton(bar, text="Go", width=60, height=40, fg_color=ACCENT,
                      hover_color=ACCENT_H, command=self.search).pack(side="left", padx=(6, 0))

        self.audio_var = ctk.BooleanVar(value=bool(self.settings.get("audio_only")))
        ctk.CTkSwitch(bar, text="🎵 Audio only", variable=self.audio_var,
                      font=self.font("small"), text_color=FG, progress_color=ACCENT,
                      command=self._save_audio_only).pack(side="left", padx=(10, 0))

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", pady=4)
        for text, cmd, accent in (
            ("▶ Play", lambda: self._do_play(self._current_list(), self.audio_var.get()), True),
            ("♪ Listen", lambda: self._do_play(self._current_list(), True), False),
            ("⏬ Video", lambda: self._do_dl(self._current_list(), "video"), False),
            ("⏬ Audio", lambda: self._do_dl(self._current_list(), "audio"), False),
        ):
            ctk.CTkButton(
                actions, text=text, height=36, command=cmd,
                fg_color=ACCENT if accent else PANEL,
                hover_color=ACCENT_H if accent else CARD_HOV,
                text_color="#ffffff" if accent else FG,
                font=self.font("small"),
            ).pack(side="left", padx=(0, 6))

        self.find_list = CardList(
            parent, self,
            "Search for a video, song or channel.\nTap once to select, double-tap to play.",
        )
        self.find_list.pack(fill="both", expand=True, pady=(6, 0))
        self.find_list.on_open = lambda: self._do_play(self.find_list, self.audio_var.get())

    def _current_list(self) -> CardList | None:
        current = self.tabview.get()
        return {
            "Find": getattr(self, "find_list", None),
            "Hist": getattr(self, "hist_list", None),
            "Lib": getattr(self, "lib_list", None),
        }.get(current)

    def _save_audio_only(self) -> None:
        self.settings.set("audio_only", bool(self.audio_var.get()))

    # -- History -------------------------------------------------------
    def _build_hist(self, parent) -> None:
        self.hist_list = CardList(parent, self, "Nothing played yet.")
        self.hist_list.pack(fill="both", expand=True, pady=4)
        self.hist_list.on_open = lambda: self._do_play(self.hist_list, self.audio_var.get())
        ctk.CTkButton(parent, text="Clear history", height=32, fg_color=DANGER,
                      hover_color=("#b91c1c", "#dc2626"),
                      command=self._clear_history).pack(pady=(0, 4))
        self._refresh_history()

    def _refresh_history(self) -> None:
        items = []
        for entry in list(self.history)[:80]:
            item = dict(entry)
            item["meta"] = "  ·  ".join(
                part for part in (entry.get("channel", ""), entry.get("when", "")) if part
            )
            items.append(item)
        self.hist_list.set_items(items)

    def _clear_history(self) -> None:
        if messagebox.askyesno("Clear history", "Delete all play history?"):
            self.history.clear()
            self._refresh_history()

    # -- Library -------------------------------------------------------
    def _build_lib(self, parent) -> None:
        self.lib_summary = ctk.StringVar(value="")
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkButton(head, text="Refresh", height=32,
                      command=self._refresh_library).pack(side="right")
        ctk.CTkLabel(head, textvariable=self.lib_summary, text_color=MUTED,
                     font=self.font("small")).pack(side="left")

        self.lib_list = CardList(parent, self,
                                 "No downloads yet.\nUse Video or Audio on a result.")
        self.lib_list.pack(fill="both", expand=True, pady=4)
        self.lib_list.on_open = self._play_library_item
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
                    "name": name,
                    "size": size,
                    "kind": kind,
                    "mtime": os.path.getmtime(full),
                    "id": match.group(1) if match else "",
                    "title": re.sub(r"\s*\[[\w-]{11}\]", "", os.path.splitext(name)[0]),
                    "meta": "%s  ·  %s" % (kind, core.utils.human(size)),
                })
        except OSError:
            pass

        items.sort(key=lambda row: row["mtime"], reverse=True)
        if hasattr(self, "lib_list"):
            self.lib_list.set_items(items)
        try:
            free = core.utils.human(shutil.disk_usage(out).free)
        except Exception:
            free = "?"
        self.lib_summary.set("%d files · %s free · %s" % (len(items), free, out))

    def _play_library_item(self) -> None:
        item = self.lib_list.selected_item()
        if not item:
            self._toast("Select a file first", "warn")
            return
        self.player.play_local(item["path"], item["kind"] == "Audio",
                               "Playing: " + item["title"][:40])

    # -- Queue ---------------------------------------------------------
    def _build_queue(self, parent) -> None:
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkButton(head, text="Clear done", height=32,
                      command=self.downloads.clear_done).pack(side="left")
        ctk.CTkButton(head, text="Retry all", height=32,
                      command=self.downloads.retry_all).pack(side="left", padx=6)
        self.q_summary = ctk.StringVar()
        ctk.CTkLabel(head, textvariable=self.q_summary, text_color=MUTED,
                     font=self.font("small")).pack(side="right")

        self.q_frame = ctk.CTkScrollableFrame(parent, fg_color="transparent", corner_radius=0)
        self.q_frame.pack(fill="both", expand=True, pady=6)

        for job in self.downloads.jobs:
            self.rows[job.uid] = JobRow(self, job, self.q_frame)
        self._refresh_queue_summary()

    def _refresh_queue_summary(self) -> None:
        counts: dict[str, int] = {}
        for job in self.downloads.jobs:
            counts[job.state] = counts.get(job.state, 0) + 1
        text = "  ·  ".join("%d %s" % (count, state) for state, count in counts.items())
        self.q_summary.set(text or "Queue is empty")

    def _on_queue_changed(self) -> None:
        self.after(0, self._sync_queue_rows)

    def _sync_queue_rows(self) -> None:
        live = {job.uid for job in self.downloads.jobs}
        for job in self.downloads.jobs:
            if job.uid not in self.rows:
                self.rows[job.uid] = JobRow(self, job, self.q_frame)
        for uid in list(self.rows.keys()):
            if uid not in live:
                try:
                    self.rows[uid].frame.destroy()
                except Exception:
                    pass
                del self.rows[uid]
        self._refresh_queue_summary()

    def _on_job_update(self, job: core.downloads.DownloadJob) -> None:
        self.after(0, lambda: self._apply_job_update(job))

    def _apply_job_update(self, job: core.downloads.DownloadJob) -> None:
        row = self.rows.get(job.uid)
        if row is not None:
            row.refresh()
        self._refresh_queue_summary()

    # -- Settings ------------------------------------------------------
    def _build_settings(self, parent) -> None:
        sf = ctk.CTkScrollableFrame(parent, fg_color="transparent", corner_radius=0)
        sf.pack(fill="both", expand=True)

        def head(text: str) -> None:
            ctk.CTkLabel(sf, text=text, text_color=ACCENT, font=self.font("head"),
                         anchor="w").pack(fill="x", pady=(12, 2))

        def note(text: str) -> None:
            ctk.CTkLabel(sf, text=text, text_color=MUTED, font=self.font("small"),
                         anchor="w", justify="left",
                         wraplength=max(280, self.win_width - 60)).pack(fill="x", pady=(0, 4))

        head("Interface")
        self._build_ui_selector(sf)

        head("Playback")
        self._build_resolution_option(sf, "Play quality", "play_res")
        self._segmented(sf, "Speed", "speed", (0.75, 1.0, 1.25, 1.5))
        self._switch(sf, "Fullscreen playback", "fs")
        self._switch(sf, "Hardware decode", "hwdec")

        head("Downloads")
        self._build_resolution_option(sf, "Download quality", "dl_res")
        note(resolutions.container_note(int(self.settings.get("dl_res", 720))))
        self._segmented(sf, "Audio format", "audio_fmt", ("m4a", "mp3"))
        self._segmented(sf, "Parallel downloads", "parallel", (1, 2, 3))
        self._out_dir_row(sf)
        self._switch(sf, "Embed thumbnail + metadata", "embed")

        head("Subtitles")
        self._switch(sf, "Show / download subtitles", "subs")
        self._segmented(sf, "Language", "sub_lang",
                        ("en", "ar", "fr", "es", "de", "tr", "ur", "hi", "pt", "ru", "id"))

        head("Appearance")
        self._segmented(sf, "Mode", "appearance", ("dark", "light", "system"))
        self._segmented(sf, "Text size", "font_scale", (0.85, 1.0, 1.15, 1.3))
        self._switch(sf, "Show thumbnails", "thumbs")
        self._switch(sf, "Compact layout", "compact")
        self._switch(sf, "Audio-only by default", "audio_only")
        self._switch(sf, "Reduce animations", "reduce_animations")

        head("Tools & dependencies")
        self.tool_labels: dict[str, ctk.StringVar] = {}
        for key, label in (("mpv", "mpv"), ("ffmpeg", "ffmpeg"), ("yt-dlp", "yt-dlp"),
                           ("vlc", "VLC (optional)"), ("pillow", "Pillow"),
                           ("osk", "On-screen keyboard (optional)")):
            row = ctk.CTkFrame(sf, fg_color=CARD, corner_radius=10)
            row.pack(fill="x", pady=3)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=10, pady=8)
            ctk.CTkLabel(inner, text=label, text_color=FG, font=self.font("body"),
                         anchor="w").pack(fill="x")
            status = ctk.StringVar(value="checking…")
            ctk.CTkLabel(inner, textvariable=status, text_color=MUTED,
                         font=self.font("small"), anchor="w").pack(fill="x")
            self.tool_labels[key] = status
        ctk.CTkButton(sf, text="Refresh status", height=32,
                      command=self._refresh_tool_status).pack(anchor="w", pady=8)
        self._switch(sf, "Auto-update yt-dlp on launch", "auto_update")

        head("Storage")
        self.cache_var = ctk.StringVar()
        ctk.CTkLabel(sf, textvariable=self.cache_var, text_color=MUTED,
                     font=self.font("small"), anchor="w").pack(fill="x")
        ctk.CTkButton(sf, text="Clear thumbnails", height=32,
                      command=self._clear_thumb_cache).pack(anchor="w", pady=(4, 4))
        ctk.CTkButton(sf, text="Reset warnings", height=32,
                      command=self._reset_warnings).pack(anchor="w", pady=(0, 12))

        head("About")
        profile = system_profile.describe()
        ctk.CTkLabel(
            sf,
            text="Super Duper Lite YT 1.1.0 — 2026-11-13",
            text_color=FG, font=self.font("body"), anchor="w",
        ).pack(fill="x")
        note("Tiny, fast, touch-friendly YouTube for Pi and small screens.")
        note("RAM %d MB · %d cores · recommended UI: %s · Python %s" % (
            profile["ram_mb"], profile["cores"], profile["recommended_ui"], profile["python"],
        ))
        note("Not affiliated with YouTube or Google. Only download content you have the right to.")

        self._refresh_cache_label()

    def _build_ui_selector(self, parent) -> None:
        current = str(self.settings.get("ui", "auto"))
        resolved = system_profile.recommended_ui()
        ctk.CTkLabel(parent, text="Auto will use: %s" % resolved,
                     text_color=MUTED, font=self.font("small"),
                     anchor="w").pack(fill="x", pady=(0, 4))

        value = ctk.StringVar(value=UI_LABELS.get(current, "Auto"))

        def on_change(display: str) -> None:
            self._apply_ui_choice(LABEL_TO_UI.get(display, "auto"))

        ctk.CTkSegmentedButton(
            parent, values=list(UI_LABELS.values()), variable=value,
            font=self.font("small"), selected_color=ACCENT,
            selected_hover_color=ACCENT_H, command=on_change,
        ).pack(fill="x")

    def _apply_ui_choice(self, value: str) -> None:
        if value != "auto":
            if not system_profile.ui_supported(value):
                self._toast("%s is not available on this system." % UI_LABELS.get(value, value),
                            "err")
                return
            if system_profile.ui_too_heavy(value):
                ok = messagebox.askyesno(
                    "Warning — heavy UI",
                    "The %s interface may be slow or unstable on this device "
                    "(%d MB RAM, %d cores).\n\nContinue anyway?"
                    % (UI_LABELS.get(value, value),
                       system_profile.total_ram_mb(), system_profile.cpu_cores()),
                )
                if not ok:
                    return

        self.settings.set("ui", value)
        if messagebox.askyesno("Restart required", "Restart now to apply the new interface?"):
            self._restart_app()

    def _build_resolution_option(self, parent, label: str, key: str) -> None:
        ctk.CTkLabel(parent, text=label, text_color=FG, font=self.font("body"),
                     anchor="w").pack(fill="x", pady=(6, 2))
        heights = resolutions.RESOLUTIONS
        current = int(self.settings.get(key, 720))
        if current not in heights:
            current = heights[0]
        values = [resolutions.label(h) for h in heights]
        initial = resolutions.label(current)
        value = ctk.StringVar(value=initial)

        def on_change(display: str) -> None:
            for height in heights:
                if resolutions.label(height) == display:
                    self._set_resolution(key, height)
                    return

        ctk.CTkSegmentedButton(
            parent, values=values, variable=value, font=self.font("small"),
            selected_color=ACCENT, selected_hover_color=ACCENT_H, command=on_change,
        ).pack(fill="x")

    def _set_resolution(self, key: str, height: int) -> None:
        if not system_profile.is_weak_system():
            self.settings.set(key, height)
            return
        threshold = 720 if key == "play_res" else 1080
        if height <= threshold:
            self.settings.set(key, height)
            return
        warn_key = "%s_high_%d" % (key, height)
        if self.settings.was_warned(warn_key):
            self.settings.set(key, height)
            return
        self.settings.mark_warned(warn_key)
        messagebox.showwarning(
            "Warning",
            resolutions.weak_system_warning(height) + "\n\n"
            "This warning will not be shown again.",
        )
        self.settings.set(key, height)

    def _segmented(self, parent, label: str, key: str, values: tuple) -> None:
        ctk.CTkLabel(parent, text=label, text_color=FG, font=self.font("body"),
                     anchor="w").pack(fill="x", pady=(6, 2))
        current = self.settings.get(key)
        str_values = [str(v) for v in values]
        value = ctk.StringVar(value=str(current))
        ctk.CTkSegmentedButton(
            parent, values=str_values, variable=value, font=self.font("small"),
            selected_color=ACCENT, selected_hover_color=ACCENT_H,
            command=lambda val, k=key: self._set_opt(k, val),
        ).pack(fill="x")

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

        if key == "appearance":
            ctk.set_appearance_mode(str(coerced))
        elif key == "font_scale":
            self._init_fonts()
            self._rerender_lists()
        elif key == "thumbs":
            self.thumbs.enabled = bool(coerced) and HAVE_PIL
            self._rerender_lists()

    def _switch(self, parent, label: str, key: str) -> None:
        var = ctk.BooleanVar(value=bool(self.settings.get(key)))
        ctk.CTkSwitch(
            parent, text=label, variable=var, font=self.font("body"),
            text_color=FG, progress_color=ACCENT,
            command=lambda k=key, v=var: self._set_opt(k, "true" if v.get() else "false"),
        ).pack(anchor="w", pady=4)

    def _out_dir_row(self, parent) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Folder", text_color=FG,
                     font=self.font("body")).pack(side="left")
        self.out_var = ctk.StringVar(value=str(self.settings.get("out_dir", "")))
        ctk.CTkEntry(row, textvariable=self.out_var, height=32).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ctk.CTkButton(row, text="…", width=38, height=32,
                      command=self._pick_out_dir).pack(side="left")
        ctk.CTkButton(row, text="Apply", width=60, height=32,
                      command=self._apply_out_dir).pack(side="left", padx=4)

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
            ok = entry.get("ok")
            version = entry.get("version", "")
            try:
                label.set(("✓ " + (version or "installed")) if ok else "✗ not installed")
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
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", padx=8, pady=8)
        self.acc_var = ctk.StringVar()
        ctk.CTkLabel(card, textvariable=self.acc_var, text_color=ACCENT,
                     font=self.font("head"), anchor="w").pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            card,
            text=("Optional: import cookies.txt from a browser logged in to YouTube.\n"
                  "Used for age-restricted or private videos. Use a secondary account."),
            text_color=MUTED, font=self.font("small"), anchor="w", justify="left",
            wraplength=max(280, self.win_width - 60),
        ).pack(fill="x", padx=12)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=10)
        ctk.CTkButton(row, text="Import", height=34, fg_color=ACCENT,
                      command=self._import_cookies).pack(side="left")
        ctk.CTkButton(row, text="Log out", height=34, fg_color=DANGER,
                      command=self._remove_cookies).pack(side="left", padx=6)
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
            shutil.copy(path, core.paths.COOKIES)
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
        self.find_list.set_items(items, multi_mode=False)
        self._set_status("%d results" % len(items) if items else "No results")

    def _do_play(self, card_list: CardList | None, audio_only: bool) -> None:
        item = card_list.selected_item() if card_list else None
        if not item:
            self._toast("Select an item first", "warn")
            return
        self.history.add(item)
        self._refresh_history()
        self.player.play_url(item["id"], audio_only, item.get("title", ""))

    def _do_dl(self, card_list: CardList | None, kind: str) -> None:
        items = card_list.selected_items() if card_list else []
        if not items:
            self._toast("Select an item first", "warn")
            return

        res = int(self.settings.get("dl_res", 720))
        if kind == "video" and resolutions.is_above_1080(res) and system_profile.is_weak_system():
            warn_key = "dl_high_%d" % res
            if not self.settings.was_warned(warn_key):
                self.settings.mark_warned(warn_key)
                ok = messagebox.askyesno(
                    "Warning",
                    "Downloading %s may use significant disk space, RAM and bandwidth. "
                    "This warning will not be shown again.\n\nContinue?"
                    % resolutions.label(res),
                )
                if not ok:
                    return

        added = sum(1 for item in items if self.downloads.add(item, kind))
        if added:
            self._toast("Queued %d download%s" % (added, "s" if added > 1 else ""), "ok")

    # ------------------------------------------------------------------
    # Player callbacks (called from worker threads)
    # ------------------------------------------------------------------
    def _on_player_status(self, message: str) -> None:
        self.after(0, lambda: self._set_status(message))

    def _on_player_error(self, message: str) -> None:
        self.after(0, lambda: self._toast(message, "err"))

    def _on_toast(self, message: str, kind: str) -> None:
        self.after(0, lambda: self._toast(message, kind))

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    def _toast(self, message: str, kind: str = "info") -> None:
        try:
            Toast(self, message, kind)
        except Exception:
            pass

    def _set_status(self, message: str) -> None:
        try:
            self.top_status.configure(text=message[:80])
        except Exception:
            pass

    def _on_volume(self, _value) -> None:
        try:
            self.settings.set("volume", int(self.vol_var.get()))
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
        if self.settings.get("auto_update") and os.path.exists(core.paths.YT):
            threading.Thread(target=self._auto_update_worker, daemon=True).start()

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
            self._toast("Missing: %s — see Settings → Tools" % ", ".join(new_missing),
                        "warn")

    def _auto_update_worker(self) -> None:
        try:
            import subprocess

            subprocess.run([core.paths.YT, "-U"], capture_output=True, timeout=180)
        except Exception:
            pass

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


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def run(settings: core.settings.Settings) -> None:
    """Launch the CustomTkinter UI (blocking until the window is closed)."""
    app = App(settings)
    app.mainloop()
