#!/usr/bin/env bash
# Yawn Kiosk on the Raspberry Pi: install missing packages, check the setup, then run.
#
#   deploy/run-pi.sh                   run the player fullscreen with the HMMD sensor and --fast-input
#   deploy/run-pi.sh --hud --windowed  extra arguments go to the player (e.g. --sensor keyboard)
#   deploy/run-pi.sh sensor-test       live sensor readings instead of the player (docs/wiring.md)
#   deploy/run-pi.sh check             install and check only
#
# Everything comes from apt (no pip, no venv): the player needs pygame, pyserial and
# the ffmpeg command. Safe to run repeatedly; apt only runs when something is missing.
# It never edits boot configuration: if the serial port isn't set up it prints the steps.

set -euo pipefail

readonly APT_PACKAGES=(python3-pygame python3-serial ffmpeg)
readonly MIN_PYTHON="3.11"
readonly PI5_UART="/dev/ttyAMA0"
readonly OTHER_PI_UART="/dev/serial0"
readonly MODEL_FILE="/proc/device-tree/model"

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

info() { echo "[run-pi]: $*"; }
fail() { echo "[run-pi]: ERROR: $*" >&2; exit 1; }

command="run"
case "${1:-}" in
  run | sensor-test | check) command="$1"; shift ;;
esac

# --- Hardware ---------------------------------------------------------------
model="$( { tr -d '\0' < "$MODEL_FILE"; } 2>/dev/null || true)"
if [[ "$model" != Raspberry\ Pi* ]]; then
  info "WARNING: this doesn't look like a Raspberry Pi (model: '${model:-unknown}'); continuing anyway"
else
  info "hardware: $model"
fi

# --- Packages ---------------------------------------------------------------
missing=()
for package in "${APT_PACKAGES[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed"; then
    missing+=("$package")
  fi
done
if ((${#missing[@]})); then
  info "installing missing packages: ${missing[*]} (needs sudo)"
  sudo apt-get update
  sudo apt-get install -y "${missing[@]}"
else
  info "packages: all installed (${APT_PACKAGES[*]})"
fi

python3 -c "import sys; sys.exit(sys.version_info < tuple(map(int, '$MIN_PYTHON'.split('.'))))" \
  || fail "Python $MIN_PYTHON or newer is needed (found $(python3 --version 2>&1)); use Raspberry Pi OS Bookworm or later"
PYGAME_HIDE_SUPPORT_PROMPT=1 python3 -c "import pygame, serial" 2>/dev/null \
  || fail "python3 can't import pygame and serial even though the packages are installed"
command -v ffmpeg >/dev/null || fail "the ffmpeg command is not on PATH"

# --- Sensor serial port -----------------------------------------------------
# The player's --sensor defaults to hmmd here; the last --sensor argument wins, as in argparse.
sensor="hmmd"
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[$i]}" in
    --sensor) sensor="${args[$((i + 1))]:-}" ;;
    --sensor=*) sensor="${args[$i]#--sensor=}" ;;
  esac
done

if [[ "$command" == "sensor-test" || "$sensor" == "hmmd" ]]; then
  if [[ "$model" == *"Raspberry Pi 5"* ]]; then uart="$PI5_UART"; else uart="$OTHER_PI_UART"; fi
  if [[ ! -e "$uart" ]]; then
    fail "serial port $uart does not exist. One-time setup (docs/wiring.md section 4):
  1. sudo nano /boot/firmware/config.txt   and add under [all]:   dtoverlay=uart0-pi5
  2. sudo raspi-config -> Interface Options -> Serial Port -> login shell: No, hardware: Yes
  3. sudo reboot"
  fi
  if [[ ! -r "$uart" || ! -w "$uart" ]]; then
    fail "no permission to use $uart. Run:  sudo usermod -aG dialout $(id -un)   then log out and back in"
  fi
  info "sensor: serial port $uart is ready"
fi

# --- Video assets -----------------------------------------------------------
if [[ "$command" != "sensor-test" ]]; then
  if [[ ! -f build/manifest.json || ! -d build/clips ]]; then
    fail "build/manifest.json or build/clips/ is missing. The manifest comes with git (git pull); the clips are copied from the PC's repo root:
  rsync -av build/clips <user>@<pi-host>:$repo_dir/build/"
  fi
  info "video: build/manifest.json and build/clips/ found"
fi

if [[ "$command" == "check" ]]; then
  info "all checks passed"
  exit 0
fi

if [[ "$command" == "sensor-test" ]]; then
  exec python3 -m tools.sensor_test "$@"
fi

# --- Display ----------------------------------------------------------------
# From the desktop terminal the session variables are already set. Over SSH, borrow the
# desktop's Wayland session if one is running; with no desktop at all (OS Lite) draw
# straight to the screen with KMS/DRM.
if [[ -z "${SDL_VIDEODRIVER:-}" && -z "${WAYLAND_DISPLAY:-}" && -z "${DISPLAY:-}" ]]; then
  runtime_dir="/run/user/$(id -u)"
  wayland_socket="$(find "$runtime_dir" -maxdepth 1 -name 'wayland-*' -type s 2>/dev/null | head -n 1 || true)"
  if [[ -n "$wayland_socket" ]]; then
    export XDG_RUNTIME_DIR="$runtime_dir"
    WAYLAND_DISPLAY="$(basename "$wayland_socket")"
    export WAYLAND_DISPLAY
    export SDL_VIDEODRIVER="wayland"
    info "display: desktop Wayland session $WAYLAND_DISPLAY"
  else
    export SDL_VIDEODRIVER="kmsdrm"
    info "display: no desktop session found, using KMS/DRM directly"
  fi
fi

info "starting the player (Q or Esc quits)"
exec python3 -m player.main --sensor hmmd --fast-input "$@"
