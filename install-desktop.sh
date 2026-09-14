#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
APPDIR="$(pwd)"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/funkgateway-ui.desktop"

mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=FunkGateway UI
Comment=Linux Radio Gateway mit Audio-VOX/PTT
Exec=$APPDIR/start.sh
Path=$APPDIR
Icon=$APPDIR/funkgateway.png
Terminal=false
Categories=AudioVideo;Network;HamRadio;
StartupNotify=true
EOF

chmod +x "$DESKTOP_FILE"
echo "Menueeintrag installiert:"
echo "  $DESKTOP_FILE"
