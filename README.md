# FunkGateway UI 0.5.9.20

**FunkGateway UI** ist ein Open-Source-Linux-Gateway-Controller für Funk ↔ VoIP. Der Core übernimmt Audio-Routing, RX-Erkennung, PTT, Schutzfunktionen, Rogerbeep, Rufzeichenbake und Papagei/Echotest. TeamSpeak und Mumble sind optionale Integrationen.

**Aktueller stabiler Feldtest-Stand: 0.5.9.20**

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

## Update-Funktion

FunkGateway kann GitHub auf eine neuere Version prüfen. Release-Pakete werden mit SHA256-Prüfsummen veröffentlicht und vor der Installation geprüft.

Ab **0.5.9.20** kann der Updater nach dem Download außerdem:

- verlorene ZIP-Ausführungsrechte der Shell-Skripte automatisch wiederherstellen,
- den passenden Distributions-Installer in einem sichtbaren Terminal starten,
- eine notwendige `sudo`-Passwortabfrage normal im Terminal zulassen,
- anschließend optional `install-desktop.sh` ausführen und den Schnellstarter auf den neuen Versionsordner setzen.

Die bisherige Installation bleibt als Rückfallmöglichkeit erhalten und `~/.config/funkgateway-ui` wird weiterverwendet.

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