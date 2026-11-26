# PoE2 Ingame Guide

Kampagne, Bosse, Builds und Atlas im Spiel. **v.0.21.0** bereitet die Kampagne von PoE2 1.0 vor. Für Akt 1–4 sind Guides und für Akt 5 und 6 jeweils zehn Gebietsvorlagen enthalten.

## Funktionsumfang wählen

Im Willkommensdialog schätzt du deine PoE-Erfahrung selbst ein. Unter **Optionen → Funktionsumfang** kannst du die Auswahl später ändern.

| Auswahl | Verfügbare Funktionen | Voreinstellung |
| --- | --- | --- |
| **Ich bin neu in PoE 2** | Kampagnenguide, Gebietsauswahl und Tipps für den Einstieg. | Ausführlich |
| **Die ersten Schritte sind mir vertraut.** | Zusätzlich Builds, Boss-Guides, Lexikon, Atlas und Crafting. | Ausführlich |
| **Ich kenne auch die tieferen Spielmechaniken.** | Zusätzlich weitere Werkzeuge. | Kompakt |
| **Ich öffne zuerst PoB und dann das Spiel.** | Zusätzlich experimentelle Funktionen und weitere Einstellungen. | Kompakt |

Bei einem Update mit bereits abgeschlossenem Willkommensdialog startet ein älteres Profil ohne gespeicherten Funktionsumfang mit Profil 3 und behält seine bisherige Textdichte.

## Build importieren

Ab Profil 2 findest du den Import unter **Wissen → Builds**. Unterstützt werden Buildschmiede-JSON, PoE2-Spielpläne (`.build`, auch als Varianten-ZIP von Mobalytics) und PoB2-Exporte als XML-Datei oder als Exportcode in einer Textdatei. Der Companion speichert importierte Builds lokal und zeigt den ersten importierten Build direkt im Guide. Weitere Varianten findest du in der Build-Auswahl.

Im Reiter **Build** siehst du Ausrüstung, Fertigkeiten mit Supports und Passivbaum für die aktuelle Phase. Ziehe die Baumkarte mit der Maus, um sie zu verschieben. Über die Knotenliste kannst du die einzelnen Werte ansehen. Den **Build-Überblick** unter der Phasenauswahl kannst du ein- und ausblenden.

Der Companion zeigt Builds als Guide. Zum Planen führt **Web-Planer öffnen ↗** ab Profil 2 zum Build-Planer auf Buildschmiede.

Mit **Strg+Umschalt+Alt+B** öffnest du ab Profil 2 im fokussierten HUD das lokale **Build Import Interface**. Hier kannst du Builds importieren, Phasen bearbeiten und die Änderungen direkt im HUD ansehen.

In den Ausrüstungskarten des HUD und des Build Import Interface übernimmt **Item kopieren** die konkreten Werte als englischen Itemtext für Path of Building 2. Dort kannst du ihn im Bereich **Items** einfügen. **Handel** öffnet zuerst die Filterauswahl für ein ähnliches Item. Wähle Liga, Basis oder Gegenstandsklasse, die gewünschten Werte und deren Mindestanteil. Anschließend öffnet sich die offizielle Handelsseite im Browser.

## Start unter Windows

Mit der Setup-EXE genügt ein Doppelklick. Python und Tcl/Tk sind enthalten. Die Anleitung für den ersten Start liegt als `README-Tester.txt` neben der Setup-Datei und im Installationsordner.

Für das portable Windows-ZIP gelten die folgenden Schritte.

1. Installiere **Python 3.10 oder neuer mit Tcl/Tk**. Der Windows-Installer bietet „Add python.exe to PATH“ an.
2. Entpacke die gesamte ZIP über **Alle extrahieren** in einen Ordner, in den du schreiben kannst. Führe **PoE2 Guide starten.cmd** im entpackten Ordner aus.
3. Starte PoE2 im Fenster oder randlosen Fenster und betrete ein Gebiet. Der Starter öffnet den Guide und dessen lokalen Dienst gemeinsam.

## Start unter Linux (Vorschau)

Entpacke das Linux-Archiv und führe **PoE2-Guide-starten.sh** aus, im Terminal mit `sh PoE2-Guide-starten.sh`. Voraussetzungen, Hinweise zu Wayland und Skalierung sowie die Unterschiede zu Windows stehen in der **LIES MICH.txt** des Linux-Pakets. Die folgenden Abschnitte gelten für beide Systeme, Pfade wie `app\userdata` schreiben sich unter Linux `app/userdata`.

Die Gebietserkennung sucht zuerst nach dem Spiel-Log in den Steam-Bibliotheken und üblichen Standalone-Installationsordnern. Wenn die Suche scheitert, wähle im Overlay unter **Optionen → Client.txt wählen** die Datei im Unterordner `logs` deiner PoE2-Installation. Sobald du das nächste Gebiet betrittst, übernimmt der Guide den Namen aus der Logdatei. Die automatische Build-Phase nutzt die im Guide gespeicherte Charakterstufe. Unter **Build** kannst du die Phase jederzeit direkt wählen.

## Im Spiel bedienen

| Taste oder Aktion | Funktion |
|---|---|
| **F8** | Overlay aus- und einblenden |
| **F9** | Zwischen Spielmodus und Bearbeiten wechseln |
| **F6** | Speedrun-Timer starten, pausieren oder fortsetzen |
| **F7** | Aktuellen Lauf zurücksetzen |
| **F4** | Separate Boss-Zeit starten oder ablesen |
| **Strg+Umschalt+F9** | Overlay anzeigen und bedienbar machen |
| **F10** oder **Companion beenden** in den Optionen | Overlay und lokalen Dienst schließen |
| **PoE2 Guide starten erneut öffnen** | Das laufende Overlay anzeigen und bedienbar machen |
| Im Bearbeitungsmodus an der Gebietsüberschrift ziehen | Fenster verschieben |
| Optionen → Anzeige | Breite und Höhe einstellen |
| **Zoom** unter Anzeige | Schriftgröße unabhängig vom Fenster einstellen |
| **Zoom − / +** in der HUD-Leiste | Schriftgröße in 10-Prozentpunkten einstellen |
| **Stoppuhr** und **Checkliste** in der HUD-Leiste | Timeranzeige und Abhakfelder ein- oder ausblenden |
| **Buildschmiede-Signet** neben dem Gebietstitel | Website öffnen |

Im Spielmodus sind die Reiter, Boss-Links und Schaltflächen direkt anklickbar. Klicks auf den Guide-Text und die freien Flächen gehen an PoE2. Fahre mit der Maus über längeren Text und scrolle dort mit dem Mausrad. **F9** ermöglicht das Verschieben am Titel. Kampagne und Atlas nutzen höchstens 20 % der Breite des jeweiligen Monitors.

Unter **Optionen → Tastenkürzel** stellst du die HUD- und Timer-Tasten ein. Gib etwa `F6` oder `Strg+Alt+R` ein und wähle dort **Tastenkürzel speichern**. Ein leeres Feld deaktiviert die Belegung. Die Boss-Zeit läuft separat und wird per Taste gestoppt.

Blende die Stoppuhr ein, um die laufende Zeit rechts neben der Levelanzeige zu sehen. Ein Klick auf die Zeit öffnet das separate Speedrun-HUD mit Gesamtzeit, Aktzeiten, Abstand zur persönlichen Bestzeit und der schnellsten Zeit je Akt. Die laufende Zeit bleibt dabei im Haupt-HUD sichtbar. Beide Fenster folgen dem Regler **Optionen → HUD & Anzeige → Transparenz**. Der Timer erkennt den Wechsel in den nächsten Akt über `Client.txt` und stoppt beim erkannten Endgame-Eintritt nach Akt 6. Die gemessene Echtzeit schließt Ladezeiten ein.

Starte am Flussufer und spiele alle sechs Akte ohne Timerpause, um eine persönliche Bestzeit zu setzen. Mit **Beenden** schließt du einen Lauf manuell ab. Pausierte und manuell beendete Läufe dienen der Übung. **Reset** setzt den aktuellen Lauf zurück und behält die gespeicherten Bestzeiten. Die Zeitdaten stehen in `poe2_race_state.json` unter `app/userdata/`.

Kampagne, Build-Guide und Wissen teilen sich Position, Breite und Zoom. Der Doktorhut öffnet **Wissen** mit der Suche. Ab Profil 2 ist dort **Atlas** als Kategorie verfügbar. **Ausführlich / Kompakt** stellt die Tiefe der Erklärungen ein.

## Wissen

**Wissen** bietet im Einstiegsprofil Kampagne und Tipps. Ab dem zweiten Profil stehen weitere Suchkategorien zur Verfügung, darunter **Werkzeuge** mit **Affixe & Modifikatoren**. Unter **Alles** durchsucht ein eingegebener Begriff alle für dein Profil verfügbaren Kategorien. Ab Profil 3 zeigt **Tastenkürzel** die Funktion und ihre Belegung nebeneinander. Ein Klick öffnet den jeweiligen Eintrag.

Unter **Lexikon → Gegenstände → Währung** findest du normale Währungen, Ligamaterialien und Crafting-Gegenstände. Du kannst nach deutschen und englischen Namen suchen. Im Hybridmodus stehen englische Spielbegriffe neben deutschen Erklärungen. **Verfügbarkeit offen** kennzeichnet Datensätze, deren Einsatz in der aktuellen Spielversion ungeklärt ist. Mitgelieferte Icons werden lokal geladen.

**Erklärung & Praxis** ergänzt die Kurzbeschreibungen. Bei aktiven Skills erscheint der Abschnitt, wenn ein individueller Praxishinweis vorliegt. Der Tooltip am Artikeltitel verwendet dieselbe Kurzbeschreibung. Tooltips zeigen verfügbare Original-Icons für passende Gegenstände, Währungen, Gemmen und passive Knoten. Hybrid kombiniert deutsche Sätze mit englischen Spielbegriffen.

## Kampagne

- **Quest** beginnt mit den Layout-Hinweisen, anschließend stehen Ziel, Belohnung und Abstecher. Hellblau hebt Wege und Signale hervor, Quest-Ziele erscheinen in dunklerem Blau und dauerhafte Boni in Grün. Uncut Gems sind in Cyan hervorgehoben, auch bei optionalen Belohnungen. In Red Vale hörst du etwa auf das Rauschen der Obelisken. Die Boss-Links stehen unter den Hinweisen.
- **Boss-Guides** zeigen Vorbereitung, Kampfplan, Angriffssignale, Reaktion, das nächste Schadensfenster und verfügbare Wille-Belohnungen. Öffne einen Guide über den Boss-Link in der Kampagne oder unter **Wissen → Bosse**. Über die Suche kannst du Kämpfe auch vorab nachschlagen.
- **Build** zeigt Skills, Supports, Passive Tree und Gear je Phase. Zur Wahl stehen **Supporting Fire · Taktiker**, **Archon Djinn · Varashta**, **Twister · Spirit Walker** und **Whirling Assault · Martial Artist**. Supporting Fire ist die erste Auswahl. Kampagne und OBS teilen sich die Build-Auswahl.

**Archon Djinn · Varashta** von terence_ begleitet den Wechsel von den ersten Zaubern zu Kelaris Befehlen. Ab Stufe 90 bleibt die Budgetvariante automatisch aktiv. „Schwarmfestung mit Ruzhans Falle“ und die weiteren Spezialisierungen wählst du selbst. Der Build-Überblick erklärt Stärken und Schwächen. Die Fragen zur Spielweise und zu Questbelohnungen findest du bei der jeweiligen Phase.

Unter **Kompakt** kannst du im Build und bei Bossen über **Details anzeigen** tiefer einsteigen. Der separate Kampagnenleitfaden liegt in `PoE2_Kampagnen_Guide.md`.

Das automatische Öffnen von Boss-Guides nutzt die erkannten Gebiete in `poe2_boss_arenas.json`. Beispiele sind Solitary Confinement und Heart of the Tribe. Die Einstellung steht ab Profil 2 in den Optionen. Die Boss-Taste zum Messen der Kampfzeit ist ab Profil 3 verfügbar.

## Atlas

Unter **Wissen → Atlas** findest du die Progression vom ersten Wegstein über den Brennenden Monolithen bis zum Turm des Ursprungs. **Ausrüstung herstellen** und **Affixe nachschlagen** ergänzen die Schritte und die Itemlevel-Schwellen. **Tablets & Farm-Ziele** bietet Suchausdrücke für Wegsteine, Erfahrung, Omens, Abyss und Breach. Der kopierte Suchausdruck richtet sich nach der Client-Sprache.

## Build-Guides direkt in den JSON-Dateien ergänzen

Vorhandene Build-Dateien kannst du über **Build importieren** hinzufügen. Eigene Build-Phasen kannst du auch direkt in den mitgelieferten Guides ergänzen.

1. Beende den Guide mit **F10**. Öffne im entpackten Ordner die Build-Daten unter `app`.
2. Kopiere in `poe2_campaign_companion.json` innerhalb von `builds` einen Build als Vorlage. Vergib eine eigene `id` wie `mein-stormweaver`. Gib den Leveling-Stufen aufsteigende `min_level`-Werte ab 1.
3. Starte **PoE2 Guide starten.cmd** neu. Dein Build erscheint im Build-Guide.

Links stehen in der jeweiligen Datei unter `sources`. Ein Boss kann unter `build_tips` einen Tipp mit deiner Build-ID als Schlüssel bekommen. Für einen zusätzlichen Affix-Filter kannst du einen Eintrag in `crafting.builds` ergänzen.

## OBS und Arbeitsfassung

Das Standalone-Paket startet das HUD. Die Buildschmiede-Website ist der Einstieg zu den Online-Guides. **Optionen** zeigt die Versionsnummer und den lokalen Port.

Für OBS verwende `http://127.0.0.1:8765/race-overlay.html` als Browserquelle. Das Overlay zeigt Gebiet, Level, XP, Zeit, Tode, Spielmodus, HC-SSF-Status und nächste Aktion. Die vollständige OBS-Ansicht mit Reitern ist unter `/overlay.html` erreichbar. Falls beim Start ein anderer Port gewählt wurde, setze den unter **Optionen** angezeigten Port ein.

Das Checklisten-Signet in der HUD-Leiste schaltet die Abhakfelder um. Strukturierte Guides haben ihre Aufgaben direkt in den jeweiligen Abschnitten. Die Einträge werden mit dem aktiven Run gespeichert. Unter **Optionen → Checkliste → Neue Run-Checkliste** beginnst du einen neuen Run.

**Strg+Umschalt+Alt+K** im fokussierten HUD öffnet den lokalen Datenaustausch. Wähle Kampagne, Bosse, Begriffe, Lexikon, Währungen oder deutsche Spieldaten. Lade die aktive JSON-Datei herunter oder wähle einen Import und bestätige die Vorschau. Das HUD übernimmt importierte Daten beim nächsten Start. In WordPress verwendest du dieselbe Datei in den Buildschmiede-Werkzeugen.

Ab Profil 3 findest du die Tastatur- und Mausreferenz unter **Wissen → Tastenkürzel**. Eigene HUD-Kürzel kannst du unter **Optionen → Tastenkürzel** ändern und speichern.

Der Companion liest die Gebietsstufe und englische oder deutsche Level-up-Meldungen lokal aus `Client.txt`. In **Optionen → Levelanzeige → Level manuell einstellen** kannst du das aktuelle Level für die laufende Sitzung setzen. Beim nächsten erkannten Level-up übernimmt der Companion den neuen Wert. Das aktuelle Level steuert auch die automatische Build-Stufe.

Die Levelanzeige ist standardmäßig an und zeigt in Kampfgebieten der Kampagne die geschätzte XP-Ausbeute regulärer Monster. Grün bedeutet volle XP, Gelb einen Malus und Rot höchstens 75 % der regulären XP. Die Stoppuhr schaltet den **Speedrun-Timer** in derselben Zeile ein und aus. Unter **Optionen → Anzeige → Menüleisten-Hintergrund** stehen Deckend, Halbtransparent und Transparent zur Wahl.

Neue Gebiets- und Bossdaten werden erst nach Prüfung ergänzt. Top 3 im Affix-Tab zeigt die stärksten belegten Rolls für die jeweilige Basis mit Item Level und Ingame-Tier.

## Update und Datensicherung

Entpacke die neue ZIP in einen eigenen Ordner und öffne **PoE2 Guide starten.cmd**. Der Starter erkennt einen älteren laufenden Guide und versucht, ihn regulär zu beenden. Bei derselben oder einer neueren laufenden Version öffnet er das vorhandene Overlay. Den geladenen Stand siehst du unter **Optionen** direkt oben. Zeigt der Starter eine Meldung zum alten Guide, beende ihn mit **F10** und öffne den neuen Starter erneut.

Benutzerdaten landen in `app\userdata`. Beende den Guide mit **F10**, bevor du vorhandene Dateien dorthin kopierst:

- `poe2_race_state.json` für Runs, Fortschritt und Notizen
- `poe2_location_settings.json` für den Client.txt-Pfad
- `poe2_guide_settings.json` für Ausführlich oder Kompakt und die Build-Auswahl
- `poe2_overlay_window.json` für Position, Größe und Zoom
- `poe2_hud_preferences.json` für Funktionsumfang, Hotkeys, Timer- und Levelanzeige sowie Boss-Automatik
- `poe2_checklists.json` für Checklisten aus R18
- `build-import-interface/` für lokal gespeicherte Build-Importe. Frühere Importe aus `build-planner/` bleiben über ihre gespeicherten IDs verfügbar.

Beim vorherigen Paket lagen diese Dateien im Hauptordner. Für ein späteres Update kannst du stattdessen `app\userdata` übernehmen. Das Löschen von `poe2_overlay_window.json` bei beendetem Guide setzt die HUD-Geometrie zurück. Der Diagnosebericht liegt in `app\userdata\overlay_fehler.txt`.

## Anzeige und Fehlerbehebung

- **Starter zeigt Python-Fehler:** Installiere Python 3.10+ mit Tcl/Tk. Starte aus dem entpackten Ordner.
- **Overlay liegt hinter PoE2:** Wechsle im Spiel zu **Fenster** oder **Randloses Fenster**. Drücke F8 oder öffne den Starter erneut, um es einzublenden.
- **Bearbeiten klappt nicht:** Drücke **Strg+Umschalt+F9** oder öffne **PoE2 Guide starten** erneut.
- **OBS zeigt 404:** Prüfe die Browserquellen-Adresse und setze den Port aus **Optionen** ein.
- **Der Guide meldet eine fehlende Datei:** Entpacke die gesamte ZIP in einen eigenen Ordner und öffne dort **PoE2 Guide starten.cmd**.
- **Anzeige zu groß oder klein:** In F9 am Griff **Größe** ziehen und bei Bedarf die Schrift über **Zoom** unter Anzeige ändern. Der Guide rendert Text passend zur DPI des Monitors.

Die Kampagnen- und Atlas-Daten stehen in `poe2_campaign_companion.json`, `poe2_campaign_tips.json` und `poe2_endgame_atlas.json`. Die Mechanik-Links führen zu PoE2DB und PoE2Wiki. Bei den Creator-Builds sind die jeweiligen Videos und Planner verlinkt. Der Dienst läuft lokal auf dem unter **Optionen** angezeigten Port und liest das Client-Log.

Die Offline-Spieldaten verbinden den Buildschmiede-Katalog mit Spielbegriffen von Grinding Gear Games. Für den deutsch-englischen Abgleich verwenden wir die Sprachdaten von PoE2DB, die Handelstexte von Exiled Exchange 2 und den über RePoE extrahierten Sprachstand 4.5.4.3. Der Guide von terence_ verlinkt die Originalquellen des Builds. [PoE2DB](https://poe2db.tw/de/) · [Exiled Exchange 2](https://github.com/Kvan7/Exiled-Exchange-2) · [Sprachdaten und Quellrevision](https://github.com/gw1108/PathOfExile_Translated/tree/0b5e587d69b433cfe277f5689876951fd1beff47/dist/poe2)
