# PoE2 Buildschmiede Companion

Der **Buildschmiede Companion** ist ein Overlay für Path of Exile 2. Es erkennt dein aktuelles Gebiet und bringt Kampagnen- und Boss-Guides, Build-Phasen, Lexikon und Atlas direkt ins Spiel. Crafting-Helfer, Affix-Suche und weitere Werkzeuge sind ebenfalls griffbereit.

Du entscheidest, was du sehen willst. Reiter, Schnellzugriffe und viele Guide-Elemente lassen sich einzeln ein- und ausblenden. Dazu kommen Themes, einstellbare Größe und Transparenz sowie kompakte und ausführliche Ansichten. Die Guides gibt es auf Deutsch, auf Englisch und im Hybridmodus mit deutschen Erklärungen und englischen Spielbegriffen.

Die aktuelle Beta **v.0.19.0** enthält den Datenstand von **Patch 0.5.5f**. Der Companion ist für PoE 2 **1.0** gedacht. Die neuen Inhalte pflegen wir schrittweise ein, sobald uns die Spieldaten vorliegen.

[Online-Guides auf buildschmiede.de](https://buildschmiede.de/)

## Download & Start

Die fertigen Pakete und ihre SHA-256-Prüfsummen findest du unter [**Releases**](https://github.com/wo0t-sys22/PoE2-Buildschmiede-Companion/releases).

| Paket | So startest du |
| --- | --- |
| **Windows 10/11 · Setup** | Die EXE installiert den Companion für dein Benutzerkonto und bringt Python und Tcl/Tk mit. Das Beta-Setup ist unsigniert. Falls Windows beim Start warnt oder das Setup blockiert, kannst du das portable ZIP verwenden. |
| **Windows 10/11 · Portabel** | ZIP vollständig entpacken, einmal `Voraussetzungen installieren.cmd` ausführen und danach `PoE2 Guide starten.cmd` öffnen. Das erste Skript prüft Python und Tcl/Tk und richtet sie bei Bedarf ein. |
| **Linux · X11 oder XWayland** | Archiv entpacken, Python 3.10+ mit Tkinter bereitstellen und `sh PoE2-Guide-starten.sh` ausführen. `sh Desktop-Eintrag-anlegen.sh` legt optional einen Menüeintrag an. |

Der Windows-Client lief auf unserem Testsystem bisher stabil. Eine frühere R18-Version lief unter CachyOS. Für die aktuelle Linux-Beta stehen breitere Tests zu Stabilität und Funktionsumfang noch aus.

[Windows-Kurzanleitung](Windows/LIES%20MICH.txt) · [Linux-Kurzanleitung](Linux/LIES%20MICH.txt)

## Bedienung

| Taste | Funktion |
| --- | --- |
| `F8` | Overlay ein- oder ausblenden |
| `F9` | Zwischen Spielmodus und Bearbeiten wechseln |
| `F10` | Companion beenden |
| `F6` | Übungstimer starten, pausieren oder fortsetzen |
| `F7` | Übungstimer zurücksetzen |

Fehlt dir eine Einstellung oder läuft unter Linux etwas anders als erwartet? Beschreib uns gern, was dir aufgefallen ist. [Feedback auf GitHub](https://github.com/wo0t-sys22/PoE2-Buildschmiede-Companion/issues)

## Aus dem Repository starten

`app/` enthält das Programm und die gemeinsamen Daten. Die Starter in `Windows/` und `Linux/` finden diesen Ordner automatisch.

- **Windows** – `Windows\PoE2 Guide starten.cmd`
- **Linux** – `sh Linux/PoE2-Guide-starten.sh`

Einstellungen und Fortschritt liegen lokal in `app/userdata/`. Dieser Ordner wird nicht versioniert.

## Rechtliches

© Buildschmiede. Alle Rechte am eigenen Code und an den eigenen Texten vorbehalten. Der Quellcode ist zur Ansicht veröffentlicht. Für Nutzung, Änderung oder Weitergabe außerhalb des normalen Gebrauchs des Tools bitte vorher anfragen.

Spieldaten, Grafiken und weitere Inhalte stammen von Dritten. Quellen und Lizenzen stehen in [DRITTANBIETER.md](DRITTANBIETER.md).

Dies ist ein unabhängiges Fanprojekt. Path of Exile ist eine Marke von Grinding Gear Games.
```
