"""Choose and launch a UI, with graceful fallback on startup failure.

Order of precedence for the first UI to attempt:

1. ``--ui=tk|ctk|pyside6`` CLI argument (never saved).
2. ``SDLYT_UI`` environment variable (never saved).
3. The ``ui`` key in ``settings.json``.
4. ``system_profile.recommended_ui()`` when the saved value is ``"auto"``.

If the chosen UI cannot be imported or raises during startup, the
launcher walks the fallback chain (lightest first) and tells the user
why. The saved preference is deliberately NOT overwritten.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import time
import traceback

from . import core

UI_NAMES: tuple[str, ...] = ("tk", "ctk", "pyside6")
FALLBACK_CHAIN: dict[str, tuple[str, ...]] = {
    "pyside6": ("ctk", "tk"),
    "ctk": ("tk", "pyside6"),
    "tk": ("ctk", "pyside6"),
}
ENV_VAR = "SDLYT_UI"
LOG_DIR = os.path.join(core.paths.APP_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "ui.log")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sdlyt",
        description="Super Duper Lite YT - a tiny YouTube client.",
    )
    parser.add_argument(
        "--ui",
        choices=list(UI_NAMES),
        default=None,
        help="Force a specific UI for this launch (does not save).",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the application version and exit.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Build the UI, pump events for ~2s, then exit 0/1.",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="If the requested UI fails, print the traceback and exit.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Write verbose launcher logs.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Run the format-selector self-test and exit.",
    )
    parser.add_argument(
        "--selftest-progress",
        action="store_true",
        help="Run the progress-parser self-test and exit.",
    )
    return parser.parse_args(argv)


def _resolve_ui(settings: core.settings.Settings, override: str | None) -> str:
    """Return the UI identifier to attempt first."""
    if override in UI_NAMES:
        return override
    env = os.environ.get(ENV_VAR, "").strip().lower()
    if env in UI_NAMES:
        return env
    saved = str(settings.get("ui", "auto")).lower()
    if saved in UI_NAMES:
        return saved
    return core.system_profile.recommended_ui()


def _load_runner(ui: str):
    """Import the module for *ui* and return its ``run(settings)`` callable."""
    package = __package__ or "sdlyt"
    if ui == "pyside6":
        module = importlib.import_module(".ui.pyside_ui.main_window", package)
    elif ui == "ctk":
        module = importlib.import_module(".ui.ctk_ui", package)
    elif ui == "tk":
        module = importlib.import_module(".ui.tk_ui", package)
    else:
        raise ValueError("Unknown UI: %r" % (ui,))
    return module.run


def _fallback_chain(first: str) -> tuple[str, ...]:
    """Return *first* followed by the configured fallback chain."""
    seen: set[str] = set()
    chain: list[str] = []
    for name in (first,) + FALLBACK_CHAIN.get(first, ("tk",)):
        if name not in seen:
            seen.add(name)
            chain.append(name)
    return tuple(chain)


def _log(message: str, debug: bool = False) -> None:
    """Append a line to the launcher log (best-effort)."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass
    if debug:
        sys.stderr.write("[sdlyt] %s\n" % message)


def _run_smoke_test(runner, settings: core.settings.Settings) -> None:
    """Run *runner* for about two seconds, then exit."""
    import threading

    thread_holder: dict[str, object] = {}

    def target() -> None:
        try:
            runner(settings)
        except SystemExit:
            pass
        except Exception:
            thread_holder["error"] = traceback.format_exc()

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    time.sleep(2.0)
    if "error" in thread_holder:
        sys.stderr.write(str(thread_holder["error"]))
        raise SystemExit(1)
    sys.exit(0)


def main(argv: list[str] | None = None) -> int:
    """Entry point used by ``sdlyt.py`` and ``python -m sdlyt``."""
    args = _parse_args(argv)

    if args.version:
        from . import __version__

        print("Super Duper Lite YT %s" % __version__)
        return 0

    if args.selftest:
        from .core import downloads_format

        _, failed = downloads_format.selftest()
        return 0 if failed == 0 else 1

    if args.selftest_progress:
        from .core import downloads_selftest

        _, failed = downloads_selftest.selftest_progress()
        return 0 if failed == 0 else 1

    settings = core.settings.Settings()
    first = _resolve_ui(settings, args.ui)

    last_reason = ""
    for candidate in _fallback_chain(first):
        if not core.system_profile.ui_supported(candidate):
            _log("skip %r: not supported" % candidate, args.debug)
            continue

        try:
            runner = _load_runner(candidate)
            if args.smoke_test:
                _run_smoke_test(runner, settings)
            runner(settings)
            return 0
        except SystemExit:
            raise
        except Exception:
            tb = traceback.format_exc(limit=4)
            last_reason = tb.strip().splitlines()[-1] if tb.strip() else "unknown error"
            _log("UI %r failed to start:\n%s" % (candidate, tb), args.debug)
            try:
                sys.stderr.write(
                    "[sdlyt] UI %r failed to start: %s\n" % (candidate, last_reason)
                )
            except Exception:
                pass
            if args.no_fallback:
                sys.stderr.write(traceback.format_exc())
                return 1
            continue

    sys.stderr.write("[sdlyt] No UI could be loaded. Last error: %s\n" % last_reason)
    _log("no UI could be loaded: %s" % last_reason, args.debug)
    return 1


if __name__ == "__main__":
    sys.exit(main())
