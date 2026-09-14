# FunkGateway UI

FunkGateway UI ist eine grafische Linux-Anwendung zur Verbindung von Funktechnik mit VoIP-Diensten wie TeamSpeak und Mumble.

Das Projekt richtet sich an Funkamateure, CB-Funk-Anwender und Betreiber von Funk-Gateways, die Audio, PTT, Schutzfunktionen und VoIP-Integration in einer Oberfläche bündeln möchten.

## Hauptfunktionen

- grafische Oberfläche mit PySide6
- Audio-Routing zwischen Funkgerät und VoIP-Anwendungen
- PTT-Steuerung
- RX-/TX-Pegelanzeige
- Rogerbeep
- Rufzeichen-/ID-Funktionen
- TeamSpeak-Integration
- Mumble-Integration
- Schutz bei Dauer-RX
- automatische Störungsräume
- WAV-Schutzansagen
- VoIP-HF-Sprachfilter
- Unterstützung für mehrere Linux-Distributionen

## Unterstützte Plattformen

Aktuelle Paketvarianten:

- Ubuntu 22.04 LTS
- Ubuntu 24.04 LTS
- Ubuntu 26.04 LTS
- Debian 12
- Debian 13
- Generic Linux

Der FunkGateway-Kern ist in allen Varianten identisch. Unterschiede betreffen hauptsächlich Installer und distributionsspezifische Systempakete.

## Audio

FunkGateway verwendet virtuelle PulseAudio-/PipeWire-Audioziele.

Typische virtuelle Geräte:

- `FunkGateway_TX`
- `FunkGateway_RX`
- `FunkGateway_RX_Input`

Unter PipeWire wird die PulseAudio-Kompatibilitätsschicht verwendet.

Benötigt werden unter anderem:

- `pactl`
- `parec`
- `pacat`
- `paplay`

## PTT-Unterstützung

FunkGateway unterstützt verschiedene Möglichkeiten zur Sendertastung:

- Testmodus
- serielle RTS-/DTR-Steuerung
- USB-Seriell
- CM108/CM119 GPIO
- Linux GPIO

Zusätzlich stehen unter anderem zur Verfügung:

- PTT Lead
- PTT Hang
- TOT
- NOT-AUS / PTT AUS

## TeamSpeak

Die TeamSpeak-Integration verwendet die lokale ClientQuery-Schnittstelle des klassischen TeamSpeak-3-Clients.

Funktionen:

- aktuellen TeamSpeak-Channel anzeigen
- aktuelle Sprecher anzeigen
- Channel Commander automatisch setzen
- Gateway-Client in andere Channels verschieben
- TeamSpeak-Störungsraum festlegen
- automatischer Wechsel in den Störungsraum bei Dauer-RX
- automatische Rückkehr in den vorherigen Channel

Standardmäßig wird ClientQuery unter folgender Adresse erwartet:

```text
127.0.0.1:25639

Der ClientQuery-API-Key kann aus der lokalen TeamSpeak-Konfiguration geladen oder manuell eingetragen werden.

Mumble

FunkGateway unterstützt mehrere Möglichkeiten zur Mumble-Integration.

Lokale Steuerung

Die lokale Mumble-Integration arbeitet über DBus und benötigt keine Server-Adminrechte.

Funktionen:

aktuellen Mumble-Channel anzeigen
aktuelle Sprecher anzeigen
lokalen Mumble-Status prüfen
Mumble Ice

Für erweiterte Serversteuerung kann Mumble Ice verwendet werden.

Unterstützte Varianten:

Direct Ice
Ice über SSH-Tunnel
Admin Bridge

Damit können unter anderem Störungsräume und automatische Channelwechsel realisiert werden.

Admin Bridge

Normale Gatewaybetreiber müssen keine globalen Ice-Secrets erhalten.

Die Admin Bridge ermöglicht eine eingeschränkte serverseitige Steuerung über persönliche Tokens.

Ein separates Admin-Paket befindet sich im Verzeichnis:

admin/
Dauer-RX-Schutz

FunkGateway kann erkennen, wenn der Funkempfang ungewöhnlich lange aktiv bleibt.

Mögliche Reaktionen:

Gateway stummschalten
Schutzansage abspielen
TeamSpeak-Gateway in einen Störungsraum verschieben
Mumble-Gateway in einen Störungsraum verschieben
wiederholte Störungsansagen
nach stabil freiem Funkkanal automatisch reaktivieren
in den vorherigen VoIP-Channel zurückkehren

Die Wiederaktivierung erfolgt optional erst, wenn der Funkkanal für eine definierte Zeit stabil frei war.

VoIP-HF-Sprachfilter

Seit Version 0.5.6.20 gibt es den Filter:

„Nur bestätigte VoIP-Sprache auf HF senden“

Wenn an FunkGateway_TX ausschließlich TeamSpeak oder Mumble hängen, wird PTT nur freigegeben, wenn der jeweilige VoIP-Client tatsächlich einen sprechenden Benutzer meldet.

Damit sollen lokale Client-Töne nicht über Funk ausgesendet werden, zum Beispiel:

Channelwechsel-Töne
Verbindungs- und Trennmeldungen
Mute-/Unmute-Hinweise
sonstige TeamSpeak-/Mumble-Systemtöne

Mumble verwendet dafür getTalkingUsers.

TeamSpeak verwendet den Sprecherstatus der ClientQuery-Schnittstelle.

Schutzansagen

Gemeinsame WAV-Einstellungen befinden sich unter:

Schutz → Ansagen

Sie gelten sowohl für TeamSpeak als auch für Mumble.

Unterstützt werden unter anderem:

Ansage bei Stummschaltung
Ansage im Störungsraum
wiederholte Störungsraum-Ansage
Ansage bei Wiederaktivierung
Installation
Generic Linux
git clone git@github.com:MysticFire01/Funkgateway.git
cd Funkgateway
./install-linux.sh
./start.sh

Alternativ:

./install.sh
./start.sh
Desktop-Eintrag

Optional:

./install-desktop.sh
Python-Ice / Mumble-Komponenten

Falls FunkGateway meldet, dass Python-Ice nicht geladen werden kann:

Integrationen → Mumble → Mumble-Komponenten installieren / reparieren

Alternativ kann die FunkGateway-Python-Umgebung über folgendes Script repariert werden:

./repair-venv.sh

Dabei wird die bestehende virtuelle Python-Umgebung gesichert und neu aufgebaut.

Konfiguration

Die lokale FunkGateway-Konfiguration befindet sich unter:

~/.config/funkgateway-ui/

Diese Konfiguration liegt außerhalb des Programmverzeichnisses und bleibt bei Versionswechseln erhalten.

Dokumentation

Weitere technische Informationen befinden sich im Verzeichnis:

docs/

Dort befinden sich unter anderem:

Architektur
Audio-Routing
Hardware
Bridge-Konzept
Sicherheit

Bitte niemals folgende Daten veröffentlichen oder committen:

TeamSpeak-API-Keys
Mumble-Ice-Secrets
Bridge-Tokens
SSH-Private-Keys
Passwörter

SSH-Schlüssel sollten möglichst über ssh-agent verwendet werden.

Releases

Fertige Pakete für Ubuntu, Debian und Generic Linux werden als GitHub Releases bereitgestellt.

Die ZIP-Pakete gehören nicht direkt in das Git-Repository.

Mitmachen

Beiträge, Fehlerberichte und Verbesserungen sind willkommen.

Weitere Hinweise befinden sich in:

CONTRIBUTING.md
Lizenz

FunkGateway UI steht unter der:

GNU General Public License v3.0

Das bedeutet unter anderem:

Nutzung ist erlaubt
Änderungen sind erlaubt
Weitergabe ist erlaubt
kommerzielle Nutzung ist erlaubt
weitergegebene abgeleitete Versionen müssen ebenfalls unter GPLv3 stehen

Weitere Informationen stehen in der Datei:

LICENSE
Aktuelle Version

0.5.6.20
