#!/usr/bin/env bash
# Super Duper Lite YT - standalone installer (package + venv, no git required)
#
# Installs system packages, copies the app to ~/.local/share/sdlyt/app,
# builds a venv with --system-site-packages, installs the package into it,
# installs yt-dlp at ~/bin/yt-dlp, writes ~/.local/bin/sdlyt, and adds a
# desktop entry + icon. Safe to re-run.
#
# Usage: bash install.sh [options]
#   -y, --yes           don't ask before installing packages
#   --dry-run           print what would happen, change nothing
#   --update            update yt-dlp if it's already installed
#   --no-ctk            skip CustomTkinter (plain Tk UI)
#   --no-pyside         skip PySide6 even on capable hardware
#   --no-launcher       don't create the app-menu entry
#   --launcher-only     only (re)install launcher + icon
#   --uninstall         remove the app, launcher and icon
#   -h, --help          show this help
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_HOME="$HOME/.local/share/sdlyt"
APP_DIR="$APP_HOME/app"
VENV_DIR="$APP_HOME/venv"
BIN_DIR="$HOME/.local/bin"
YTDLP="$HOME/bin/yt-dlp"
USER_DATA="$HOME/.sdlyt"
OUT_DIR="$HOME/Downloads/YT"

YES=0; WITH_CTK=1; WITH_PYSIDE=1; WITH_LAUNCHER=1
UPDATE_YTDLP=0; LAUNCHER_ONLY=0; UNINSTALL=0; DRY=0

usage() { awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; }

for a in "$@"; do
  case "$a" in
    -y|--yes)         YES=1 ;;
    --no-ctk)         WITH_CTK=0 ;;
    --no-pyside)      WITH_PYSIDE=0 ;;
    --no-launcher)    WITH_LAUNCHER=0 ;;
    --update)         UPDATE_YTDLP=1 ;;
    --launcher-only)  LAUNCHER_ONLY=1 ;;
    --uninstall)      UNINSTALL=1 ;;
    --dry-run)        DRY=1 ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "Unknown option: $a"; usage; exit 1 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }
say()  { printf '\n==> %s\n' "$*"; }
do_()  { if [ "$DRY" -eq 1 ]; then echo "    [dry-run] $*"; return 0; fi; "$@"; }
FAILED=()
LOG="$(mktemp 2>/dev/null || echo /tmp/sdlyt-install.log)"

# ---------------------------------------------------------------- package manager
PM=""
for pair in apt-get:apt dnf:dnf pacman:pacman apk:apk zypper:zypper; do
  if have "${pair%%:*}"; then PM="${pair##*:}"; break; fi
done

run_root() {
  if [ "$(id -u)" -eq 0 ]; then "$@"
  elif have sudo; then sudo "$@"
  else echo "Need root to run: $*"; return 1; fi
}

INDEX_DONE=0
refresh_index() {
  [ "$INDEX_DONE" -eq 1 ] && return 0
  INDEX_DONE=1
  case "$PM" in
    apt)    run_root env DEBIAN_FRONTEND=noninteractive apt-get update ;;
    apk)    run_root apk update ;;
    zypper) run_root zypper --non-interactive refresh ;;
    *)      true ;;
  esac
}

pm_install() {
  case "$PM" in
    apt)    run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
    dnf)    run_root dnf install -y "$@" ;;
    pacman) run_root pacman -S --needed --noconfirm "$@" ;;
    apk)    run_root apk add "$@" ;;
    zypper) run_root zypper --non-interactive install "$@" ;;
    *)      return 1 ;;
  esac
}

pkg_for() {
  case "$1:$PM" in
    python:pacman) echo python ;;
    python:*)      echo python3 ;;
    venv:apt)      echo python3-venv ;;
    venv:dnf)      echo python3-virtualenv ;;
    venv:pacman)   echo python-virtualenv ;;
    venv:apk)      echo py3-virtualenv ;;
    venv:zypper)   echo python3-virtualenv ;;
    tk:apt|tk:zypper) echo python3-tk ;;
    tk:dnf)        echo python3-tkinter ;;
    tk:pacman)     echo tk ;;
    tk:apk)        echo py3-tkinter ;;
    pil:apt)       echo python3-pil ;;
    pil:dnf)       echo python3-pillow ;;
    pil:pacman)    echo python-pillow ;;
    pil:apk)       echo py3-pillow ;;
    pil:zypper)    echo python3-Pillow ;;
    pip:apt)       echo python3-pip ;;
    pip:dnf)       echo python3-pip ;;
    pip:pacman)    echo python-pip ;;
    pip:apk)       echo py3-pip ;;
    pip:zypper)    echo python3-pip ;;
    ffmpeg:dnf)    echo ffmpeg-free ;;
    *)             echo "$1" ;;
  esac
}

ensure() {
  local name="$1" test="$2" req="$3" pkg
  if eval "$test" >/dev/null 2>&1; then printf '  ok       %s\n' "$name"; return 0; fi
  if [ -z "$PM" ]; then
    printf '  MISSING  %s (no supported package manager, install it yourself)\n' "$name"
    [ "$req" = 1 ] && FAILED+=("$name"); return 1
  fi
  pkg="$(pkg_for "$name")"
  printf '  install  %s (%s)\n' "$name" "$pkg"
  if [ "$DRY" -eq 1 ]; then echo "    [dry-run] install package $pkg"; return 0; fi
  refresh_index >>"$LOG" 2>&1 || true
  if pm_install "$pkg" >>"$LOG" 2>&1; then
    printf '  done     %s\n' "$name"
  else
    printf '  FAILED   %s (see %s)\n' "$name" "$LOG"
    [ "$req" = 1 ] && FAILED+=("$name")
    [ "$req" = 0 ] && FAILED+=("$name (optional)")
    return 1
  fi
}

# ---------------------------------------------------------------- hardware checks
detect_pyside_ok() {
  local arch ram_mb=4096
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64|aarch64|arm64) : ;;
    *) echo "  skip     PySide6 (no wheels for $arch)"; return 1 ;;
  esac
  if [ -f /proc/meminfo ]; then
    ram_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  fi
  if [ "${ram_mb:-4096}" -lt 1900 ]; then
    echo "  skip     PySide6 (${ram_mb} MB RAM < 1900 MB, will use CustomTkinter or Tk)"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------- yt-dlp
ytdlp_asset() {
  if ls /lib/ld-musl-* /usr/lib/ld-musl-* >/dev/null 2>&1; then echo yt-dlp; return; fi
  case "$(uname -m)" in
    x86_64|amd64)  echo yt-dlp_linux ;;
    aarch64|arm64) echo yt-dlp_linux_aarch64 ;;
    armv7l|armv7)  echo yt-dlp_linux_armv7l ;;
    *)             echo yt-dlp ;;
  esac
}

download() {
  if have curl; then curl -fL --retry 3 -o "$2" "$1"
  elif have wget; then wget -q -O "$2" "$1"
  else python3 -c 'import sys,urllib.request as u; u.urlretrieve(sys.argv[1], sys.argv[2])' "$1" "$2"; fi
}

install_ytdlp() {
  mkdir -p "$(dirname "$YTDLP")"
  local tmp="$YTDLP.new" asset base="https://github.com/yt-dlp/yt-dlp/releases/latest/download"
  for asset in "$(ytdlp_asset)" yt-dlp; do
    if download "$base/$asset" "$tmp" >>"$LOG" 2>&1 && chmod +x "$tmp" && "$tmp" --version >/dev/null 2>&1; then
      mv "$tmp" "$YTDLP"; return 0
    fi
  done
  rm -f "$tmp"; return 1
}

# ---------------------------------------------------------------- launcher + icon
install_icon() {
  local ICONS="$HOME/.local/share/icons/hicolor" svg="$HERE/packaging/icons/sdlyt.svg"
  if [ "$DRY" -eq 1 ]; then echo "    [dry-run] write icon to $ICONS"; return 0; fi
  mkdir -p "$ICONS/scalable/apps" "$ICONS/256x256/apps"
  if [ -f "$svg" ]; then
    cp "$svg" "$ICONS/scalable/apps/sdlyt.svg"
  fi
  if [ -x "$VENV_DIR/bin/python" ] && "$VENV_DIR/bin/python" -c "import PIL" >/dev/null 2>&1; then
    "$VENV_DIR/bin/python" "$HERE/tools/make_icons.py" \
        --png "$ICONS/256x256/apps/sdlyt.png" --size 256 >/dev/null 2>&1 || true
  fi
}

install_launcher_script() {
  if [ "$DRY" -eq 1 ]; then echo "    [dry-run] write $BIN_DIR/sdlyt"; return 0; fi
  mkdir -p "$BIN_DIR"
  cat > "$BIN_DIR/sdlyt" <<EOF
#!/bin/sh
exec "$VENV_DIR/bin/python" -m sdlyt "\$@"
EOF
  chmod 755 "$BIN_DIR/sdlyt"
}

install_desktop_entry() {
  local APPS="$HOME/.local/share/applications"
  if [ "$DRY" -eq 1 ]; then echo "    [dry-run] write launcher to $APPS"; return 0; fi
  mkdir -p "$APPS"
  install_icon
  cat > "$APPS/sdlyt.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Super Duper Lite YT
GenericName=YouTube player and downloader
Comment=Search, play and download YouTube videos
Exec=$BIN_DIR/sdlyt
Icon=sdlyt
StartupWMClass=Sdlyt
Terminal=false
Categories=AudioVideo;Video;Player;Network;
Keywords=youtube;video;music;download;mpv;
StartupNotify=false
DESK
  chmod 644 "$APPS/sdlyt.desktop"
  have update-desktop-database && update-desktop-database "$APPS" >/dev/null 2>&1 || true
  have gtk-update-icon-cache && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------- uninstall
uninstall_app() {
  say "Uninstalling Super Duper Lite YT"
  do_ rm -rf "$APP_HOME"
  do_ rm -f "$BIN_DIR/sdlyt" \
            "$HOME/.local/share/applications/sdlyt.desktop" \
            "$HOME/.local/share/icons/hicolor/scalable/apps/sdlyt.svg" \
            "$HOME/.local/share/icons/hicolor/256x256/apps/sdlyt.png"
  have update-desktop-database && update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
  have gtk-update-icon-cache && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  echo "  removed: $APP_HOME, ~/.local/bin/sdlyt, desktop entry, icon"
  if [ -d "$USER_DATA" ] || [ -d "$OUT_DIR" ]; then
    if [ "$YES" -eq 1 ]; then
      rm -rf "$USER_DATA" "$OUT_DIR"
      echo "  removed user data: $USER_DATA, $OUT_DIR"
    elif [ -t 0 ]; then
      read -rp "  Also delete settings, history and downloads? [y/N] " ans
      case "${ans:-n}" in
        y|Y) rm -rf "$USER_DATA" "$OUT_DIR"; echo "  removed user data" ;;
        *)   echo "  kept user data in $USER_DATA and $OUT_DIR" ;;
      esac
    else
      echo "  kept user data in $USER_DATA and $OUT_DIR (re-run with --yes to delete)"
    fi
  fi
  echo "  yt-dlp in ~/bin was left in place (may be shared with other tools)."
  echo "  Done."
}

# ---------------------------------------------------------------- main
if [ "$UNINSTALL" -eq 1 ]; then
  uninstall_app
  exit 0
fi

if [ "$LAUNCHER_ONLY" -eq 1 ]; then
  say "Installing app-menu launcher"
  install_launcher_script
  install_desktop_entry && echo "  done. Restart your launcher if it doesn't appear immediately."
  exit 0
fi

say "Super Duper Lite YT installer"
echo "  package manager: ${PM:-none found}"
echo "  architecture:    $(uname -m)"
if [ -n "$PM" ] && [ "$(id -u)" -ne 0 ] && ! have sudo; then
  echo "  note: not root and no sudo - system packages can't be installed."
fi
if [ "$YES" -eq 0 ] && [ "$DRY" -eq 0 ] && [ -t 0 ]; then
  read -rp "Install missing packages now? [Y/n] " ans
  case "${ans:-y}" in n|N) echo "Cancelled."; exit 0 ;; esac
fi

say "App source"
if [ ! -f "$HERE/sdlyt.py" ] || [ ! -d "$HERE/sdlyt" ]; then
  echo "  FAILED   sdlyt.py or sdlyt/ package missing next to install.sh"
  echo "           Expected: $HERE/sdlyt.py and $HERE/sdlyt/"
  exit 1
fi
echo "  ok       $HERE/sdlyt.py and $HERE/sdlyt/"

say "System packages"
ensure python "have python3" 1
ensure venv   "python3 -m venv --help >/dev/null 2>&1" 1
ensure tk     "python3 -c 'import tkinter'" 1
ensure mpv    "have mpv" 1
ensure ffmpeg "have ffmpeg" 1
ensure pil    "python3 -c 'import PIL'" 0
ensure curl   "have curl || have wget" 0

say "Hardware capability check"
PYSIDE_OK=0
if [ "$WITH_PYSIDE" -eq 1 ]; then
  if detect_pyside_ok; then PYSIDE_OK=1; echo "  ok       PySide6 will be installed"; fi
else
  echo "  skip     PySide6 (--no-pyside)"
fi

say "JavaScript runtime (for yt-dlp)"
JS_FOUND=""
for cand in deno node; do
  if have "$cand"; then JS_FOUND="$cand"; break; fi
done
if [ -n "$JS_FOUND" ]; then
  echo "  ok       $JS_FOUND found ($(command -v "$JS_FOUND"))"
else
  echo "  WARN     no JS runtime found. yt-dlp needs one for full YouTube access."
  case "$PM" in
    pacman) echo "           Install with: sudo pacman -S --needed deno" ;;
    apt)    echo "           Install with: curl -fsSL https://deno.land/install.sh | sh  (or apt install nodejs)" ;;
    dnf)    echo "           Install with: sudo dnf install -y deno  (or nodejs)" ;;
    apk)    echo "           Install with: sudo apk add nodejs" ;;
    zypper) echo "           Install with: sudo zypper install nodejs" ;;
    *)      echo "           Install deno or node from your distro or https://deno.land/" ;;
  esac
fi

say "Copying app to $APP_DIR"
if [ "$DRY" -eq 0 ]; then
  mkdir -p "$APP_HOME"
  rm -rf "$APP_DIR"
  mkdir -p "$APP_DIR"
  cp -a "$HERE/sdlyt" "$APP_DIR/"
  cp -a "$HERE/sdlyt.py" "$APP_DIR/"
  cp -a "$HERE/pyproject.toml" "$APP_DIR/" 2>/dev/null || true
  cp -a "$HERE/requirements.txt" "$APP_DIR/" 2>/dev/null || true
  cp -a "$HERE/README.md" "$APP_DIR/" 2>/dev/null || true
  cp -a "$HERE/tools" "$APP_DIR/" 2>/dev/null || true
  cp -a "$HERE/packaging" "$APP_DIR/" 2>/dev/null || true
  echo "  done"
else
  echo "    [dry-run] copy sdlyt/, sdlyt.py, pyproject.toml, tools/, packaging/ to $APP_DIR"
fi

say "Creating virtual environment"
if [ "$DRY" -eq 0 ]; then
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    python3 -m venv --system-site-packages "$VENV_DIR" >>"$LOG" 2>&1 || {
      echo "  FAILED   venv creation (see $LOG)"; FAILED+=("venv"); }
  fi
  if [ -x "$VENV_DIR/bin/python" ]; then
    "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip >>"$LOG" 2>&1 || true
    echo "  done     $VENV_DIR"
  fi
else
  echo "    [dry-run] python3 -m venv --system-site-packages $VENV_DIR"
fi

say "Installing Python packages into the venv"
if [ "$DRY" -eq 0 ] && [ -x "$VENV_DIR/bin/python" ]; then
  PIP="$VENV_DIR/bin/python -m pip install --quiet"
  cd "$APP_DIR" || exit 1
  # Base + CustomTkinter first
  if $PIP ".[ctk]" >>"$LOG" 2>&1; then
    echo "  done     base + customtkinter"
  else
    echo "  WARN     base + customtkinter failed, retrying base only (see $LOG)"
    if $PIP "." >>"$LOG" 2>&1; then
      echo "  done     base"
    else
      echo "  FAILED   base install (see $LOG)"; FAILED+=("pip install")
    fi
  fi
  if [ "$PYSIDE_OK" -eq 1 ]; then
    if $PIP ".[pyside6]" >>"$LOG" 2>&1; then
      echo "  done     pyside6"
    else
      echo "  skip     pyside6 (pip failed, app will use CustomTkinter or Tk; see $LOG)"
      FAILED+=("pyside6 (optional)")
    fi
  fi
  cd - >/dev/null || true
else
  echo "    [dry-run] pip install .[ctk] (and .[pyside6] if capable)"
fi

say "yt-dlp"
if [ -x "$YTDLP" ]; then
  if [ "$UPDATE_YTDLP" -eq 1 ]; then
    echo "  updating"; do_ "$YTDLP" -U || FAILED+=("yt-dlp update (optional)")
  else
    echo "  ok       yt-dlp $("$YTDLP" --version 2>/dev/null)"
  fi
elif [ "$DRY" -eq 1 ]; then
  echo "  [dry-run] download $(ytdlp_asset) to $YTDLP"
else
  echo "  downloading $(ytdlp_asset)"
  if install_ytdlp; then echo "  done     yt-dlp $("$YTDLP" --version 2>/dev/null)"
  else echo "  FAILED   yt-dlp (check your internet connection)"; FAILED+=("yt-dlp"); fi
fi

say "Launcher script"
install_launcher_script && echo "  done     $BIN_DIR/sdlyt"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "  note     $BIN_DIR is not on PATH yet. Open a new shell or add:"
     echo '             export PATH="$HOME/.local/bin:$PATH"' ;;
esac

if [ "$WITH_LAUNCHER" -eq 1 ]; then
  say "App-menu launcher and icon"
  install_desktop_entry && echo "  done     look for Super Duper Lite YT in your app menu"
fi

say "Verifying"
if [ "$DRY" -eq 0 ] && [ -x "$VENV_DIR/bin/python" ]; then
  "$VENV_DIR/bin/python" -m sdlyt --version 2>/dev/null \
    && echo "  ok       sdlyt --version works" \
    || { echo "  FAILED   sdlyt --version (see $LOG)"; FAILED+=("entry point"); }
  [ -x "$YTDLP" ] && echo "  ok       ~/bin/yt-dlp is executable"
  have mpv     && echo "  ok       mpv found"
  have ffmpeg  && echo "  ok       ffmpeg found"
  "$VENV_DIR/bin/python" -c "import PIL" 2>/dev/null && echo "  ok       Pillow importable"
  "$VENV_DIR/bin/python" -c "import customtkinter" 2>/dev/null \
    && echo "  ok       CustomTkinter importable" \
    || echo "  info     CustomTkinter not available (plain Tk UI)"
  if [ "$PYSIDE_OK" -eq 1 ]; then
    "$VENV_DIR/bin/python" -c "import PySide6" 2>/dev/null \
      && echo "  ok       PySide6 importable (modern UI enabled)" \
      || echo "  info     PySide6 not available (will use CustomTkinter or Tk)"
  fi
fi

say "Summary"
if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "  All set."
  echo "  Run:  sdlyt     (or: $BIN_DIR/sdlyt, or via your app menu)"
  echo ""
  echo "  Low-RAM / 32-bit-ARM tip:"
  echo "    On Pi Zero (512 MB) or ARMv7 the app auto-uses plain Tk and skips"
  echo "    thumbnails. Force a heavier UI with:  sdlyt --ui=ctk  (or --ui=pyside6)"
else
  echo "  Finished with notes: ${FAILED[*]}"
  echo "  Details: $LOG"
  [ "$PM" = dnf ] && echo "  Fedora tip: mpv comes from RPM Fusion (https://rpmfusion.org)."
  echo "  You can install/update tools later from Settings -> Tools in the app."
  for f in "${FAILED[@]}"; do
    case "$f" in *"(optional)"*) ;; *) exit 1 ;; esac
  done
fi
exit 0
