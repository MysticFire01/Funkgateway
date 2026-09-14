#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
APP_VERSION="0.5.6.20"
echo "============================================================"
echo " FunkGateway UI ${APP_VERSION} - Generic Linux Installer"
echo "============================================================"
echo
PM=""
if command -v apt-get >/dev/null 2>&1; then PM="apt";
elif command -v dnf >/dev/null 2>&1; then PM="dnf";
elif command -v pacman >/dev/null 2>&1; then PM="pacman";
elif command -v zypper >/dev/null 2>&1; then PM="zypper"; fi

echo "Paketmanager: ${PM:-nicht automatisch erkannt}"
case "$PM" in
 apt)
   sudo apt-get update
   sudo apt-get install -y python3 python3-venv python3-pip python3-serial pulseaudio-utils libportaudio2 libsndfile1 libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0
   sudo apt-get install -y openssh-client gpiod python3-libgpiod || true
   sudo apt-get install -y python3-zeroc-ice zeroc-ice-slice || true
   ;;
 dnf)
   sudo dnf install -y python3 python3-pip python3-pyserial pulseaudio-utils portaudio libsndfile mesa-libGL mesa-libEGL libxkbcommon-x11 libxcb xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil openssh-clients libgpiod libgpiod-utils || true
   echo "ZeroC Ice ggf. distributionsspezifisch nachinstallieren."
   ;;
 pacman)
   sudo pacman -Sy --needed --noconfirm python python-pip python-pyserial libpulse portaudio libsndfile libglvnd libxkbcommon-x11 libxcb xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil openssh libgpiod || true
   echo "ZeroC Ice ggf. distributionsspezifisch/AUR nachinstallieren."
   ;;
 zypper)
   sudo zypper --non-interactive install python3 python3-pip python3-pyserial libpulse0 libportaudio2 libsndfile1 Mesa-libGL1 Mesa-libEGL1 libxkbcommon-x11-0 libxcb1 openssh || true
   echo "ZeroC Ice/libgpiod ggf. distributionsspezifisch nachinstallieren."
   ;;
 *)
   echo "Installiere manuell: Python3+venv+pip, pyserial, pactl/parec/pacat/paplay, PortAudio, libsndfile, Qt/XCB-Laufzeitbibliotheken; optional OpenSSH/ZeroC Ice/libgpiod."
   ;;
esac

command -v python3 >/dev/null 2>&1 || { echo "FEHLER: python3 fehlt"; exit 1; }
python3 -m venv --help >/dev/null 2>&1 || { echo "FEHLER: Python venv fehlt"; exit 1; }

if [[ ! -d .venv ]]; then
  python3 -m venv --system-site-packages .venv
elif /usr/bin/python3 -c 'import Ice' >/dev/null 2>&1 && ! .venv/bin/python -c 'import Ice' >/dev/null 2>&1; then
  ./repair-venv.sh
fi
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install "PySide6>=6.5,<6.9" "sounddevice>=0.4,<0.6" "soundfile>=0.12,<0.14" "pyserial>=3.5,<4"

for cmd in pactl parec pacat paplay; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "FEHLER: $cmd fehlt"; exit 1; }
done
chmod +x start.sh install-linux.sh install.sh install-desktop.sh repair-venv.sh
mkdir -p "$HOME/.config/funkgateway-ui"
echo "Installation abgeschlossen. Start: ./start.sh"
echo "Mumble/Ice: Integrationen -> Mumble -> Mumble-Komponenten installieren / reparieren"
