#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
APP_VERSION="0.6.23"

PM=""
if command -v apt-get >/dev/null 2>&1; then PM="apt"
elif command -v dnf >/dev/null 2>&1; then PM="dnf"
elif command -v pacman >/dev/null 2>&1; then PM="pacman"
elif command -v zypper >/dev/null 2>&1; then PM="zypper"
fi

install_each() {
  local pkg
  for pkg in "$@"; do
    case "$PM" in
      dnf) sudo dnf install -y "$pkg" || echo "WARNUNG: Paket $pkg konnte nicht installiert werden." ;;
      pacman) sudo pacman -S --needed --noconfirm "$pkg" || echo "WARNUNG: Paket $pkg konnte nicht installiert werden." ;;
      zypper) sudo zypper --non-interactive install "$pkg" || echo "WARNUNG: Paket $pkg konnte nicht installiert werden." ;;
    esac
  done
}

case "$PM" in
 apt)
   sudo apt-get update
   sudo apt-get install -y python3 python3-venv python3-pip python3-serial      pulseaudio-utils libportaudio2 libsndfile1 libgsm1 libopus0 libgl1 libegl1      libx11-6 libxtst6 libxext6 libxkbcommon-x11-0      libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1      libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 qrencode
   sudo apt-get install -y openssh-client gpiod python3-libgpiod python3-zeroc-ice zeroc-ice-slice || true
   ;;
 dnf)
   install_each python3 python3-pip python3-pyserial pulseaudio-utils portaudio libsndfile gsm opus      libX11 libXtst libXext libxkbcommon-x11 qrencode openssh-clients
   ;;
 pacman)
   sudo pacman -Sy --noconfirm
   install_each python python-pip python-pyserial libpulse portaudio libsndfile gsm opus      libx11 libxtst libxext libxkbcommon-x11 qrencode openssh
   ;;
 zypper)
   sudo zypper --non-interactive refresh || true
   install_each python3 python3-pip python3-pyserial libpulse0 libportaudio2 libsndfile1 libgsm1 libopus0      libX11-6 libXtst6 libXext6 libxkbcommon-x11-0 qrencode openssh
   ;;
 *)
   echo "WARNUNG: Kein unterstützter Paketmanager erkannt."
   echo "Systempakete bitte manuell installieren: Python3/venv/pip, pyserial, pactl/parec/pacat/paplay, PortAudio, libsndfile, libgsm, X11/XTest, Qt/XCB und qrencode."
   ;;
esac

command -v python3 >/dev/null 2>&1 || { echo "FEHLER: python3 fehlt"; exit 1; }
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "FEHLER: Python-venv fehlt. Bitte das venv-Paket deiner Distribution installieren."
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv --system-site-packages .venv
fi

.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install   "PySide6>=6.5,<6.9"   "sounddevice>=0.4,<0.6"   "soundfile>=0.12,<0.14"   "pyserial>=3.5,<4"   "pynput>=1.7,<2"   "opuslib==3.0.1"   "protobuf==3.20.3"   "cryptography>=43,<46"   "git+https://github.com/azlux/pymumble.git@8755c7d41b8f1f91402a6218c413121b64bdce33"

.venv/bin/python - <<'PY'
import serial, sounddevice, soundfile, pynput, opuslib, pymumble_py3, cryptography
from PySide6.QtCore import __version__ as pyside_version
print("Python-Abhängigkeiten: OK")
print("PySide6:", pyside_version)
print("pynput:", getattr(pynput, "__version__", "installiert"))
print("pymumble_py3:", pymumble_py3.__file__)
print("cryptography:", cryptography.__version__)
PY

for cmd in pactl parec pacat paplay; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "FEHLER: $cmd fehlt"; exit 1; }
done

chmod +x start.sh install-linux.sh install.sh install-desktop.sh repair-venv.sh
mkdir -p "$HOME/.config/funkgateway-ui"
echo "Installation abgeschlossen. Start: ./start.sh"
