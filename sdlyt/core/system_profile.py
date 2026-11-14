"""Hardware detection and UI recommendation.

The thresholds intentionally live in one place. A Raspberry Pi sold as
"2 GB" typically reports about 1.8–1.95 GB in ``/proc/meminfo``, so a
strict ``>= 1900`` check classifies some nominal 2 GB boards as weak.
That is deliberate: PySide6 on such a board is not a good experience.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import struct
import subprocess
import sys

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
PYSIDE6_MIN_RAM_MB = 1900
LOW_RAM_MB = 1500
VERY_LOW_RAM_MB = 700


def total_ram_mb() -> int:
    """Return total physical RAM in MiB.

    Tries psutil first, then ``/proc/meminfo``, then a few platform
    fallbacks. Returns 4096 on total failure so the application remains
    usable.
    """
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().total / (1024 * 1024))
    except Exception:
        pass

    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass

    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True, timeout=5
            )
            return int(out.strip()) // (1024 * 1024)
        except Exception:
            pass

    return 4096


def cpu_cores() -> int:
    """Return the number of logical CPUs, with a safe fallback."""
    try:
        import psutil  # type: ignore

        return psutil.cpu_count(logical=True) or os.cpu_count() or 1
    except Exception:
        return os.cpu_count() or 1


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _real_import(name: str) -> bool:
    """Try a real import so half-installed packages do not pass the check."""
    try:
        __import__(name)
        return True
    except Exception:
        return False


def ctk_available() -> bool:
    """Return True when CustomTkinter can be imported."""
    return _real_import("customtkinter")


def pyside6_available() -> bool:
    """Return True when PySide6 has a usable wheel on this platform."""
    machine = platform.machine().lower()
    if machine in ("armv6l", "armv7l", "i386", "i686"):
        return False
    if struct.calcsize("P") * 8 != 64:
        return False
    return _real_import("PySide6")


def is_very_low_ram() -> bool:
    """True for devices where even CTk is uncomfortable."""
    return total_ram_mb() < VERY_LOW_RAM_MB


def is_low_ram() -> bool:
    """True for the existing low-RAM tuning tier."""
    return total_ram_mb() < LOW_RAM_MB


def is_weak_system() -> bool:
    """True when the machine is a poor fit for heavy UI or 4K playback."""
    return total_ram_mb() < PYSIDE6_MIN_RAM_MB or cpu_cores() <= 2


def recommended_ui() -> str:
    """Return the UI identifier that best fits this machine."""
    ram = total_ram_mb()
    if pyside6_available() and ram >= PYSIDE6_MIN_RAM_MB:
        return "pyside6"
    if ctk_available() and ram >= LOW_RAM_MB:
        return "ctk"
    return "tk"


def ui_supported(ui: str) -> bool:
    """Return whether *ui* can be loaded at all (real import, not find_spec)."""
    if ui == "pyside6":
        return pyside6_available()
    if ui == "ctk":
        return ctk_available()
    if ui == "tk":
        return True
    return False


def ui_too_heavy(ui: str) -> bool:
    """Return True when *ui* is likely too heavy for this machine."""
    if ui == "pyside6":
        return (not pyside6_available()) or total_ram_mb() < PYSIDE6_MIN_RAM_MB
    if ui == "ctk":
        return (not ctk_available()) or total_ram_mb() < LOW_RAM_MB
    return False


def describe() -> dict[str, object]:
    """Return a small dictionary for About/settings screens."""
    return {
        "ram_mb": total_ram_mb(),
        "cores": cpu_cores(),
        "weak": is_weak_system(),
        "low_ram": is_low_ram(),
        "very_low_ram": is_very_low_ram(),
        "recommended_ui": recommended_ui(),
        "pyside6": pyside6_available(),
        "ctk": ctk_available(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
