## 0.5.6.20
- Mumble/Ice: Python-Ice-Erkennung robuster gemacht. FunkGateway erkennt nun auch Ubuntu/Debian-Systemmodule unter `/usr/lib/python3/dist-packages`, wenn eine ältere isolierte venv verwendet wird.
- Mumble-Komponentenprüfung unterscheidet nun zwischen „Ice fehlt“ und „Ice ist im System vorhanden, aber die laufende Python-Umgebung sieht es noch nicht“.
- Nach Installation von Python-Ice weist FunkGateway auf einen vollständigen Neustart hin.
- Mumble/Ice: neuer Button **SSH-Tunnel stoppen**. Er beendet ausschließlich den von FunkGateway gestarteten Tunnel und lässt extern gestartete SSH-Tunnel unangetastet.
- Ubuntu-24.04-Installer installiert die optionalen Pakete `python3-zeroc-ice`, `zeroc-ice-slice` und `openssh-client` mit, ohne den übrigen Gateway-Betrieb bei einem optionalen Paketfehler abzubrechen.
- Veralteten Hinweis im `start.sh` auf Ubuntu 22.04 korrigiert.

# 0.5.6.20

- Mumble-Unterseite vollständig scrollbar gemacht; Ice-/SSH-Felder bleiben erreichbar.
- Direkte Ice-/SSH-Adminfelder nach oben gezogen, damit Read-/Write-Secret, Murmur.ice und SSH-Zugang nicht unterhalb des sichtbaren Bereichs verschwinden.
- Checkbox zum temporären Anzeigen/Verbergen der Ice-Secrets ergänzt; Secrets werden weiterhin nicht gespeichert.
- Eingebaute SSH-Key-Anleitung ergänzt (ED25519, ssh-copy-id, ssh-agent, kein Passwortspeichern).
- Hinweise für direkten Ice-Modus präzisiert: Read-Secret für Lesen/Status, Write-Secret zusätzlich für Channel-Wechsel.

# 0.5.6.20

- **Hauptsteuerung dauerhaft sichtbar:** Gateway starten, Gateway stoppen, NOT-AUS / PTT AUS und Rufzeichen jetzt senden stehen jetzt fest oberhalb der Reiter.
- Die vier Hauptschalter verschwinden damit auch auf kleineren Bildschirmen oder bei langen Einstellungsseiten nicht mehr aus dem sichtbaren Bereich.
- Der NOT-AUS ist unabhängig vom aktuell geöffneten Reiter direkt erreichbar.
- Doppelte Hauptschalter auf der Startseite entfernt; dadurch bleibt dort mehr Platz für Statusanzeigen.
- Tooltips erklären, dass die Hauptsteuerung in jedem Reiter verfügbar bleibt.
- Startseite enthält einen kurzen Hinweis auf die neue feste Hauptsteuerung.
- Referenzplattform: Ubuntu 24.04 LTS.

# 0.5.6.13

- Mumble-Betriebsarten sicher getrennt: **lokal**, **Bridge des Server-Admins**, **direktes Ice (Admin)** und **Ice über SSH (Admin)**.
- Bridge-Modus für normale Gatewaybetreiber aktiviert: Bridge-Adresse + persönliches Token genügen; globale Ice-Secrets werden im Client nicht benötigt.
- Neuer Bridge-Verbindungstest prüft Bridge, Token, zugeordnetes Gateway und aktuellen Channel.
- Dauer-RX-Schutz kann im Bridge-Modus den vom Admin freigegebenen Störungsraum aktivieren und anschließend in den freigegebenen Normalraum zurückkehren.
- Im Bridge-Modus sind freie Channel-Wahl und freie User-Steuerung absichtlich gesperrt; diese Grenzen werden verständlich erklärt.
- **Direktes Ice / SSH bleibt ausdrücklich Adminmodus.** Ice Read-/Write-Secrets werden weiterhin nicht in `config.json` gespeichert und nicht protokolliert.
- Neuer Button **„Admin-Paket speichern / weitergeben“** im Mumble-Subtab. Das mitgelieferte Paket enthält Bridge-Software, Admin-CLI, Tokenverwaltung, Installer, Diagnose, systemd-Service, Sicherheits-/Kompatibilitätsdokumentation und Reverse-Proxy-Beispiel.
- Hilfe erklärt ausdrücklich: Eine Bridge mit echtem Ice-Secret darf nicht auf einem unkontrollierten Funkrechner eines Normalnutzers betrieben werden; sie gehört auf einen vom Server-Admin kontrollierten Server/Management-Host.
- Fallback für alte/EOL-Mumble-Server dokumentiert: Bridge auf modernem Admin-Management-Rechner betreiben und den lokalen Ice-Endpunkt sicher per SSH/VPN erreichen, statt alte Paketabhängigkeiten zu erzwingen.
- Lokale Mumble-Funktionen über DBus bleiben unabhängig von Bridge/Ice vollständig optional und beeinflussen den Gateway-Core bei Fehlern nicht.

# Changelog

## 0.5.6.11 – Integrationen mit Subtabs übersichtlicher gegliedert
- Reiter **Integrationen** auf eine zweite Tab-Ebene umgestellt, damit die Hauptnavigation trotz weiterer Module kompakt bleibt.
- Neue Untertabs **Übersicht**, **TeamSpeak** und **Mumble**.
- In **Übersicht** sitzt der zentrale Schalter für das TeamSpeak-Modul sowie eine kurze Erklärung zum modularen Aufbau.
- Sämtliche bisherigen TeamSpeak-Einstellungen wurden unverändert in den Untertab **TeamSpeak** verschoben.
- Vorbereiteter Untertab **Mumble** ergänzt; noch ohne aktive Mumble-Steuerung und ohne Einfluss auf den Gateway-Core.
- Zusätzliche Tooltips für TeamSpeak-Verbindungstest, API-Key laden, Channel Commander, Channel-Wechsel und Status kopieren.
- Architekturgrundsatz festgehalten: optionale Integrationen bleiben vom Audio-/PTT-/RX-/TX-/Schutz-Core entkoppelt; spätere Module können parallel ergänzt werden.
- Referenzplattform: Ubuntu 24.04 LTS.

## 0.5.6.10 – Schutzstatus auf der Startseite eindeutiger
- Feldtest 0.5.6.9: Der Dauer-RX-Schutz blieb korrekt gemutet, während die große RX-Anzeige zeitweise bereits wieder „FUNK KANAL FREI“ zeigte. Das war technisch möglich, aber für den Bediener missverständlich.
- Schutzstatus hat nun Vorrang vor der normalen Frei-/RX-Anzeige auf der Startseite.
- Bei aktivem Dauer-RX-Schutz erscheinen je nach Zustand eindeutige Meldungen: **„STÖRUNG WEITERHIN VORHANDEN“**, **„STÖRUNG NOCH NICHT GEKLÄRT“** oder **„PRÜFE, OB STÖRUNG BEENDET IST …“**.
- Der bisherige sichere Wiederanlauf aus 0.5.6.9 bleibt unverändert: kurze Frei-Impulse heben den Schutz nicht auf; stabile Frei-Zeit und Schutz-Frei-Schwelle müssen weiterhin erfüllt sein.
- Beim Aktivieren oder Aufheben eines Schutzstatus wird die große RX-Anzeige sofort passend aktualisiert.
- Wird ein laufender Frei-Timer durch neues RX oder einen zu hohen RX-Pegel zurückgesetzt, springt die Anzeige ebenfalls sofort zurück auf den passenden Störungsstatus.
- Für den TeamSpeak-Störungsraum zeigt die große RX-Anzeige während des Schutzes **„GATEWAY IM STÖRUNGSRAUM“**.
- Integrierte Hilfe um die neuen Schutzstatus-Anzeigen erweitert.
- Referenzplattform: Ubuntu 24.04 LTS.

## 0.5.6.9 – Dauer-RX-Schutz gegen kurze Frei-Impulse gehärtet
- Feldtest: Bei offener Rauschsperre konnte RX kurzzeitig als „frei“ erkannt werden. Dadurch wurde die sichere automatische Wiederaktivierung zu früh freigegeben.
- „Nur wieder aktivieren, wenn Funk-RX stabil frei war“ ersetzt die bisherige Einmal-Frei-Prüfung.
- Neue Einstellung **Stabil frei für** (Standard 3 s): RX muss durchgehend frei bleiben; jedes neue RX-Signal setzt den Timer zurück.
- Neue Einstellung **Schutz-Frei-Schwelle** (Standard -30 dBFS): Der RX-Pegel muss während der kompletten Frei-Zeit unter dieser Schwelle bleiben.
- Ein einzelner kurzer „FUNK KANAL FREI“-Impuls kann den Dauer-RX-Schutz nicht mehr aufheben.
- Der Frei-Timer wird bei erneutem RX oder zu hohem Pegel sofort zurückgesetzt.
- Diagnosemodus protokolliert Start und Rücksetzen des Schutz-Frei-Timers.
- Hilfetext und Tooltips für die neue Schutzfreigabe erweitert.
- Bestehende Konfigurationen bleiben kompatibel; neue Werte erhalten sichere Standardwerte.

## 0.5.6.8 – Schutzfunktionen, Störungsraum und TS3-Channel-Fix
- TeamSpeak TS3 3.6.2 Feldtest: `channelinfo` wird vom ClientQuery nicht unterstützt (`error id=256 command not found`).
- Aktueller Channelname wird deshalb über `channelvariable cid=<CID> channel_name` gelesen.
- Komfortfehler bei der Channel-Namensabfrage setzen das gesamte TeamSpeak-Modul nicht mehr auf „nicht verbunden“.
- Neuer Reiter **Schutz**. Alle Funktionen sind optional; ohne Haken bleibt der bisherige Gateway-Betrieb unverändert.
- Einstellbarer Dauer-RX-Schutz: Schutz nach frei wählbarer Dauer, Standard 180 s.
- Bei Schutzabschaltung wird Funk→Computer stummgeschaltet und normale PTT-Weitergabe blockiert; RX-Erkennung selbst läuft weiter.
- Optional automatische Wiederaktivierung nach frei wählbarer Zeit.
- Optionaler sicherer Wiederanlauf: erst wieder aktivieren, nachdem Funk-RX mindestens einmal frei war.
- Eigene WAV-Dateien für Dauer-RX/Mute, Störungsraum und Wiederaktivierung.
- TeamSpeak-Störungsraum benutzerdefinierbar und serverbezogen gespeichert; keine fest verdrahteten Channel-Namen oder CIDs.
- Channel-Liste kann im Schutz-Tab geladen und der gewünschte Störungsraum ausgewählt/gespeichert oder gelöscht werden.
- Gateway kann beim Betreten des Störungsraums automatisch gemutet werden.
- Störungsraum-Ansage kann in einem frei wählbaren Minutenintervall wiederholt werden.
- Optional kann Dauer-RX den eigenen TeamSpeak-Gateway-Client automatisch in den gespeicherten Störungsraum verschieben.
- Vorheriger TeamSpeak-Channel wird gemerkt; optionale automatische Rückkehr nach Wiederaktivierung.
- Fehlt auf einem Server die Störungsraum-Zuordnung, funktioniert der Dauer-RX-Schutz trotzdem weiter und protokolliert nur einen Hinweis.
- Große Statusanzeige auf der Startseite zeigt zusätzlich **GATEWAY AKTIV** bzw. **GATEWAY GEMUTET – Grund**.
- Neue Tooltips an Schutz- und TeamSpeak-Channel-Bedienelementen.
- Hilfe komplett erweitert: Schnellstart, Audio, RX/Rogerbeep, PTT/TOT, TeamSpeak, Schutzfunktionen, Störungsraum, Wiederanlauf und Fehlersuche in einfacher Sprache.
- TeamSpeak-, Audio-, Schutz- und PTT-Kern bleiben voneinander entkoppelt: ein Fehler in einer optionalen Integration darf den normalen Gateway-Core nicht stoppen.


## 0.5.6.7 – TeamSpeak Channel-Anzeige und Gateway-Verschieben
- Feldtest von 0.5.6.6 bestätigt: ClientQuery-Verbindung funktioniert auf Ubuntu 24.04 LTS mit TS3 3.6.2.
- Feldtest bestätigt: aktueller TeamSpeak-Sprecher wird korrekt angezeigt; Sprecher aus anderen Channels werden nicht als aktiver Sprecher des Gateway-Channels angezeigt.
- Feldtest bestätigt: Channel Commander wird bei Funk-RX automatisch gesetzt und anschließend wieder deaktiviert.
- Neuer TeamSpeak-Status **Aktiver TeamSpeak-Channel** mit Channel-Name und CID.
- Neue Channel-Liste im Reiter **Integrationen**; sichtbare TeamSpeak-Channels können per ClientQuery geladen und ausgewählt werden.
- Neuer Knopf **Gateway in ausgewählten Channel verschieben**. Es wird ausschließlich der eigene lokale Gateway-Client (`whoami`/eigene `clid`) mit `clientmove` verschoben.
- Nach dem Verschieben wird der neue Channel erneut abgefragt, angezeigt und im FunkGateway-Protokoll dokumentiert.
- Fehler beim Laden oder Verschieben sind weiterhin kopierbar und beeinflussen Audio/PTT/RX/TX nicht.
- TeamSpeak-Modul bleibt optional; bei ausgeschaltetem Modul bleibt die normale FunkGateway-Funktion unverändert.
- Internen Zustandsfehler korrigiert: beim erfolgreichen ClientQuery-Verbindungsaufbau werden ermittelte `schandlerid`/`clid` nicht mehr unmittelbar wieder auf `None` gesetzt.
- Referenzplattform: Ubuntu 24.04 LTS.
- Python- und Bash-Syntaxprüfungen durchgeführt.


## 0.5.6.6 – TeamSpeak ServerConnectionHandler Recovery
- Feldtest bestätigt: `currentschandlerid` und `serverconnectionhandlerlist` liefern auf dem Funkrechner jeweils `schandlerid=1`.
- Fehlerbild dokumentiert: trotz gültigem Handler meldete das Integrationsmodul zeitweise `invalid server connection handler ID`.
- TeamSpeak-Modul validiert den aktuell gewählten ServerConnectionHandler nach AUTH mit `currentschandlerid` und `serverconnectionhandlerlist`.
- Ein bereits gültiger Handler wird **nicht** unnötig mit `use` neu gesetzt; der normale ClientQuery-Ablauf bleibt unverändert.
- Nur im Recovery-Fall wird ein aktuell vorhandener Handler mit `use schandlerid=<ID>` ausgewählt und anschließend verifiziert.
- Bei `invalid server connection handler ID` wird die ClientQuery-Verbindung einmal vollständig neu aufgebaut, der Handler neu ermittelt und der ursprüngliche Befehl einmal wiederholt.
- Der TeamSpeak-Verbindungstest zeigt nun zusätzlich `schandlerid`, lokale `clid` und `cid` an; dadurch sind spätere Feldtests leichter nachvollziehbar.
- Channel-Commander-Kommandos bleiben `clientupdate client_is_channel_commander=1/0`, wie am echten TS3 3.6.2 manuell bestätigt.
- TeamSpeak-Integration bleibt optional; Fehler beeinflussen Audio, PTT, RX/TX und normale Gateway-Funktion nicht.
- Referenzplattform: Ubuntu 24.04 LTS.
- Python- und Bash-Syntaxprüfungen durchgeführt.

## 0.5.6.5 – kopierbare Fehlermeldungen / TeamSpeak-Diagnose
- Fehlerdialoge im FunkGateway sind jetzt kopierbar; der vollständige Meldungstext kann markiert oder über **Fehler kopieren** in die Zwischenablage übernommen werden.
- Der manuelle TeamSpeak-Verbindungstest zeigt Fehler zusätzlich in einem kopierbaren Dialog an.
- TeamSpeak-Status und Sprecheranzeige sind mit der Maus/Tastatur markierbar.
- Neuer Knopf **TeamSpeak-Status kopieren** kopiert Status und aktuellen Sprecher in die Zwischenablage.
- Die Änderung betrifft nur Diagnose/Bedienung; Audio, PTT, RX/TX, Rogerbeep und optionale Integrationen bleiben funktional unverändert.
- Ubuntu 24.04 LTS bleibt Referenzplattform.
- TeamSpeak ClientQuery Greeting-Fix aus 0.5.6.5 bleibt enthalten.
- Python- und Bash-Syntaxprüfungen durchgeführt.

## 0.5.6.5 – Ubuntu 24.04 LTS / TeamSpeak Greeting Fix
- Referenzplattform des Funkrechners korrigiert: Ubuntu 24.04 LTS (Noble) statt Ubuntu 22.04 LTS.
- Eigenes Ubuntu-24.04-LTS-Paket und angepasste Installations-/README-Dateien.
- TeamSpeak ClientQuery Greeting-Parser an den real beobachteten TS3-3.6.2-Datenstrom angepasst.
- Feldtest zeigte Zeilentrennung `\n\r`; dadurch begann die Folgelinie intern mit `\rselected schandlerid=...` und wurde von `startswith("selected schandlerid=")` nicht erkannt.
- `_readline()` entfernt nun CR sowohl am Anfang als auch am Ende einer Query-Zeile.
- Dadurch wird `selected schandlerid=...` zuverlässig erkannt und AUTH erst anschließend gesendet.
- Frühere Feldtests bleiben bestätigt: `auth`, `whoami`, `clientlist -voice` und `clientupdate client_is_channel_commander=0/1` funktionieren am echten TS3 3.6.2.
- Python- und Bash-Syntaxprüfungen durchgeführt.

## 0.5.6.5 – TeamSpeak ClientQuery Feldtest-Fix
- Reales TS3-3.6.2-ClientQuery-Protokoll am Funkrechner verifiziert.
- Begrüßungsdaten werden jetzt exakt bis `selected schandlerid=...` gelesen, bevor AUTH gesendet wird.
- API-Key wird bei `auth apikey=...` bytegetreu/unverändert übertragen; er wird nicht mehr als normaler Query-Text escaped.
- Hintergrund: Der manuelle RAW-Socket-Test antwortete unmittelbar mit `error id=0 msg=ok`; damit waren TS3, Port 25639 und API-Key nachweislich korrekt.
- Die manuellen Befehle `whoami`, `clientlist -voice` und `clientupdate client_is_channel_commander=1/0` wurden am echten Client erfolgreich bestätigt.
- Präzisere Fehlermeldung, falls die ClientQuery-Begrüßung nicht vollständig empfangen wird.
- TeamSpeak-Integration bleibt optional; Ausfälle beeinflussen Audio/PTT des FunkGateway-Core nicht.

## 0.5.6.5 – TeamSpeak-Feldtest / ClientQuery-Protokoll korrigiert
- Reale ClientQuery-Feldtests auf Ubuntu 22.04 LTS mit TeamSpeak 3.6.2 dokumentiert.
- `auth apikey=...` manuell bestätigt: `error id=0 msg=ok`.
- `whoami` manuell bestätigt; der lokale Gateway-Client wurde korrekt geliefert.
- `clientlist -voice` manuell bestätigt; `client_nickname`, `client_flag_talking` und `client_is_channel_commander` stehen zur Verfügung.
- Channel Commander manuell in beide Richtungen bestätigt: `clientupdate client_is_channel_commander=1` und anschließend `=0`, jeweils mit `error id=0 msg=ok`.
- Ursache des verbliebenen Verbindungsproblems eingegrenzt: FunkGateway sendete nach AUTH zusätzlich ein nacktes `use`. Der reale klassische ClientQuery-Workflow benötigt diesen Schritt nicht; die aktive Verbindung ist nach dem Greeting/AUTH bereits gewählt.
- Das zusätzliche `use` aus dem TeamSpeak-Modul entfernt. `whoami`, `clientlist -voice` und `clientupdate` werden nun direkt nach erfolgreichem AUTH ausgeführt.
- Standard-ClientQuery-Timeout auf 2,0 Sekunden gesetzt; Timeout-Meldungen nennen jetzt zusätzlich den betroffenen Query-Befehl.
- API-Key-Feld um **API-Key anzeigen** ergänzt. Der Schlüssel bleibt standardmäßig maskiert und kann zur lokalen Kontrolle sichtbar geschaltet werden.
- TeamSpeak bleibt ein optionales Zusatzmodul; Fehler in ClientQuery beeinflussen Audio, PTT, RX/TX und andere Programme weiterhin nicht.
- Versionsnummer auf **0.5.6.5** erhöht.
- Python-Syntaxprüfung und Bash-Syntaxprüfung durchgeführt.

## 0.5.6.1 – TeamSpeak ClientQuery Timeout-Fix
- Feldtest auf Ubuntu 22.04 LTS mit klassischem TeamSpeak 3.6.2: ClientQuery lauscht korrekt auf `127.0.0.1:25639`, `~/.ts3client/clientquery.ini` ist vorhanden.
- Fehlerbild dokumentiert: `Cannot read from timed out object` beim TeamSpeak-Verbindungstest.
- Ursache im TeamSpeak-Modul behoben: der ClientQuery-Socket wird nicht mehr über `socket.makefile()` / `readline()` weiterverwendet, nachdem beim Einlesen der Begrüßung ein Timeout aufgetreten ist.
- Neue direkte, zeilenbasierte Socket-Leselogik mit eigenem Empfangspuffer (`_recv_buffer`).
- ClientQuery-Begrüßung wird jetzt in einem begrenzten Zeitfenster gelesen; ein Timeout beendet nur das Greeting und beschädigt nicht die nachfolgenden Query-Lesevorgänge.
- Befehle werden mit `socket.sendall()` gesendet; Antworten werden weiterhin bis zur TeamSpeak-`error`-Zeile ausgewertet.
- Aussagekräftigere Timeout-Meldung ergänzt: `TeamSpeak ClientQuery antwortet nicht innerhalb von ... s`.
- Verbindungsabbruch setzt Socket und Empfangspuffer vollständig zurück, damit ein neuer Verbindungsversuch sauber startet.
- TeamSpeak-Funktionen bleiben optional; ein ClientQuery-Fehler darf Audio, RX/TX oder PTT nicht beeinflussen.
- Versionsnummer für den Ubuntu-22.04-Testbuild auf **0.5.6.1** erhöht.
- Python-Syntaxprüfung und lokaler ClientQuery-Protokolltest gegen einen simulierten Server durchgeführt.

## 0.5.6 – optionale TeamSpeak-Integration / RX-Großanzeige
- Neuer Reiter **Integrationen**; alle Zusatzmodule sind optional und beeinflussen den FunkGateway-Kern bei Fehlern nicht.
- Erstes **TeamSpeak-3-ClientQuery-Modul** für den klassischen TS3-Client.
- Optional: **Channel Commander bei gültigem Funk-RX automatisch EIN**, nach RX-Ende wieder AUS.
- Anzeige der aktuell sprechenden TeamSpeak-Nutzer über `clientlist -voice`.
- ClientQuery-Host/Port/API-Key konfigurierbar; API-Key kann aus `~/.ts3client/clientquery.ini` geladen werden.
- Große allgemeine Anzeige auf der Startseite: **FUNKEMPFANG AKTIV / FUNK KANAL FREI / FUNK RX SPERRZEIT**.
- TOT-Protokoll erweitert: TX-Dauer und erkennbare Streams auf `FunkGateway_TX` werden protokolliert.
- TeamSpeak-Modul standardmäßig ausgeschaltet; bestehender Betrieb mit anderer Software bleibt unverändert.

## 0.5.5 – RX-Stabilität / virtuelle Aufnahmequelle
- Automatische normale Aufnahmequelle `FunkGateway_RX_Input` für TeamSpeak/Mumble/FRN.
- RX-Hysterese und Mindestdauer eines gültigen RX-Signals.
- Konfigurierbare RX-Sperrzeit nach Rogerbeep, Mindest-Frei-Zeit und Cooldown.
- TX/RX-Gain frei einstellbar; TX bis +24 dB, RX -24 bis +18 dB.
- RX/TX-dBFS-Anzeigen und TX-Clipping-Anzeige.
- Optionales RX/Rogerbeep-Diagnoseprotokoll.


## 0.5.4 – RX-Gain / FunkGateway_RX
- Einstellbare RX-Verstärkung für Funk → Computer: -12, -9, -6, -3, 0, +3 oder +6 dB.
- Neue virtuelle Computer-Empfangsquelle `FunkGateway_RX` (`funkgateway_rx.monitor`).
- Funk-RX wird vom gewählten physischen Eingang gelesen, mit RX-Gain bearbeitet und an FunkGateway_RX weitergereicht.
- RX-Erkennung und Rogerbeep-Trigger arbeiten weiterhin mit dem unveränderten Eingangssignal; RX-Gain verändert die Schaltschwelle nicht.
- 16-Bit-Clipping-Schutz bei positiver RX-Verstärkung.
- TX-Gain, RX-Rogerbeep und universelles FunkGateway-Icon bleiben enthalten.

## 0.5.3 – TX-Gain / Icon
- Einstellbare TX-Verstärkung für Computer/TeamSpeak/Mumble/FRN → Funk: 0, +3, +6 oder +9 dB.
- TX-Gain wirkt nur auf den ausgegebenen Funk-Audioweg; VOX/PTT-Erkennung bleibt auf dem unverstärkten Signal.
- 16-Bit-Clipping-Schutz bei positiver TX-Verstärkung.
- Universelles FunkGateway-Icon `funkgateway.png` ins Paket aufgenommen.
- Installer für den Ubuntu-Starter setzt das Icon automatisch.
- Auch das laufende Qt-Fenster setzt das FunkGateway-Icon.

## 0.5.2 – RX-Rogerbeep
- Neue Funk-RX-Audioerkennung über eine frei wählbare Pulse/PipeWire-Quelle.
- Rogerbeep nach dem Ende eines empfangenen HF-Durchgangs.
- Rogerbeep wird direkt über den Funkgeräte-Ausgang gesendet, nicht zu TeamSpeak.
- Auswahl: Aus, CW K (-.-), Einzelton, Doppelton oder eigene WAV-Datei.
- CW K mit einstellbarer Tonfrequenz und WPM.
- Einstellbare RX-Schwelle, RX-Nachhaltezeit, Roger-Verzögerung und Lautstärke.
- Schutz gegen Rogerbeep-Rückkopplung/Endlosschleifen.
- Testknopf für den Rogerbeep ergänzt.

## 0.5.1 – Ubuntu 22.04 LTS
- Eigener Installer für Ubuntu 22.04 LTS.
- PulseAudio und PipeWire-Pulse-kompatible Audiokette über pactl/parec/pacat/paplay.
- PySide6, sounddevice, soundfile und pyserial in lokaler venv.
- Benötigte Ubuntu-22.04-XCB/Qt-Laufzeitbibliotheken werden installiert.
- TeamSpeak-/Mumble-/FRN-Routing-Wächter aus 0.5 übernommen.
- Audio-VOX/PTT-Erkennung aus 0.5 übernommen.
- Rufzeichenaufnahme-Fix aus 0.5 übernommen.
- Optionaler Ubuntu-Anwendungsmenü-Eintrag ergänzt.

## 0.5
- Quellcode in Module aufgeteilt.
- Quellcode und Architektur verständlicher kommentiert.
- GPLv3/Open-Source-Projektstruktur ergänzt.
- Portsuche erweitert: `/dev/ttyS*`, `/dev/ttyUSB*`, `/dev/ttyACM*`.
- Schaltfläche `Ports neu suchen` für Hotplug/USB-Adapter.
- Freundliche Portnamen in der GUI.
- Hilfe erweitert.
- Rufzeichenintervall 1–1440 Minuten.
- Rufzeichen-Aufnahmedauer 1–300 Sekunden.
- Versionsnummer bereinigt.
- Doppelte Audio-Sink-Funktion aus 0.4 entfernt.

## 0.4
- Hilfe und Rufzeichenaufnahme ergänzt.

## 0.3.x
- Audio-getriggerte PTT über FunkGateway_TX.
- Serielle PTT, CM108 und Linux GPIO.

### 0.5 – kleine Korrektur
- Verständlicher Hinweis, wenn kein USB-Seriell-Adapter (`/dev/ttyUSB*` / `/dev/ttyACM*`) gefunden wurde.

### 0.5 – korrigierter Port-Hinweis
- Sichtbarer Hinweis direkt unter der COM-/USB-Port-Auswahl.
- Doppelte `refresh_ports()`-Definition entfernt.
- `/dev/ttyUSB*` und `/dev/ttyACM*` werden verständlich als USB-Seriell-Geräte gemeldet.

### 0.5 – Audio-Routing-Korrektur
- FunkGateway_TX wird beim Programmstart geprüft und bei Bedarf automatisch angelegt.
- Laufende Audioprogramme können in der GUI angezeigt und per Klick zu FunkGateway_TX geroutet werden.
- Bekannte Sprachprogramme wie TeamSpeak, Mumble und FRN können beim Gateway-Start automatisch auf FunkGateway_TX umgeschaltet werden.
- Die GUI zeigt an, ob das ausgewählte Programm tatsächlich über FunkGateway_TX läuft.

### 0.5 – dauerhafter Audio-Routing-Wächter
- FunkGateway_TX wird bereits beim Programmstart geprüft und bei Bedarf angelegt.
- Laufende Audioprogramme werden in der GUI angezeigt.
- Ein ausgewähltes Programm kann per Knopf direkt zu FunkGateway_TX verschoben werden.
- TeamSpeak, Mumble, FRN und weitere typische Sprachprogramme werden während des laufenden Gateways alle 1,5 Sekunden geprüft.
- Wenn PipeWire oder EasyEffects einen neuen Stream wieder auf den falschen Sink legt, verschiebt FunkGateway ihn automatisch zurück auf FunkGateway_TX.

### 0.5 – Rufzeichenaufnahme korrigiert
- Mikrofonquellen werden direkt über `pactl` aus PipeWire/PulseAudio gelesen.
- Monitor-Quellen wie `funkgateway_tx.monitor` werden nicht als Mikrofon angeboten.
- Die Aufnahme nutzt `parec` mit dem tatsächlich ausgewählten Source-Namen.
- Die WAV-Datei wird auf Inhalt und Pegel geprüft.
- Praktisch stumme Aufnahmen erzeugen eine Warnung statt einer falschen Erfolgsmeldung.

- Generic Linux-Paket auf den korrigierten 0.5-Stand mit Rufzeichenaufnahme-Fix und Routing-Wächter aktualisiert.
