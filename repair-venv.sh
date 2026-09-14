#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! /usr/bin/python3 -c 'import Ice; print(Ice.stringVersion())' >/dev/null 2>&1; then
    echo "FEHLER: System-Python kann Python-Ice nicht laden." >&2
    exit 2
fi

stamp="$(date +%Y%m%d-%H%M%S)"
if [[ -d .venv ]]; then
    backup=".venv.backup-${stamp}"
    echo "Sichere vorhandene .venv nach ${backup}"
    mv .venv "${backup}"
fi

cleanup_failed() {
    [[ -d .venv ]] && rm -rf .venv
}
trap cleanup_failed ERR

echo "Erstelle .venv mit --system-site-packages ..."
/usr/bin/python3 -m venv --system-site-packages .venv

echo "Installiere FunkGateway-Pythonpakete ..."
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install     "PySide6>=6.5,<6.9"     "sounddevice>=0.4,<0.6"     "soundfile>=0.12,<0.14"     "pyserial>=3.5,<4"

if ! .venv/bin/python -c 'import Ice; print(Ice.stringVersion())' >/dev/null 2>&1; then
    if .venv/bin/python -m pip show numpy >/dev/null 2>&1; then
        echo "Ice-Import scheitert; entferne lokale venv-NumPy-Version ..."
        .venv/bin/python -m pip uninstall -y numpy || true
    fi
fi

.venv/bin/python - <<'PY'
from PySide6.QtWidgets import QApplication
import serial, sounddevice, soundfile
import Ice
print("GUI + Audio + pyserial: OK")
print("Python-Ice:", Ice.stringVersion())
print("Ice-Modul:", Ice.__file__)
PY

trap - ERR
echo "venv-Reparatur erfolgreich."
