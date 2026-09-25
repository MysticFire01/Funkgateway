# Changelog

## 0.5.9.20 – Update-Installer und Schnellstarter-Automatik
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

## 0.5.9.19 – Kompaktes und ausführliches Protokoll
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