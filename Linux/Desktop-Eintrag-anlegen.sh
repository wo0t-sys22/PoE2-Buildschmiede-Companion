#!/bin/sh
# Adds "PoE2 Companion" to the application menu of the current user.
# Start: sh Desktop-Eintrag-anlegen.sh
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app="$here/app"
[ -d "$app" ] || app="$here/../app"
starter="$here/PoE2-Guide-starten.sh"
chmod +x "$here"/*.sh 2>/dev/null
target="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$target"
cat > "$target/poe2-companion.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PoE2 Companion
Comment=Buildschmiede Ingame Guide für Path of Exile 2
Exec=sh "$starter"
Path=$here
Icon=$app/web/images/buildschmiede-mark.png
Terminal=false
Categories=Game;Utility;
StartupWMClass=PoE2-Companion
EOF
chmod +x "$target/poe2-companion.desktop" 2>/dev/null
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$target" 2>/dev/null
echo "Menüeintrag angelegt: $target/poe2-companion.desktop"
echo "Der Companion erscheint im Anwendungsmenü unter \"PoE2 Companion\"."
