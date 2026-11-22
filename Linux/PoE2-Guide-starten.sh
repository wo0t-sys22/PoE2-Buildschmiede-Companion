#!/bin/sh
# PoE2 Ingame Guide for Linux (X11 or XWayland).
#
# Start:   sh PoE2-Guide-starten.sh      (works even without the executable flag)
#    or:   ./PoE2-Guide-starten.sh
# Option:  POE2_SCALE=1.5 sh PoE2-Guide-starten.sh   (fixed scale for HiDPI or mixed-DPI setups)
#
# Started by double-click there is no terminal: errors then appear as a dialog
# (zenity, kdialog, notify-send or xmessage) and in app/userdata/start.log.

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Release: app/ next to this starter. Working copy: Produktiv/Linux/ next to Produktiv/app/.
app="$here/app"
[ -f "$app/poe2_standalone_overlay.py" ] || app="$here/../app"

# Copies from Windows or VM shared folders lose the executable flag: restore it quietly.
chmod +x "$here"/*.sh 2>/dev/null

say() {
    # Message to the terminal, or as a dialog when started without one.
    if [ -t 1 ]; then
        printf '%s\n' "$1"
        return
    fi
    if command -v zenity >/dev/null 2>&1; then
        zenity --error --title="PoE2 Companion" --no-wrap --text="$1" 2>/dev/null
    elif command -v kdialog >/dev/null 2>&1; then
        kdialog --title "PoE2 Companion" --error "$1" 2>/dev/null
    elif command -v notify-send >/dev/null 2>&1; then
        notify-send "PoE2 Companion" "$1" 2>/dev/null
    elif command -v xmessage >/dev/null 2>&1; then
        xmessage -center "$1" 2>/dev/null
    fi
    printf '%s\n' "$1" >&2
}

if [ ! -f "$app/poe2_standalone_overlay.py" ]; then
    say "Der Ordner \"app\" fehlt neben dem Starter.
Das Archiv vollständig in einen eigenen Ordner entpacken und den Starter dort ausführen."
    exit 1
fi

python=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c "import sys, tkinter; assert sys.version_info >= (3, 10)" >/dev/null 2>&1; then
        python=$candidate
        break
    fi
done
if [ -z "$python" ]; then
    say "Python 3.10 oder neuer mit Tkinter fehlt.
Debian/Ubuntu: sudo apt install python3 python3-tk
Fedora: sudo dnf install python3 python3-tkinter
Arch/CachyOS: sudo pacman -S python tk"
    exit 1
fi

if [ -z "${DISPLAY:-}" ]; then
    say "Kein X11-Display gefunden.
Unter Wayland wird XWayland benötigt (bei KDE Plasma und GNOME Standard).
Über SSH oder in einer reinen Konsole startet der Guide nicht."
    exit 1
fi

mkdir -p "$app/userdata" 2>/dev/null
log="$app/userdata/start.log"
{
    printf '=== %s · %s · %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$("$python" --version 2>&1)" \
        "${XDG_SESSION_TYPE:-?} DISPLAY=$DISPLAY"
} >>"$log" 2>/dev/null

"$python" -B "$app/poe2_standalone_overlay.py" "$@" 2>>"$log"
status=$?
if [ "$status" -ne 0 ]; then
    say "Der Guide wurde mit Fehler $status beendet.
Details: $log
$(tail -n 8 "$log" 2>/dev/null)"
fi
exit "$status"
