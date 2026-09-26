# FunkGateway UI 0.5.9.44

**FunkGateway UI** ist ein Open-Source-Linux-Gateway-Controller für Funk ↔ VoIP. Der Core übernimmt Audio-Routing, RX-Erkennung, PTT, Schutzfunktionen, Rogerbeep, Rufzeichenbake und Papagei/Echotest. TeamSpeak und Mumble sind optionale Integrationen.

**Aktueller stabiler Feldtest-Stand: 0.5.9.44**

## Betriebsarten

FunkGateway bietet vier dauerhaft auswählbare Betriebsarten:

- **PC-User** – Betrieb auf einem normalen Linux-PC ohne Funk-PTT; mit TeamSpeak/PC-Funktionen, PC-Papagei und eigener Hardware-Port-Wahl für Mikrofon/Line-In.
- **Funk-Gateway** – vollständiger Funk↔VoIP-Betrieb mit RX, PTT, Rogerbeep, Rufzeichen, DTMF und Schutzfunktionen.
- **Funk-Papagei** – Funk-RX wird aufgenommen und anschließend wieder über Funk ausgesendet.
- **VoIP-Papagei** – eingehendes VoIP-Audio wird aufgenommen und über eine getrennte virtuelle VoIP-Audiokette zurückgespielt.

Hardware-Port-Wächter können bei Shared-Mic/Line-In-Soundkarten den gewünschten Port automatisch wiederherstellen. PC-User und Funk-RX besitzen getrennte Portkonfigurationen.

Die Startseite passt ihre Anzeigen an die gewählte Betriebsart an. Nicht relevante Funk-PTT-Anzeigen werden in PC-User und VoIP-Papagei ausgeblendet.

## Einfache und erweiterte Gateway-Ansicht

Ab **0.5.9.28** startet der Funk-Gateway-Modus mit einer vereinfachten Oberfläche. Auf der Startseite kann mit **„Erweiterte Einstellungen anzeigen“** jederzeit auf die vollständige Gateway-Oberfläche umgeschaltet werden.

In der einfachen Ansicht bleiben die für den normalen Betrieb wichtigsten Bereiche sichtbar: Start, Audio, PTT, RX/Rogerbeep, Rufzeichen, Papagei, DTMF, Integrationen, Updates, Protokoll und Hilfe. Zusätzliche Feinabstimmungs- und Expertenseiten werden erst in der erweiterten Ansicht eingeblendet.

Der Reiter **Moderation** gehört ausschließlich zum Modus **PC / TeamSpeak** und wird im Funk-Gateway-Modus grundsätzlich nicht angezeigt.

### Vereinfachung innerhalb der Reiter

Die einfache Ansicht blendet nicht nur ganze Expertenreiter aus. Auch auf den weiterhin sichtbaren Seiten werden technische Feinwerte verborgen, wenn für den normalen Betrieb ein bewährter Standard ausreicht. Dazu gehören beispielsweise PTT-/Rogerbeep-Timings, Papagei-Vorlauf/Nachlauf und DTMF-Protokollzeiten.

Die Werte bleiben intern aktiv. Auf neuen Installationen gelten die voreingestellten Standardwerte. Bereits vorhandene benutzerdefinierte Einstellungen werden durch das Umschalten zwischen einfacher und erweiterter Ansicht nicht verändert.

## Einrichtung, Diagnose und Profile

Ab **0.5.9.28** bündelt die Startseite die letzten Funktionsbausteine vor dem Design-Fokus:

- Eigener Reiter **Einrichtung** mit Schritt-für-Schritt-Assistent (Zurück/Weiter) ohne automatisches Senden
- Selbsttest für Audio, PTT, Konfiguration und aktivierte VoIP-Integrationen
- Konfigurations-Backup und Wiederherstellung
- lokale benannte Profile
- kompakte Systemstatusübersicht
- redigiertes Diagnosepaket für Support und Fehlersuche

Diagnosepakete entfernen bekannte Zugangsdaten und Authentifizierungsgeheimnisse. Normale Konfigurationssicherungen und lokale Profile können dagegen sensible Daten enthalten und sollten wie Passwörter behandelt werden.

## Highlights

- Funk ↔ Computer/VoIP mit PipeWire/PulseAudio-kompatiblem Routing
- PTT über seriell, CM108/CM119 und Linux GPIO
- RX/TX-Gain, Pegelanzeigen, TOT und Selbstrücklauf-Schutz
- Rogerbeep: CW-K, Einzelton, Doppelton oder eigene WAV
- intelligente Rufzeichenbake mit Wartefunktion auf freien Kanal
- Papagei/Echotest mit RX-Vorlauf, PTT-Vorlauf und eigener Bake
- harte Audio-Isolation zwischen Papagei und VoIP
- TeamSpeak 3 ClientQuery inkl. Channel Commander, Mute/Deaf und Raumwechsel
- Mumble lokal per DBus sowie optionale Bridge-/Ice-/SSH-Adminmodi
- DTMF-Fernsteuerung direkt über echten Funk-RX
- optionale PIN-AUTH oder TOTP-AUTH
- lokaler TOTP-QR-Code ohne externen Webdienst
- DTMF-Codeliste als PDF
- Funk-Vollzugsmeldungen nach DTMF-Befehlen
- kompaktes oder ausführliches Bildschirm-Log
- integrierte GitHub-Updateprüfung mit SHA256-Prüfung


## Mitgelieferte Standard-WAVs

Ab **0.5.9.28** enthält FunkGateway im Ordner `default_wavs/` generische deutsche Ansagen für alle vorhandenen WAV-Slots. Leere Felder werden automatisch mit diesen Dateien vorbelegt.

Eigene Ansagen können jederzeit über **„WAV auswählen“** eingesetzt werden. Bereits konfigurierte eigene WAV-Pfade werden beim Start nicht überschrieben.

## DTMF-Steuerung

Standardmäßig beginnt ein DTMF-Befehl mit `*` und endet mit `#`. Während einer gültigen DTMF-Steuersitzung wird Funk → VoIP unterdrückt, damit die Steuerfolge nicht in TeamSpeak/Mumble übertragen wird.

Standardcodes:

| Code | Funktion |
|---|---|
| `*91#` | Papagei EIN |
| `*90#` | normaler VoIP-/Gateway-Betrieb |
| `*51#` | TeamSpeak MUTE |
| `*52#` | TeamSpeak UNMUTE |
| `*53#` | TeamSpeak DEAF |
| `*54#` | TeamSpeak UNDEAF |
| `*61#` | Mumble MUTE |
| `*62#` | Mumble UNMUTE |
| `*63#` | Mumble DEAF |
| `*64#` | Mumble UNDEAF |

Zusätzlich stehen je fünf frei belegbare Raumwechsel für TeamSpeak und Mumble zur Verfügung.

### DTMF-AUTH

AUTH ist optional und kann pro Funktion aktiviert werden.

**PIN:**
```text
*00*4711#
```

Die PIN wird nicht im Klartext gespeichert, sondern mit PBKDF2-HMAC-SHA256 und zufälligem Salt.

**TOTP:**
```text
*00*583214#
```

TOTP arbeitet offline nach RFC 6238. Standard: 6 Stellen, 30 Sekunden, Toleranz ±1 Zeitschritt. Erfolgreich verwendete TOTP-Zeitschritte werden gegen Wiederholung gesperrt. Die `otpauth://`-URI und ein lokaler QR-Code können direkt im Programm erzeugt werden.

## Papagei und VoIP-Isolation

Bei aktivem **„VoIP während Papageibetrieb stummschalten“** wird der normale gemischte Pfad `FunkGateway_TX.monitor → Funkgeräte-Ausgang` im Papageibetrieb gesperrt. Interne Papagei-, Bake- und DTMF-Bestätigungs-WAVs werden direkt zum Funkgeräte-Ausgang gespielt.

Dadurch kann laufendes TeamSpeak-/Mumble-Audio nicht mehr in eine Papagei-Aussendung hineingemischt werden.

## DTMF-Vollzugsmeldungen

Nach erfolgreichen DTMF-Befehlen können WAV-Bestätigungen über Funk gesendet werden, z. B. **„Papagei aktiv“** oder **„Gateway/VoIP aktiv“**.

PTT bleibt bis zum tatsächlichen Ende der WAV aktiv. Danach folgt ein einstellbarer PTT-Nachlauf, standardmäßig **2500 ms**, damit gepuffertes Audio vollständig ausgesendet wird.

## Protokoll

Im Reiter **Protokoll** gibt es die Checkbox **„Ausführliches Log“**.

- Ohne Haken: kompakte Anzeige mit PTT, Sprechern, DTMF-Aktionen, Papagei, Betriebsart-/Raumwechseln, Schutzfunktionen, Warnungen und Fehlern.
- Mit Haken: zusätzliche technische Ablauf- und Diagnosemeldungen.
- Die gespeicherte Logdatei bleibt unabhängig davon vollständig.

## Installation

Die empfohlenen Installationspakete befinden sich bei den GitHub-Releases.

Verfügbare Pakete:

- Generic Linux
- Ubuntu 22.04 LTS
- Ubuntu 24.04 LTS
- Ubuntu 26.04 LTS
- Debian 12
- Debian 13

Beispiel Ubuntu 24.04 LTS:

```bash
chmod +x install-ubuntu-24.04.sh
./install-ubuntu-24.04.sh
./start.sh
```

## Schnellstarter

`install-desktop.sh` erzeugt den stabilen Menüeintrag `~/.local/share/applications/funkgateway-ui.desktop`.
Ab **0.5.9.28** werden dabei alte lokale FunkGateway-Starter automatisch entfernt. Ein bereits angehefteter alter GNOME-Favorit wird auf die stabile Desktop-ID umgestellt, sodass der Drawer/Dash nicht mehr auf einen alten Versionsordner zeigt.

## Update-Funktion

FunkGateway kann GitHub auf eine neuere Version prüfen. Release-Pakete werden mit SHA256-Prüfsummen veröffentlicht, damit Downloads vor der Installation geprüft werden können.

## Sicherheit

- TOTP-Geheimnisse und QR-Codes enthalten vertrauliches Schlüsselmaterial.
- Statische DTMF-PINs sind Zugriffsschutz, aber keine Abhörsicherheit.
- TOTP reduziert Replay-Risiken; Funk-DTMF identifiziert jedoch nicht die physische Person am Funkgerät.
- Mumble-Ice-Secrets sollten nicht auf unkontrollierten Funkrechnern verteilt werden.

## Dokumentation

Weitere Dokumente befinden sich unter `docs/`.

Der vollständige Versionsverlauf steht in `CHANGELOG.md`.

## Lizenz

GNU General Public License v3.0

### PC-Papagei und TeamSpeak-Audio

Der PC-Papagei verwendet PulseAudio/PipeWire statt eines direkten ALSA-Hardwarezugriffs. Dadurch kann er die normalen Desktop-Standardgeräte parallel zu TeamSpeak benutzen. Aufnahme und Wiedergabe bleiben zeitlich getrennt, um Rückkopplungsschleifen zu vermeiden.

### Eigener Moderations-Reiter

Ab **0.5.9.28** liegt die TeamSpeak-Moderation in einem eigenen Reiter. Die Seite nutzt eine zweispaltige Anordnung, damit Benutzerwahl, Poke, Verschieben und Kick ohne langes Scrollen erreichbar sind.
