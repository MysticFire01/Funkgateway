## 0.5.9.44

- PC-User: eigene Hardware-Port-Auswahl für Aufnahmequellen (z. B. Front-Mic, Rear-Mic, Line-In).
- PC-User: eigener Hardware-Port-Watchdog, getrennt vom Funk-RX-Watchdog.
- PC-User: gewählter Port kann beim Modusstart und nach Audio-Neusuche wiederhergestellt werden.
- Startseite passt Titel, Statusfelder und Hinweise an PC-User, Funk-Gateway, Funk-Papagei und VoIP-Papagei an.
- PTT-Status wird in Nicht-Funk-Modi nicht mehr als relevante Startseiteninformation angezeigt.

## 0.5.9.43

### Layout/Scroll-Fix

- Einstellungsseiten sind horizontal und vertikal bei Bedarf scrollbar.
- Mehr Innenabstand verhindert abgeschnittene Beschriftungen an Fensterrändern.
- Lange QFormLayout-Zeilen dürfen umbrechen; Eingabefelder wachsen flexibel.
- Standardfenster etwas vergrößert, bleibt aber auch auf kleineren Displays nutzbar.
- Der RX-Hardware-Port-Watchdog aus 0.5.9.42 ist in beiden synchronisierten Builds enthalten.

# FunkGateway UI 0.5.9.41

## Kritischer PTT-Sicherheitsfix für PC-/VoIP-Modi

- PC-User und VoIP-Papagei dürfen keine Funk-PTT mehr initialisieren oder schalten.
- `set_ptt()` ist gegen fehlende/`None`-PTT-Objekte abgesichert.
- Beim Wechsel in PC-User oder VoIP-Papagei wird ein eventuell noch vorhandenes PTT-Objekt sicher freigegeben, geschlossen und verworfen.
- Beim Stoppen des Funkbetriebs wird das PTT-Objekt ebenfalls vollständig geschlossen.
- Verhindert den Fehler `NoneType object has no attribute key` im PC-User-Modus.

# FunkGateway UI 0.5.9.40

## Optionaler RX-Hardware-Port für Shared Mic/Line-In

- Funk-RX kann jetzt optional einen konkreten Hardware-Eingangsport der gewählten Aufnahmequelle fest vorgeben.
- Gedacht für Soundkarten mit gemeinsam genutztem bzw. umschaltbarem Mic-/Line-In-Anschluss.
- Verfügbare Ports werden über PipeWire/PulseAudio (`pactl`) ermittelt und mit ihrem aktiven/verfügbaren Status angezeigt.
- Auswahl bleibt für normale USB-/Ein-Port-Geräte standardmäßig deaktiviert und ist damit rückwärtskompatibel.
- Optional kann der gewählte Port beim Programmstart, nach „Audiogeräte neu suchen“ und unmittelbar vor dem Start von Funk-RX automatisch wiederhergestellt werden.
- Ein manueller Button „Hardware-Port jetzt anwenden“ erlaubt die direkte Prüfung.
- Quelle, Port und Wiederherstellungsoption werden in `config.json` gespeichert.
- Beispiel Shared-Port: `analog-input-linein` statt `analog-input-mic`.

---

# FunkGateway UI 0.5.9.39 – vorheriger Stand

## Papagei / TeamSpeak Channel Commander

- Channel Commander wird während einer Funk- oder VoIP-Papagei-Rückgabe jetzt vom internen Wiedergabezustand gehalten.
- Kurze leise Stellen oder ein abfallender TeamSpeak-VOX-/Sprechstatus können Channel Commander während der laufenden Rückgabe nicht mehr kurz ausschalten.
- Erst nach dem tatsächlichen Ende der Papagei-Wiedergabe wird die Haltefunktion aufgehoben und Channel Commander wieder freigegeben.
- Die vorhandene VoIP-Auto-Routing-Funktion bleibt erhalten.

# FunkGateway UI 0.5.9.38 – VoIP-Papagei Auto-Routing und Channel Commander

- VoIP-Papagei: automatische Umleitung unterstützter VoIP-Wiedergabestreams auf `FunkGateway_VoIP_Parrot_RX` bleibt standardmäßig aktiviert.
- Laufende und neu erzeugte TeamSpeak-, Mumble- und TeamTalk-Wiedergabestreams werden während aktivem VoIP-Papagei regelmäßig nachgezogen.
- Beim Stoppen werden umgeleitete Streams wieder auf ihren ursprünglichen Ausgang zurückgesetzt.
- Channel Commander für Funk- und VoIP-Papagei thread-sicher über ein Qt-Signal umgesetzt.
- Channel Commander wird nur während der Papagei-Rückgabe gesetzt und danach wieder entfernt.
- Fehlerhafte bzw. aus Worker-Threads nicht ausgeführte `QTimer.singleShot()`-Umschaltung wurde ersetzt.

## 0.5.9.38 – VoIP-Papagei: dedizierter RX-Pfad erzwungen

- Im Normalbetrieb lauscht der VoIP-Papagei jetzt fest auf `funkgateway_voip_parrot_rx.monitor`.
- Alte gespeicherte Mikrofon-/EasyEffects-Quellen können dadurch nicht mehr unbemerkt als Papagei-Eingang aktiv werden.
- Neue Option **„Expertenquelle verwenden“** für Sonderfälle.
- Die freie Quellenauswahl ist nur bei aktivierter Expertenoption freigeschaltet.
- Standard bleibt: VoIP-Ausgang → `FunkGateway_VoIP_Parrot_RX`; Rückgabe → `FunkGateway_VoIP_Parrot_Input`.

# FunkGateway UI 0.5.9.38

- Neuer dedizierter VoIP-Empfangspfad `FunkGateway_VoIP_Parrot_RX`.
- Im VoIP-Client wird `FunkGateway_VoIP_Parrot_RX` als Wiedergabegerät gewählt.
- Der VoIP-Papagei lauscht standardmäßig auf `funkgateway_voip_parrot_rx.monitor`.
- Der Rückweg bleibt getrennt über `FunkGateway_VoIP_Parrot_Input` als Mikrofon/Aufnahmegerät.
- Dadurch gelangt das lokale physische Mikrofon nicht automatisch in die VoIP-Papagei-Aufnahme.
- Die bisherige freie Quellenauswahl bleibt als Fallback für Sonderfälle verfügbar.
- Globales Desktop-/VoIP-Audiorouting wird weiterhin nicht verändert.

# FunkGateway UI 0.5.9.34

- VoIP-Papagei: fehlendes `import os` für das Playback-Routing behoben.
- Playback-Fehler lassen den VoIP-Papagei nicht mehr in einem Wiedergabezustand hängen.
- Bei Fehler/Abbruch werden Aufnahme- und Wiedergabeprozess beendet und die temporäre WAV gelöscht.
- Der Papagei wird anschließend sauber in den Idle-Zustand zurückgesetzt und kann erneut gestartet werden.

# 0.5.9.33 – VoIP-Papagei Routing

- VoIP-Papagei-Wiedergabe wird gezielt auf `funkgateway_voip_parrot` geroutet.
- `PULSE_SINK=funkgateway_voip_parrot` wird zusätzlich gesetzt, um PipeWire/PulseAudio-Routing zuverlässiger zu machen.
- Fallback verschiebt ausschließlich den einzelnen `paplay`-Wiedergabestream per `pactl move-sink-input`, falls die Ausgabe zunächst am Standard-Sink landet.
- Der globale Standard-Sink wird nicht verändert. Nach Stop/Ende des VoIP-Papageis bleibt das ursprüngliche Desktop-/VoIP-Audiorouting unverändert.

# 0.5.9.33 – Temporäre WAVs des VoIP-Papageis

- Temporäre VoIP-Papagei-Aufnahme wird nach erfolgreicher Wiedergabe sofort gelöscht.
- Aufräumen erfolgt zusätzlich beim Stoppen, beim Neustart des VoIP-Papageis und im Fehler-/Abbruchfall.
- Keine dauerhafte Speicherung der gesprochenen VoIP-Durchgänge.

# 0.5.9.31 – Plattformunabhängiger VoIP-Papagei

- Neuer eigener Reiter **VoIP-Papagei** ausschließlich im PC-/VoIP-Modus.
- Der vorhandene PC-Papagei bleibt unverändert ein lokaler Mikrofontest.
- Der Funk-Papagei bleibt davon vollständig getrennt.
- Plattformneutraler Audio-Pfad für TeamSpeak, Mumble, TeamTalk und weitere VoIP-Clients.
- Eigener virtueller Mikrofoneingang `FunkGateway_VoIP_Parrot_Input`.
- Frei wählbare VoIP-Audio-Eingangsquelle.
- Einstellbare Spracherkennungsschwelle.
- Einstellbarer Vorlaufpuffer, damit der Anfang kurzer Durchgänge nicht verloren geht.
- Einstellbarer Nachlauf zur Erkennung des Sprachendes.
- Einstellbare Pause vor der Rückgabe.
- Einstellbare **maximale Sprechzeit** pro Durchgang.
- Einstellbare Rückkopplungssperre nach der Wiedergabe.
- Während der eigenen Wiedergabe wird nicht erneut aufgenommen.

# FunkGateway UI 0.5.9.33 – Debian-12-Testbuild

- Fehler beim Betriebsartwechsel behoben: Der PC-/TeamSpeak-Haken **„Channel Commander beim Sprechen automatisch setzen“** bleibt jetzt erhalten, wenn kurz in den Funk-Gateway-Modus und anschließend zurück in den PC-Modus gewechselt wird.
- Beim Wechsel in den Funk-Gateway-Modus wird nur noch der aktuelle Channel-Commander-Laufzeitzustand neu synchronisiert; die gespeicherte PC-Einstellung wird nicht mehr überschrieben.
- Die bestehende modusabhängige **Einrichtung** und der PC-/Gateway-Wizard aus 0.5.9.29 bleiben unverändert erhalten.

## 0.5.9.29 – Debian-12-Testbuild

- **Einrichtung** ist jetzt in beiden Betriebsarten sichtbar: Funk-Gateway und PC / TeamSpeak.
- Der Inhalt von **Einrichtung** passt sich an die gewählte Betriebsart an.
- Funk-Gateway: Audio, PTT/Modem, RX-Erkennung, TeamSpeak/Mumble, Rufzeichen, Papagei, DTMF, Diagnose und Sicherung.
- PC / TeamSpeak: Desktop-Audio, TeamSpeak/ClientQuery, PC-Papagei, Channel Commander, Selbsttest/Diagnose, Profile und Konfigurationssicherung.
- Der Einrichtungsassistent ist jetzt wirklich modusabhängig.
- PC-Wizard: **Willkommen → Audio → TeamSpeak → Papagei → Channel Commander → Test → Fertig**.
- Der PC-Wizard fragt keine Funkhardware, PTT, RX-Erkennung, Rufzeichen oder DTMF-Funksteuerung ab.
- Gateway-Wizard: **Willkommen → Audio → PTT / Modem → RX-Erkennung → TeamSpeak / Mumble → Rufzeichen / Papagei / DTMF → Gesamttest → Fertig**.
- PC-Selbsttest prüft PC-Audio und TeamSpeak, ohne Funk-Ausgang, Funk-RX oder PTT als Fehler zu melden.
- TeamSpeak-Verbindungstest aktualisiert auch die Statusanzeige im PC-/TeamSpeak-Reiter.
- Versionskennung in `funkgateway/__init__.py` auf 0.5.9.29 korrigiert.
- PTT wird durch den Einrichtungsassistenten niemals automatisch betätigt.
- Shellskripte werden im Debian-12-ZIP mit Unix-Ausführungsrechten gespeichert.

## 0.5.9.28 – Update-Installer und Schnellstarter-Automatik
- Der interne GitHub-Updater kann ein geprüftes Release nach dem Download jetzt automatisch installieren.
- Nach dem Entpacken werden verlorene ZIP-Ausführungsrechte automatisch wiederhergestellt (`+x` für Shell-Skripte).
- Neue Option **„Nach Download automatisch installieren“**.
- Neue Option **„Schnellstarter auf neue Version aktualisieren“**.
- Nach erfolgreicher SHA256-Prüfung startet FunkGateway den passenden Distributions-Installer in einem grafischen Terminal.
- Eine erforderliche `sudo`-Passwortabfrage findet sichtbar im Terminal statt; FunkGateway speichert oder verarbeitet kein sudo-Passwort.
- Nach erfolgreicher Installation kann `install-desktop.sh` automatisch ausgeführt werden.
- Der Desktop-/Menüeintrag zeigt dadurch direkt auf den neuen Versionsordner.
- Die bisherige Version bleibt als Rückfallmöglichkeit erhalten.
- `~/.config/funkgateway-ui` bleibt unverändert und wird von der neuen Version weiterverwendet.
- Wenn kein unterstütztes Terminal gefunden wird, erhält der Benutzer einen klaren manuellen Installationshinweis.

# Changelog

## 0.5.9.28 – Kompaktes und ausführliches Protokoll
- Neue Checkbox **„Ausführliches Log“** im Reiter **Protokoll**.
- Standard ist aus: Die Anzeige konzentriert sich auf wichtige Grundfunktionen.
- Im Kompaktmodus sichtbar bleiben unter anderem PTT EIN/AUS, TeamSpeak-/Mumble-Sprecher, DTMF-Befehle, Papagei-Aufnahme/Wiedergabe, Raum-/Betriebsartwechsel, Schutzfunktionen sowie Warnungen und Fehler.
- Mit aktivierter Checkbox erscheinen zusätzlich technische Ablauf- und Diagnosemeldungen.
- Die gespeicherte Logdatei bleibt immer vollständig; der Haken beeinflusst nur die Bildschirmdarstellung.
- Einstellung wird gespeichert und beim nächsten Start wiederhergestellt.

## 0.5.9.18 – Harte Audio-Isolation im Papageibetrieb
- Praxisfehler behoben: Laufendes TeamSpeak-/Mumble-Audio konnte trotz vorheriger Sperren gemeinsam mit dem Papagei auf HF erscheinen.
- Bei aktivem **„VoIP während Papageibetrieb stummschalten“** wird der komplette `FunkGateway_TX.monitor → Funkgeräte-Ausgang`-Bridge-Ausgang gesperrt.
- Interne Papagei-, Papageibaken- und DTMF-Vollzugsmeldungs-WAVs umgehen in diesem Modus `FunkGateway_TX` und werden direkt auf den gewählten Funkgeräte-Ausgang gespielt.
- Die Sink-Input-Stummschaltung bleibt als zweite Schutzebene erhalten.
- Feldtest bestätigt die Trennung von laufendem TeamSpeak und Papagei-Aussendung.

## 0.5.9.17 – Zusätzliche VoIP-Sink-Input-Sperre
- Bekannte VoIP-Sink-Inputs auf `FunkGateway_TX` werden im Papageibetrieb tatsächlich stummgeschaltet.
- Erfasst werden TeamSpeak, Mumble, FRN, Zello und Discord.
- Neue Wiedergabestreams werden vom Routing-Wächter ebenfalls berücksichtigt.
- Beim Verlassen des Papageibetriebs werden nur Streams wieder freigegeben, die FunkGateway selbst stummgeschaltet hat.

## 0.5.9.16 – PTT-Nachlauf für Vollzugsmeldungen
- Einstellbarer PTT-Nachlauf nach Ende der Vollzugsmeldungs-WAV.
- Standardwert 2500 ms, Wertebereich 0 bis 5000 ms.
- Verhindert, dass im virtuellen PipeWire/PulseAudio-Pfad gepufferte Audioanteile am Ende abgeschnitten werden.
- Feldtest bestätigt vollständige `*91#`- und `*90#`-Bestätigungen.

## 0.5.9.15 – Vollzugsmeldungs-WAV vollständig abspielen
- Vollzugsmeldungen überwachen den tatsächlichen `paplay`-Prozess.
- PTT bleibt bis zum Ende der WAV aktiv.
- Verhindert abgeschnittene längere Bestätigungsansagen.

## 0.5.9.14 – `*91#` nach Funkende freigegeben
- Fehler behoben, durch den „Papagei aktiv“ nach `*91#` dauerhaft auf Funkende warten konnte.
- DTMF-Steuerträger wird beim Übergang in den Papageibetrieb sauber freigegeben.
- Vollzugsmeldung kann direkt nach Funkende senden.

## 0.5.9.13 – Betriebsart-Bestätigung vor Papagei-Aufnahme
- Betriebsart-Vollzugsmeldungen erhalten Priorität vor einer neuen Papagei-Aufnahme.
- Laufende/stale Papagei-Aufnahmen können für eine DTMF-Bestätigung verworfen werden.
- Neue Papagei-Aufnahme startet erst nach Ende der ausstehenden Betriebsart-Bestätigung.

## 0.5.9.12 – DTMF-ACK-Zustand stabilisiert
- DTMF-Steuerdurchgänge lösen keinen normalen Rogerbeep mehr aus.
- Wartende Betriebsart-Bestätigungen werden entprellt.
- Neuester Betriebsartbefehl gewinnt; ältere wartende Bestätigungen werden verworfen.
- Kanal-frei-Erkennung für Vollzugsmeldungen korrigiert.

## 0.5.9.11 – DTMF/Papagei-Aktivierungsrennen behoben
- `*91#` wird nicht mehr als erster Papagei-Durchgang aufgenommen.
- Papagei wartet nach DTMF-Aktivierung auf echtes Funkende.
- Vorlaufpuffer wird beim Betriebsartwechsel geleert.

## 0.5.9.10 – TOTP-QR-Code
- Lokale QR-Code-Erzeugung aus der aktuellen `otpauth://`-URI.
- Nutzung von `qrencode`, kein externer Webdienst.
- Sicherheitswarnung wegen enthaltenem TOTP-Geheimnis.

## 0.5.9.9 – Schutz des TOTP-Geheimnisses
- Sicherheitsabfrage vor dem Erzeugen eines neuen TOTP-Geheimnisses.
- Standardauswahl ist „Nein“.
- Bestehende Authenticator-Einrichtung bleibt bei Abbruch erhalten.

## 0.5.9.8 – TOTP-AUTH
- TOTP als alternatives AUTH-Verfahren neben statischer PIN.
- RFC-6238-kompatibel, Standard 6 Stellen / 30 Sekunden / Toleranz ±1.
- Replay-Schutz für bereits erfolgreich verwendete Zeitschritte.
- `otpauth://`-URI wird erzeugt.

## 0.5.9.7 – Optionale PIN-AUTH
- DTMF-Befehle können einzeln mit AUTH-Pflicht versehen werden.
- Anmeldung über `*00*PIN#`, Logout über `*00*0#`.
- Zeitlich begrenztes AUTH-Fenster, Fehlversuchsgrenze und Sperrzeit.
- PIN wird mit PBKDF2-HMAC-SHA256 und zufälligem Salt gespeichert.
- AUTH-Daten werden im Log maskiert.

## 0.5.9.3 bis 0.5.9.6 – Funk-Vollzugsmeldungen
- Optionale WAV-Bestätigungen nach ausgeführten DTMF-Befehlen.
- Getrennte Ansagen für Papagei und VoIP sowie allgemeine Bestätigung für weitere Befehle.
- TX-Belegungsprüfung und Fehlerbehandlung stabilisiert.

## 0.5.9.2 – DTMF-Code-Liste als PDF
- Export einer druckbaren DTMF-Code-Liste direkt aus FunkGateway.

## 0.5.9.1 – DTMF-Erkennung verbessert
- Goertzel-Auswertung auf exakte DTMF-Frequenzen.
- Erkennung insbesondere für Ziffer `4` korrigiert.

## 0.5.9.0 – DTMF-Fernsteuerung
- DTMF-Erkennung ausschließlich auf echtem Funk-RX.
- Standardformat `*...#`.
- DTMF-Steuerfolgen werden während der Eingabe nicht zu VoIP übertragen.
- Konfigurierbare Befehle für Papagei/VoIP, TeamSpeak/Mumble Mute/Deaf und je fünf Raumwechsel.

## 0.5.7.0
- Selbstrücklauf-Schutz erweitert.
- Rufzeichenbake und Update-Funktion erweitert.
- Einstellungen und Hilfe ergänzt.

## 0.5.6.20
- Erster öffentlicher GitHub-Release.
- TeamSpeak-/Mumble-Integration, Audio-Routing, PTT, Schutzfunktionen und VoIP-HF-Sprachfilter.
