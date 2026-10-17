#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ -x .venv/bin/python ]]; then
    # Neue optionale Laufzeit-Abhängigkeiten nach Updates ergänzen.
    # Ein Fehler hier blockiert den Start nicht; FunkGateway fällt dann auf
    # den lokalen Hotkey zurück und zeigt den Grund im Status an.
    if ! .venv/bin/python -c 'import pynput' >/dev/null 2>&1; then
        echo "FunkGateway: pynput fehlt im vorhandenen venv – installiere System-Hotkey-Unterstützung ..."
        .venv/bin/python -m pip install "pynput>=1.7,<2" ||             echo "WARNUNG: pynput konnte nicht installiert werden. Systemweiter Hotkey bleibt deaktiviert."
    fi
    exec .venv/bin/python main.py "$@"
fi

echo "Virtuelle Python-Umgebung fehlt."
echo "Bitte zuerst ausfuehren:"
echo "  ./install.sh"
exit 1
