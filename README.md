# Super Duper Lite YT

A tiny, fast, touch-friendly YouTube client for Raspberry Pi and small
screens. Search, play, and download videos or audio using **yt-dlp** and
**mpv**. Three UIs share one backend: plain **Tk** (lightest), **CustomTkinter**
(modern, medium), and **PySide6** (premium, heaviest). The launcher picks the
best one for the machine and falls back automatically.

## Features

- Search YouTube and browse results with thumbnails.
- Play video or audio-only, with a sleep timer and volume control.
- Download video (up to 8K on capable hardware) or audio, with a live
  progress bar showing percent, speed and ETA.
- Queue with parallel downloads, cancel, retry, pause-on-restart.
- History, local library, cookies for age-restricted/private videos.
- Three UIs, auto-selected by RAM and CPU. Force any of them with
  `--ui=tk|ctk|pyside6` or `SDLYT_UI=...`.
- Works on Pi Zero (plain Tk, 512 MB) up to Pi 5 (PySide6, 4K).

## Install

### Installer script (recommended)

```bash
git clone https://github.com/GITHUB_USER/sdlyt.git
cd sdlyt
bash install.sh
```

The installer checks system packages, copies the app to
`~/.local/share/sdlyt/app`, creates a venv at `~/.local/share/sdlyt/venv`
with `--system-site-packages`, installs Python dependencies into the venv,
puts yt-dlp at `~/bin/yt-dlp`, writes `~/.local/bin/sdlyt`, and installs a
desktop entry + icon.

Options:

```
-y, --yes           don't ask before installing packages
--dry-run           print what would happen, change nothing
--update            update yt-dlp if it's already installed
--no-ctk            skip CustomTkinter
--no-pyside         skip PySide6 even on capable hardware
--no-launcher       don't create the app-menu entry
--launcher-only     only (re)install launcher + icon
--uninstall         remove the app, launcher and icon
-h, --help          show help
```

Skip PySide6 automatically: on 32-bit ARM (armv7l/armv6l) and on machines
under 1.9 GB RAM. The app falls back to CustomTkinter or Tk transparently.

### pip / pipx

```bash
pipx install "sdlyt[ui]"             # all three UIs, where wheels exist
# or:
python3 -m pip install --user "sdlyt[ctk]"   # just CustomTkinter + Tk
python3 -m pip install --user sdlyt          # Tk only
```

PySide6 is filtered by environment markers so it is silently skipped on
32-bit ARM. yt-dlp is installed separately (see below).

### Pi-Apps

The `Super Duper Lite YT/` folder is a Pi-Apps package. To test locally:

```bash
cp -r "Super Duper Lite YT" ~/pi-apps/apps/
~/pi-apps/manage install "Super Duper Lite YT"
~/pi-apps/manage uninstall "Super Duper Lite YT"
```

Before submitting to the Pi-Apps repo, edit `GITHUB_USER` and `REPO` in
`Super Duper Lite YT/install` and `Super Duper Lite YT/uninstall`, and
generate the required PNGs:

```bash
python3 tools/make_icons.py --pi-apps-dir "Super Duper Lite YT"
```

### Arch notes

The installer supports `pacman` and will pull `python`, `tk`, `python-pillow`,
`mpv`, `ffmpeg` from the official repos. For PySide6, `pip install ".[pyside6]"`
inside the venv pulls `PySide6` from PyPI (wheels for x86_64/aarch64 only).
Install a JavaScript runtime for full YouTube support:

```bash
sudo pacman -S --needed deno
```

PEP 668 on Arch: the installer uses a venv with `--system-site-packages`,
so `pip install` inside the venv is allowed without `--break-system-packages`.

### yt-dlp and a JS runtime

The app expects `yt-dlp` at `~/bin/yt-dlp`. The installer places it there.
For full YouTube access, yt-dlp needs a JavaScript runtime; install `deno`
or `node` if you don't already have one. The installer prints a hint if
neither is present but does not install it automatically.

## Running

```bash
sdlyt                            # auto-picks the UI
sdlyt --ui=tk                    # force plain Tk
sdlyt --ui=ctk                   # force CustomTkinter
sdlyt --ui=pyside6               # force PySide6
sdlyt --no-fallback --ui=pyside6 # debug a broken UI
sdlyt --smoke-test               # build the UI and exit in ~2s
sdlyt --selftest                 # validate format selectors
sdlyt --selftest-progress        # validate progress parser
```

`python sdlyt.py` still works from the source tree if the venv is active.

## Test checklist

```bash
bash -n install.sh
bash -n "Super Duper Lite YT/install"
bash -n "Super Duper Lite YT/uninstall"
shellcheck install.sh "Super Duper Lite YT/install" "Super Duper Lite YT/uninstall"
bash install.sh --dry-run
python sdlyt.py --selftest
python sdlyt.py --selftest-progress
```

Pi-Apps scripts (on a Raspberry Pi with `pi-apps` installed):

```bash
cp -r "Super Duper Lite YT" ~/pi-apps/apps/
~/pi-apps/manage install "Super Duper Lite YT"
~/pi-apps/manage uninstall "Super Duper Lite YT"
```

## License

MIT. Not affiliated with or endorsed by YouTube or Google.
