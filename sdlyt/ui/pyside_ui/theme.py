"""Design tokens, QSS theme and inline SVG icons.

One palette (dark + light) and one QSS generator feed the whole UI.
No inline styling is scattered across widget modules.

Icons are inline SVG strings; nothing reads from disk. Render once
per (name, color, size) and cache.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QRectF, Qt, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Palette:
    """One UI palette. Values use the same hex codes as the CTk version."""

    bg: str
    panel: str
    card: str
    card_hover: str
    sel: str
    fg: str
    muted: str
    accent: str
    accent_hover: str
    success: str
    danger: str
    warn: str
    line: str


DARK = Palette(
    bg="#0f1115",
    panel="#171a21",
    card="#1d2129",
    card_hover="#262b35",
    sel="#243044",
    fg="#e5e7eb",
    muted="#8b93a1",
    accent="#3b82f6",
    accent_hover="#2563eb",
    success="#10b981",
    danger="#f87171",
    warn="#fbbf24",
    line="#232833",
)

LIGHT = Palette(
    bg="#f5f6f8",
    panel="#ffffff",
    card="#ffffff",
    card_hover="#eef2f7",
    sel="#dbeafe",
    fg="#111827",
    muted="#6b7280",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    success="#059669",
    danger="#dc2626",
    warn="#d97706",
    line="#e5e7eb",
)


def palette_for(mode: str) -> Palette:
    """Return the dark or light palette for *mode*."""
    return LIGHT if mode == "light" else DARK


# ---------------------------------------------------------------------------
# QSS
# ---------------------------------------------------------------------------
def build_qss(p: Palette, compact: bool = False) -> str:
    """Return the global QSS for *p*."""
    radius = 8 if compact else 12
    pad = "6px 10px" if compact else "8px 14px"
    return f"""
    QWidget {{
        background-color: {p.bg};
        color: {p.fg};
        font-family: "Inter", "Segoe UI", "DejaVu Sans", sans-serif;
        font-size: 13px;
    }}
    QFrame#TopBar, QFrame#BottomBar, QFrame#Sidebar {{
        background-color: {p.panel};
    }}
    QLineEdit#SearchField {{
        background-color: {p.card};
        border: 1px solid {p.line};
        border-radius: {radius}px;
        padding: {pad};
        color: {p.fg};
        selection-background-color: {p.accent};
    }}
    QLineEdit#SearchField:focus {{
        border: 1px solid {p.accent};
    }}
    QPushButton {{
        background-color: {p.panel};
        color: {p.fg};
        border: 1px solid {p.line};
        border-radius: {radius}px;
        padding: {pad};
    }}
    QPushButton:hover {{
        background-color: {p.card_hover};
    }}
    QPushButton:disabled {{
        color: {p.muted};
    }}
    QPushButton#Primary {{
        background-color: {p.accent};
        color: #ffffff;
        border: 1px solid {p.accent};
    }}
    QPushButton#Primary:hover {{
        background-color: {p.accent_hover};
        border: 1px solid {p.accent_hover};
    }}
    QPushButton#Danger {{
        background-color: {p.danger};
        color: #ffffff;
        border: 1px solid {p.danger};
    }}
    QPushButton#SidebarButton {{
        background-color: transparent;
        color: {p.muted};
        border: none;
        border-radius: {radius}px;
        padding: 8px 12px;
        text-align: left;
    }}
    QPushButton#SidebarButton:hover {{
        background-color: {p.card_hover};
        color: {p.fg};
    }}
    QPushButton#SidebarButton:checked {{
        background-color: {p.sel};
        color: {p.fg};
    }}
    QFrame#ResultCard {{
        background-color: {p.card};
        border-radius: {radius}px;
    }}
    QFrame#ResultCard[selected="true"] {{
        background-color: {p.sel};
    }}
    QLabel#Title {{
        color: {p.fg};
        font-weight: 600;
        background: transparent;
    }}
    QLabel#Meta {{
        color: {p.muted};
        font-size: 11px;
        background: transparent;
    }}
    QLabel#Header {{
        color: {p.accent};
        font-size: 13px;
        font-weight: 700;
        background: transparent;
    }}
    QLabel#About {{
        color: {p.muted};
        font-size: 11px;
        background: transparent;
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p.muted};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QProgressBar {{
        background-color: {p.line};
        border: none;
        border-radius: 3px;
        height: 6px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {p.accent};
        border-radius: 3px;
    }}
    QComboBox {{
        background-color: {p.panel};
        border: 1px solid {p.line};
        border-radius: {radius}px;
        padding: 6px 10px;
        color: {p.fg};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p.panel};
        color: {p.fg};
        selection-background-color: {p.accent};
        border: 1px solid {p.line};
    }}
    QCheckBox {{
        background: transparent;
        color: {p.fg};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {p.line};
        border-radius: 4px;
        background-color: {p.panel};
    }}
    QCheckBox::indicator:checked {{
        background-color: {p.accent};
        border: 1px solid {p.accent};
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {p.line};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {p.accent};
        width: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QSlider::sub-page:horizontal {{
        background: {p.accent};
        border-radius: 2px;
    }}
    QStackedWidget {{
        background: transparent;
    }}
    """


# ---------------------------------------------------------------------------
# Inline SVG icons
# ---------------------------------------------------------------------------
_ICONS: dict[str, str] = {
    "search": (
        '<path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16'
        'c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 '
        '5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>'
    ),
    "play": '<path d="M8 5v14l11-7z"/>',
    "stop": '<path d="M6 6h12v12H6z"/>',
    "download": '<path d="M5 20h14v-2H5v2zM19 9h-4V3H9v6H5l7 7 7-7z"/>',
    "history": (
        '<path d="M13 3a9 9 0 0 0-9 9H1l4 4 4-4H6a7 7 0 1 1 7 7c-1.93 0-3.68-.79-4.94-2.06'
        'l-1.42 1.42A8.954 8.954 0 0 0 13 21a9 9 0 0 0 0-18zm-1 5v5l4 2.38.75-1.23'
        '-3.25-1.9V8H12z"/>'
    ),
    "library": (
        '<path d="M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 '
        '2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-1 9h-4v4h-2v-4H9V9h4V5h2v4h4v2z"/>'
    ),
    "queue": '<path d="M3 6h18v2H3V6zm0 5h18v2H3v-2zm0 5h12v2H3v-2z"/>',
    "settings": (
        '<path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 '
        '0 0 .12-.61l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94'
        'l-.36-2.54a.484.484 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54'
        'c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47'
        '.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61'
        'l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41'
        '.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96'
        'c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6'
        'c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>'
    ),
    "account": (
        '<path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2'
        'c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>'
    ),
    "moon": (
        '<path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 0 1-4.4 2.26 '
        '5.403 5.403 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/>'
    ),
    "volume": (
        '<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 7.97v8.05'
        'c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71'
        'v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>'
    ),
    "close": (
        '<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 '
        '12 13.41 17.59 19 19 17.59 13.41 12z"/>'
    ),
    "check": '<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>',
    "error": (
        '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z'
        'm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>'
    ),
    "warning": '<path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>',
    "info": (
        '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z'
        'm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>'
    ),
}

_ICON_CACHE: dict[tuple[str, str, int], QPixmap] = {}


def svg_icon(name: str, color: str, size: int = 20) -> QPixmap:
    """Render a cached SVG icon in *color* at *size* pixels."""
    key = (name, color, size)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached

    body = _ICONS.get(name, "")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="{color}">{body}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    _ICON_CACHE[key] = pixmap
    return pixmap


def svg_icon_qicon(name: str, color: str, size: int = 20) -> QIcon:
    """Return a QIcon built from :func:`svg_icon`."""
    return QIcon(svg_icon(name, color, size))


def icon_size(size: int = 20) -> QSize:
    """Small helper for ``setIconSize``."""
    return QSize(size, size)