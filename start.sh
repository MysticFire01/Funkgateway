#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ -x .venv/bin/python ]]; then
    exec .venv/bin/python main.py "$@"
fi

echo "Virtuelle Python-Umgebung fehlt."
echo "Bitte zuerst ausfuehren:"
echo "  ./install-ubuntu-24.04.sh"
exit 1
