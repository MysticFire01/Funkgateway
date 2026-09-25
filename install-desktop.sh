#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

APPDIR="$(pwd)"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_ID="funkgateway-ui.desktop"
DESKTOP_FILE="$DESKTOP_DIR/$DESKTOP_ID"

mkdir -p "$DESKTOP_DIR"

echo "Bereinige alte FunkGateway-Starter ..."

removed=0
while IFS= read -r -d '' oldfile; do
    [[ "$oldfile" == "$DESKTOP_FILE" ]] && continue

    # Nur eindeutig zu FunkGateway gehörende lokale Starter entfernen.
    if grep -Eqi \
        '^(Name=.*FunkGateway|Exec=.*FunkGateway-UI-[0-9]|Path=.*FunkGateway-UI-[0-9]|Icon=.*FunkGateway-UI-[0-9])' \
        "$oldfile"; then
        echo "  Entferne alten Starter: $oldfile"
        rm -f -- "$oldfile"
        removed=$((removed + 1))
    fi
done < <(find "$DESKTOP_DIR" -maxdepth 1 -type f -name '*.desktop' -print0)

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

# GNOME-Favoriten: vorhandenen alten FunkGateway-Eintrag auf die stabile
# Desktop-ID umbiegen, statt einen zweiten Eintrag anzulegen.
if command -v gsettings >/dev/null 2>&1 \
   && gsettings writable org.gnome.shell favorite-apps >/dev/null 2>&1; then
    current="$(gsettings get org.gnome.shell favorite-apps 2>/dev/null || true)"
    if [[ -n "$current" ]]; then
        normalized="$(
            python3 - "$DESKTOP_ID" "$current" <<'PY'
import ast
import sys

canonical=sys.argv[1]
raw=sys.argv[2]

try:
    favs=ast.literal_eval(raw)
except Exception:
    print(raw)
    raise SystemExit(0)

if not isinstance(favs,list):
    print(raw)
    raise SystemExit(0)

result=[]
inserted=False
for item in favs:
    if not isinstance(item,str):
        continue
    if "funkgateway" in item.lower():
        if not inserted:
            result.append(canonical)
            inserted=True
        continue
    if item not in result:
        result.append(item)

print(repr(result))
PY
        )"
        if [[ -n "$normalized" && "$normalized" != "$current" ]]; then
            if gsettings set org.gnome.shell favorite-apps "$normalized"; then
                echo "  GNOME-Favorit auf $DESKTOP_ID aktualisiert."
            fi
        fi
    fi
fi

# Desktop-Datenbank neu einlesen, falls das Werkzeug vorhanden ist.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

echo
echo "Schnellstarter installiert/aktualisiert:"
echo "  $DESKTOP_FILE"
echo "  Ziel: $APPDIR"
if (( removed > 0 )); then
    echo "  Alte lokale FunkGateway-Starter entfernt: $removed"
fi
echo
echo "Falls GNOME noch ein altes Symbol zwischenspeichert, einmal ab- und wieder anmelden."
