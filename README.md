# SMW Play Launcher

Kleines Windows-Programm (Python, nur Standardbibliothek). Einmal einrichten, danach startet **Play** auf einer Seite den Hack direkt im Emulator. Das Format ist nicht an Spinjump gebunden: es soll später auch für eine SMWC-Erweiterung und den SMWC Downloader & Patcher taugen.

## Protokoll

```
smwplay://play?url=<https-Adresse einer .bps oder .zip>[&id=<Kennung>][&title=<Titel>][&sha256=<Prüfsumme>]
```

- `url`: Pflicht, nur `https`, kein Benutzername. Direkt auf eine `.bps` oder auf ein `.zip` mit `.bps` darin (bei mehreren fragt der Launcher).
- `id`: `quelle:name` als Schlüssel für die Bibliothek (nicht für den Dateinamen), z. B. `spinjump:mein-hack@1.0`. Ohne `id`: Host plus Hash der Adresse.
- `title`: nur Anzeige. `sha256`: Prüfsumme des Downloads (vor dem Entpacken); stimmt sie nicht, wird abgebrochen.

Spinjump setzt den Link in `web/src/lib/launcher.ts`. Der **Link-Generator** (kleiner Link unten im Einrichtungsfenster) baut ihn aus einer Adresse.

## Ablauf

Windows startet den Launcher mit dem Link (Registrierung unter `HKCU\Software\Classes\smwplay`, beim Speichern der Einrichtung). Der Launcher lädt die Datei, zieht bei einem ZIP die `.bps` heraus, wendet sie auf die ROM an (Prüfsummen von Quelle, Ergebnis und Patch) und legt `<Hacks-Ordner>/<Name>/<Name>.sfc` ab, wobei `<Name>` der Name der BPS-Datei ist (z. B. `Mario's Inferno/Mario's Inferno.sfc`; ohne Dateinamen, also bei einem direkten Link, der Titel). Ist sie schon da, wird nichts geladen: der Launcher führt im Hacks-Ordner eine kleine Bibliothek (`.smwplay-library.json`, Kennung → fertige ROM) und schaut dort vor dem Download nach. Das gilt auch für ZIPs (dort hängt der Dateiname vom Inhalt ab). Enthält ein ZIP **mehrere** BPS-Patches, werden alle gepatcht und in einem Ordner abgelegt (`<Hack>/<Patch>.sfc`, Ordner nach dem Titel); gefragt wird nur, welcher startet (der zuletzt gestartete ist vorgewählt). Ein Patch, der nicht zur ROM passt, stoppt die anderen nicht. Gelöschte ROMs werden neu geladen. Danach startet der Emulator.

**FXPak Pro:** In der Einrichtung kann das Ziel auf „FXPak Pro“ stehen. Der Launcher patcht wie gewohnt, kopiert die ROM über **QUsb2Snes** (`ws://localhost:23074`, muss laufen) nach `<Ordner>/<Name>/<Name>.sfc` auf die SD-Karte (Standard `/ROMS/Spinjump`) und startet sie dort. Liegt sie schon da, wird nur gestartet. Ablauf wie im SMWC Downloader & Patcher (`fxpak.py`, Abhängigkeit `websockets`). Mit einem Fake-Server getestet, nicht mit echter Hardware. Findet der Launcher QUsb2Snes nicht, springt er **nicht still** auf den Emulator: Er zeigt die Meldung mit „Erneut versuchen“, „Zum Emulator wechseln“ (merkt sich das dauerhaft, in der Einrichtung rückstellbar) und „Abbrechen“. Auch „Kein Gerät gefunden“ (QUsb2Snes läuft, der FXPak fehlt) fragt so nach.

Einstellungen: `%APPDATA%\Spinjump\launcher.json` (ROM, Hacks-Ordner, Emulator, Argumente).

**Emulator:** Der Launcher erkennt ihn am Dateinamen (Mesen, Snes9x, bsnes, higan, ares, ZSNES, RetroArch) und nimmt passende Argumente, solange das Feld leer ist (meist nur die ROM). Bei RetroArch sucht er in `cores/` einen SNES-Core (snes9x, bsnes, Mesen-S) und startet mit `-L <core> <rom>`. Mesen ist die Voreinstellung der Tests; RetroArch ist nur gegen Dateinamen und Core-Suche getestet, nicht mit einem echten Start.

## Sicherheit

- Geladen wird nur von **vertrauten Domains** (Domain samt Subdomains). Die Liste pflegt allein der Betreiber (`BUILTIN_TRUSTED` in `core.py`: `spinjump.club`, `smwcentral.net`); Spieler können nichts eintragen. Andere Domains werden abgelehnt, ebenso Weiterleitungen dorthin oder auf `http`.
- Aus einem ZIP werden nur `.bps`-Dateien im Speicher gelesen. Nichts wird entpackt oder ausgeführt. Grenzen: 32 MB, 500 Einträge.
- Dateinamen werden bereinigt, Ausgaben liegen nur im Hacks-Ordner. Nur BPS (E-29). Keine ROMs werden geladen oder gehostet.


## Browser-Erweiterung für SMW Central

`extension/` ist eine kleine Chrome-Erweiterung (Manifest V3, auch für Firefox geeignet). Auf Detailseiten von smwcentral.net setzt sie neben „Download“ einen **Play**-Knopf, der den Launcher mit der Datei öffnet, die SMWC selbst verlinkt (`smwplay://play?url=https://dl.smwcentral.net/<id>/<Datei>&id=smwcentral:<name>-<id>&title=…`). Sie lädt nichts und braucht nur Zugriff auf die Seite. Der Ordner heißt wie die BPS-Datei im ZIP.

- Für Spieler: Seite `/launcher` auf spinjump.club (Anleitung, ZIP-Download). ZIP bauen mit `python launcher/build-extension.py` und auf den Server nach `~/spinjump-data/downloads/SMWPlayExtension.zip` legen (wie die EXE, siehe `docs/DEPLOYMENT.md`).
- Zum Ausprobieren: `chrome://extensions` → Entwicklermodus → „Entpackte Erweiterung laden“ → Ordner `launcher/extension`.
- Beim ersten Klick fragt Chrome, ob smwcentral.net den Launcher öffnen darf; dort „Immer erlauben“ wählen.
- Test: `node --test launcher/extension/content.test.js` (gegen den Seitenausschnitt von `?p=section&a=details&id=39701`). Gegen die echte Seite ist es noch nicht geprüft; ändert SMWC den Aufbau (`#file-download-button`, `#submission-header .title`), muss `content.js` nachgezogen werden.
- Download-Zähler: Ein Download mit dem Launcher-Code ohne Login hat den SMWC-Zähler erhöht (610 → 611 am 24.11.2026).
- Offen: viele ältere SMWC-Hacks haben nur IPS; der Launcher kann nur BPS.

## Linux und macOS (GitHub Actions)

`.github/workflows/launcher.yml` baut bei jeder Änderung in `launcher/` die Programme für Windows, Linux und macOS (PyInstaller, `launcher/smwplay.spec`) und lädt sie als Artefakte hoch (Actions → Lauf → Artifacts). Vorher laufen die Tests auf allen drei Systemen (Linux mit `xvfb`).

- **Linux:** eine Datei `SMWPlayLauncher`. Beim Speichern der Einrichtung legt der Launcher `~/.local/share/applications/smwplay.desktop` an und setzt per `xdg-mime` den Handler für `smwplay://`. Ohne Emulator-Eintrag öffnet `xdg-open` die ROM. Einstellungen unter `~/.config/Spinjump/launcher.json`.
- **macOS:** `SMWPlayLauncher.app` (ZIP). Die `.app` meldet `smwplay://` über ihre Info.plist an; der Link kommt als Ereignis (`::tk::mac::LaunchURL`), nicht als Argument. Emulatoren als `.app` startet der Launcher mit `open -a`. Nicht signiert: beim ersten Start Rechtsklick → Öffnen. Einstellungen unter `~/Library/Application Support/Spinjump/`.
- **Nicht getestet:** die Tests laufen nur auf Windows geprüft; Registrierung, macOS-Link-Ereignis und die gebauten Programme sind noch nie auf Linux/macOS gelaufen. Erst nach dem ersten Actions-Lauf auf echten Rechnern ausprobieren.
- **Android:** geht mit Tkinter/PyInstaller nicht. Bräuchte eine eigene App (Link-Handler, BPS patchen, Emulator per Intent starten); noch nicht begonnen.

## Nächste Schritte

- **Liste vertrauter Seiten von spinjump.club laden** (signiert, mit Bewerbung für Seitenbetreiber), damit neue Seiten kein Launcher-Update brauchen.
- FXPak Pro: ein Ziel pro Play-Knopf statt global; Gerät wählbar.
- Emulator-Voreinstellungen mit echten Starts prüfen (RetroArch, Snes9x, bsnes); Auswahlliste statt Erkennung nach Dateinamen.
- Gemeinsames Modul mit dem SMWC Downloader & Patcher; SMWC-Erweiterung (prüfen, ob SMWC-Downloads per Programm ladbar sind).
- EXE signieren (SmartScreen).

## Entwickeln

```powershell
python -m pytest launcher/tests      # Tests
python launcher/app.py               # Einrichtung
python launcher/app.py "smwplay://play?url=https%3A%2F%2Fspinjump.club%2Fapi%2Fv1%2Fhacks%2Fmein-hack%2Fdownload%2F1.0"
python -m PyInstaller --onefile --noconsole --name SMWPlayLauncher launcher/app.py   # EXE bauen
```

Die EXE liegt nicht im Repo. Die Seite verlinkt `/downloads/SMWPlayLauncher.exe` (`web/src/routes/launcher`); sie muss beim Deployment dort abgelegt werden.
