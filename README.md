# PoE2 Ingame Guide v.0.19.0 · Buildschmiede Companion

Ein Overlay für **Path of Exile 2** mit Kampagnenguide, Boss-Guides, Build-Import, Lexikon und Atlas, direkt über dem Spiel. Die Texte gibt es in Deutsch, Englisch und Hybrid. Grundlage ist Patch 0.5.5f.

Die Online-Guides findest du auf [buildschmiede.de](https://buildschmiede.de/).

## Download

Die fertigen Pakete liegen unter **[Releases](../../releases)**:

| System | Datei |
| --- | --- |
| Windows 10/11 (portabel) | `PoE2-Companion-<Version>-Windows.zip` |
| Windows 10/11 (Setup, unsigniert) | `PoE2-Companion-<Version>-Setup.exe` |
| Linux (X11 oder XWayland) | `PoE2-Companion-<Version>-Linux.tar.gz` |

Jedes Release enthält eine `SHA256SUMS.txt` mit den Prüfsummen.

## Start

**Windows (portabel)**
1. ZIP entpacken (Rechtsklick → „Alle extrahieren“).
2. Einmal `Voraussetzungen installieren.cmd` öffnen. Das Skript prüft Python 3.10+ mit Tcl/Tk und installiert es bei Bedarf für dein Benutzerkonto.
3. `PoE2 Guide starten.cmd` öffnen.

**Windows (Setup)**

Das Setup installiert den Companion für dein Benutzerkonto und bringt Python und Tcl/Tk mit.

**Linux**
1. Archiv entpacken.
2. Python 3.10+ mit Tkinter installieren, z. B. `sudo apt install python3 python3-tk` oder `sudo pacman -S python tk`.
3. `sh PoE2-Guide-starten.sh` ausführen. `sh Desktop-Eintrag-anlegen.sh` legt optional einen Menüeintrag an.

> Die Linux-Fassung ist noch nicht auf echter Hardware getestet. Rückmeldungen sind willkommen.

Aus diesem Repository startest du den Companion genauso: unter Windows über `Windows\PoE2 Guide starten.cmd`, unter Linux über `sh Linux/PoE2-Guide-starten.sh`. Die Starter finden den gemeinsamen Ordner `app/` automatisch.

## Bedienung

| Taste | Funktion |
| --- | --- |
| F8 | Overlay ein- oder ausblenden |
| F9 | Spielmodus oder Bearbeiten |
| F10 | Guide beenden |
| F6 / F7 | Timer starten und pausieren / zurücksetzen |

Die ausführliche Anleitung steht in [app/README.md](app/README.md). Kurzfassungen liegen in [Windows/LIES MICH.txt](Windows/LIES%20MICH.txt) und [Linux/LIES MICH.txt](Linux/LIES%20MICH.txt).

## Aufbau

| Ordner | Inhalt |
| --- | --- |
| `app/` | Programm und Daten für beide Systeme. `app/plattform/` enthält das Fenster-Backend für Windows und Linux. |
| `Windows/` | Starter, Python-Prüfung und Kurzanleitung für Windows |
| `Linux/` | Starter, Menüeintrag und Kurzanleitung für Linux |

Persönliche Einstellungen und Fortschritt speichert der Companion lokal in `app/userdata/`. Dieser Ordner wird nicht versioniert.

## Rechtliches

© Buildschmiede. Alle Rechte am eigenen Code und an den eigenen Texten vorbehalten. Der Quellcode ist zur Ansicht veröffentlicht. Für Nutzung, Änderung oder Weitergabe außerhalb des normalen Gebrauchs des Tools bitte vorher anfragen.

Spieldaten, Grafiken und weitere Inhalte stammen von Dritten. Quellen und Lizenzen stehen in [DRITTANBIETER.md](DRITTANBIETER.md).

Dies ist ein Fanprojekt und steht in keiner Verbindung zu Grinding Gear Games. Path of Exile ist eine Marke von Grinding Gear Games.
