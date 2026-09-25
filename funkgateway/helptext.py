"""Simple in-app help for FunkGateway UI."""

HELP_HTML = r"""
<h2>FunkGateway – Hilfe in einfacher Sprache</h2>
<p>Diese Hilfe erklärt die wichtigsten Funktionen ohne Fachsprache. Wenn du etwas nicht brauchst, kannst du es einfach ausgeschaltet lassen.</p>

<h3>1. Schnellstart</h3>
<ol>
<li>Unter <b>PTT / Modem</b> zuerst den Testmodus benutzen.</li>
<li>Unter <b>Audio-Automatik</b> den echten Ausgang zum Funkgerät wählen.</li>
<li>Unter <b>RX / Rogerbeep</b> die Funk-Empfangsquelle wählen.</li>
<li>In TeamSpeak, Mumble oder FRN <b>FunkGateway_TX</b> als Lautsprecher-Ausgang wählen.</li>
<li>Für Funk → Computer <b>FunkGateway_RX_Input</b> als Mikrofon-/Aufnahmequelle wählen.</li>
<li>Gateway starten und Pegel/Status beobachten.</li>
</ol>

<h3>2. Audio-Automatik</h3>
<p><b>FunkGateway_TX</b> ist der virtuelle Ausgang für TeamSpeak, Mumble, FRN und ähnliche Programme. Alles, was dort abgespielt wird, kann zum Funkgerät weitergegeben werden.</p>
<p><b>TX-Verstärkung</b> macht Computer-Audio in Richtung Funk lauter oder leiser. Wenn die Clipping-Anzeige anschlägt, ist der Pegel zu hoch.</p>
<p><b>FunkGateway_RX_Input</b> ist die virtuelle Aufnahmequelle für den Rückweg Funk → Computer. Sie wird automatisch angelegt.</p>

<h3>3. RX / Rogerbeep</h3>
<p><b>RX-Erkennungsschwelle</b>: Ab diesem Pegel gilt ein Funksignal als empfangen.</p>
<p><b>RX-Hysterese</b>: Verhindert, dass der Status an der Schwelle ständig zwischen Signal und Frei wechselt.</p>
<p><b>Mindestdauer gültiges RX-Signal</b>: Sehr kurze Knackser werden ignoriert.</p>
<p><b>RX-Nachhaltezeit</b>: Kurze Sprachpausen werden nicht sofort als Ende des Durchgangs gewertet.</p>
<p><b>RX-Sperrzeit nach Rogerbeep</b> und <b>Cooldown</b>: Schützen vor Rogerbeep-Schleifen und Squelch-Tail-Impulsen.</p>
<p>Der Rogerbeep kann als CW-K, Einzelton, Doppelton oder eigene WAV-Datei gesendet werden.</p>

<h3>4. PTT und Sicherheit</h3>
<p><b>PTT</b> schaltet den Sender. Mit <b>PTT testen</b> kann die Steuerung geprüft werden.</p>
<p><b>TOT</b> ist die maximale Sendezeit. Wenn PTT zu lange eingeschaltet bleibt, beendet FunkGateway die Sendung automatisch. Das schützt vor Dauersendungen.</p>
<p><b>NOT-AUS</b> schaltet PTT sofort aus.</p>

<h3>5. Rufzeichen, CW und DTMF</h3>
<p>Die Rufzeichenansage kann als WAV-Datei gewählt oder direkt aufgenommen werden. Das Intervall bestimmt, wie oft sie automatisch gesendet wird.</p>
<p>CW erzeugt Morsezeichen. DTMF erzeugt Mehrfrequenztöne.</p>

<h3>6. TeamSpeak-Integration</h3>
<p>Das TeamSpeak-Modul ist <b>optional</b>. Ist es ausgeschaltet oder nicht erreichbar, arbeitet FunkGateway normal weiter.</p>
<p>Benötigt wird beim klassischen TeamSpeak-3-Client das ClientQuery-Plugin. Standard ist <code>127.0.0.1:25639</code>.</p>
<p><b>Aktueller Sprecher</b>: FunkGateway zeigt den sprechenden Benutzer im aktuellen TeamSpeak-Channel an. Sprecher in anderen Channels werden nicht angezeigt.</p>
<p><b>Channel Commander bei Funk-RX</b>: Wenn auf der Funkseite ein gültiger Durchgang erkannt wird, kann FunkGateway Channel Commander einschalten. Nach RX-Ende wird er wieder ausgeschaltet.</p>
<p><b>Aktiver Channel</b>: Zeigt, in welchem TeamSpeak-Raum der Gateway-Client gerade ist.</p>
<p><b>Gateway verschieben</b>: Lädt die sichtbaren Channels und verschiebt nur den eigenen Gateway-Client in den ausgewählten Raum.</p>

<h3>7. Schutzfunktionen</h3>
<p>Alle Schutzfunktionen sind optional und befinden sich im Reiter <b>Schutz</b>. Ohne gesetzten Haken arbeitet FunkGateway wie bisher.</p>

<h4>Dauer-RX-Schutz</h4>
<p>Wenn auf der Funkseite sehr lange ein Signal anliegt, kann FunkGateway automatisch stummschalten. Das schützt vor Dauerträgern oder Störungen.</p>
<p><b>Dauer-RX erkannt nach</b>: Nach dieser Zeit wird der Schutz ausgelöst, zum Beispiel nach 180 Sekunden.</p>
<p>Beim Schutz werden Funk → Computer und die normale PTT-Weitergabe gemutet. Eine eigene WAV-Datei kann einmal über Funk abgespielt werden, zum Beispiel „Gateway gemutet“.</p>

<h4>Automatische Wiederaktivierung</h4>
<p>Optional kann sich FunkGateway nach einer einstellbaren Zeit selbst wieder aktivieren.</p>
<p>Mit <b>Nur wieder aktivieren, wenn Funk-RX stabil frei war</b> wartet FunkGateway zusätzlich auf ein wirklich stabiles Ende des Störträgers. Ein sehr kurzer „Frei“-Impuls reicht nicht mehr aus.</p>
<p><b>Stabil frei für</b>: So viele Sekunden muss Funk-RX ohne Unterbrechung frei bleiben. Kommt wieder ein Signal, beginnt die Zeit von vorn.</p>
<p><b>Anzeige während des Schutzes:</b> Solange das Gateway wegen Dauer-RX gemutet bleibt, zeigt die Startseite nicht einfach „FUNK KANAL FREI“. Stattdessen steht dort zum Beispiel „Störung weiterhin vorhanden“, „Störung noch nicht geklärt“ oder „Prüfe, ob Störung beendet ist …“. Erst nach einer echten Freigabe erscheint wieder die normale Kanal-Anzeige.</p>
<p><b>Schutz-Frei-Schwelle</b>: Während der ganzen Frei-Zeit muss der gemessene RX-Pegel unter diesem Wert bleiben. Das verhindert eine Freigabe durch kurze Rauschlöcher bei noch offener Rauschsperre.</p>
<p>Eine eigene WAV-Datei kann bei der Wiederaktivierung abgespielt werden.</p>

<h4>Störungsraum in TeamSpeak</h4>
<p>Für jeden TeamSpeak-Server kann ein eigener Störungsraum gewählt werden. Die Auswahl ist nicht fest im Programm eingebaut.</p>
<p>Mit <b>Ausgewählten Channel als Störungsraum setzen</b> wird der gewählte Raum für den aktuell verbundenen Server gespeichert.</p>
<p>Wenn der Gateway-Client später in diesem Raum ist, kann FunkGateway automatisch stummschalten und eine eigene WAV-Datei senden, zum Beispiel „Gateway im Störungsraum“.</p>
<p>Die Ansage kann nach einem frei einstellbaren Zeitraum wiederholt werden, zum Beispiel alle 10 Minuten.</p>

<h4>Bei Dauer-RX automatisch in den Störungsraum</h4>
<p>Optional kann FunkGateway nach einer Dauer-RX-Abschaltung den eigenen TeamSpeak-Client automatisch in den gespeicherten Störungsraum verschieben.</p>
<p>Der vorherige Channel wird gemerkt. Wenn gewünscht, kehrt FunkGateway nach der Wiederaktivierung automatisch dorthin zurück.</p>
<p>Ist für den aktuellen Server kein Störungsraum gespeichert, bleibt das Gateway einfach im aktuellen Channel. Der normale Schutz funktioniert trotzdem.</p>


<h3>8. Mumble-Integration</h3>
<p><b>Mumble lokal</b> funktioniert ohne Ice und ohne Server-Adminrechte. FunkGateway erkennt, ob Mumble installiert, gestartet und verbunden ist. Angezeigt werden aktueller Server/Channel, Sprecher sowie Mute-/Deaf- und Sendemodus.</p>
<p><b>Bridge des Server-Admins – für normale Gatewaybetreiber:</b> Für automatischen Störungsraum und serverseitige Channel-Steuerung bekommst du vom Mumble-Admin nur zwei Dinge: die HTTPS-Adresse seiner FunkGateway-Bridge und dein persönliches <code>fgw_...</code>-Token. Das globale Ice-Secret darf dir nicht gegeben werden und wird im Bridge-Modus auch nicht benötigt.</p>
<p>Hat dein Server-Admin die Bridge noch nicht eingerichtet, benutze <b>Admin-Paket speichern / weitergeben</b>. Das Paket enthält Bridge-Software, Installationsskript, Diagnose, Tokenverwaltung, Sicherheitsregeln, Reverse-Proxy-Beispiel und eine Schritt-für-Schritt-Anleitung. Der Admin richtet die Serverseite ein und gibt dir anschließend Bridge-Adresse + Token.</p>
<p><b>Direktes Ice / Ice über SSH – nur Adminmodus:</b> Diese Modi sind ausschließlich für den eigenen Server bzw. Server-Administratoren gedacht. Nur hier werden Murmur.ice und Ice Read-/Write-Secret benötigt. Die Secrets werden nicht in <code>config.json</code> gespeichert und nicht protokolliert.</p>
<p><b>Wichtige Sicherheitsregel:</b> Eine Bridge auf dem Funkrechner eines normalen Nutzers schützt ein dort hinterlegtes Ice-Secret nicht. Wer den Rechner kontrolliert, könnte es auslesen. Deshalb muss eine Bridge mit echtem Ice-Secret auf einem vom Server-Admin kontrollierten Server oder Management-Rechner laufen.</p>
<p>Im Bridge-Modus sind freie Channel-Wechsel absichtlich gesperrt. Der Admin bindet dein Token an genau deinen Gateway-Benutzer, Normalraum und Störungsraum. Ein manipuliertes FunkGateway erhält dadurch keine allgemeinen Ice-Rechte.</p>
<p><b>Murmur.ice</b> ist nur im Admin-Ice-Modus nötig und muss zur Servergeneration passen.</p>
<p>Mit <b>Mumble-Komponenten installieren / reparieren</b> installiert FunkGateway auf Ubuntu auf Wunsch lokale Komponenten. Der normale Gateway-Core funktioniert auch, wenn Mumble, Bridge oder Ice nicht verfügbar sind.</p>


<h3>8a. Direktes Ice und SSH (Adminmodus)</h3>
<p>Für Status und Channel-Liste wird das Ice Read-Secret benötigt; für Änderungen wie Channel-Wechsel zusätzlich das Ice Write-Secret. Diese Secrets werden von FunkGateway nicht dauerhaft gespeichert.</p>
<p>Bei SSH sollte ein ED25519-Schlüssel verwendet werden. Erzeuge ihn mit <code>ssh-keygen -t ed25519</code>, übertrage ihn mit <code>ssh-copy-id -p PORT BENUTZER@SERVER</code> und teste die Anmeldung. Ein geschützter Schlüssel kann über <code>ssh-agent</code>/<code>ssh-add</code> entsperrt werden. FunkGateway speichert absichtlich kein SSH-Passwort.</p>
<p>Der komplette Mumble-Reiter ist scrollbar. Falls nicht alle Felder sichtbar sind, innerhalb der Seite nach unten scrollen.</p>

<h3>9. Protokoll und Fehlersuche</h3>

<p>Wichtige Ereignisse werden im Reiter <b>Protokoll</b> und zusätzlich in <code>~/.config/funkgateway-ui/gateway.log</code> gespeichert.</p>
<p>Fehlermeldungen sind kopierbar. Im TeamSpeak-Bereich gibt es zusätzlich <b>TeamSpeak-Status kopieren</b>.</p>
<p>Der Diagnosemodus im RX-Bereich schreibt zusätzliche Informationen über RX-Erkennung und Rogerbeep in das Protokoll.</p>

<h3>10. Tooltips</h3>
<p>Bei vielen neuen Schaltern und Buttons erscheint eine kurze Erklärung, wenn der Mauszeiger darüber bleibt.</p>
"""

# 0.5.9.19 note:
# Mumble Ice/SSH can be stopped from the Integration/Mumble page.  The stop
# action only terminates tunnels started by FunkGateway itself.

# 0.5.9.19:
# Mumble-Störungsraum wird bei Dauer-RX sofort betreten, auch bei offener Rauschsperre.
# Normaler VoIP->RF-Audiopfad wird während Schutz hart stummgeschaltet.
# Schutzansagen werden seriell abgespielt; Mumble-Systemtöne können nicht in RF leaken.
# Ice-Port kann lokal/per SSH automatisch aus Murmur-Konfiguration erkannt werden.
# Venv kann automatisch mit --system-site-packages repariert werden.

# 0.5.9.19 UI-Struktur:
# Schutz -> Allgemein: gemeinsame Dauer-RX-/Wiederanlauf-Logik.
# Schutz -> Ansagen: integrationsneutrale WAVs und Wiederholungsintervall.
# Integrationen -> TeamSpeak: TeamSpeak-Störungsraum und automatischer Raumwechsel.
# Integrationen -> Mumble: Mumble-Störungsraum und automatischer Raumwechsel.
# Damit liegen Integrationsdetails nicht mehr gemischt im allgemeinen Schutzbereich.

# 0.5.9.19:
# - Mumble-Raumwechsel-Schutz: der lokale Mumble-Wiedergabestream wird für 8 s
#   gezielt stummgeschaltet, damit Channel-/Systemtöne oder eine kurze Audio-
#   Rückkopplung nicht die Funk-PTT auslösen. Danach wird nur Mumble wieder
#   freigegeben; andere Audioziele bleiben unverändert.
# - Während dieses Schutzfensters darf die normale Audio-Automatik keine PTT
#   einschalten.
# - Gilt für manuellen Ice-Wechsel, automatischen Störungsraum, Bridge und Rückkehr.
# - Python-Ice-Fehler nennt für Normalnutzer direkt den richtigen Menüweg/Button.
# - Venv-Reparatur läuft im Hintergrund; Qt bleibt reaktionsfähig und Linux sollte
#   deshalb kein "Warten oder Beenden" mehr anzeigen.

# 0.5.9.19:
# - Neuer integrationsneutraler "VoIP-HF-Sprachfilter" (Standard: EIN).
# - Wenn am FunkGateway_TX ausschließlich TeamSpeak/Mumble hängen, wird PTT
#   nur freigegeben, wenn der jeweilige Client live einen echten Sprecher meldet.
# - Mumble nutzt getTalkingUsers; TeamSpeak nutzt ClientQuery-Sprecherstatus.
# - Lokale Hinweis-, Channel-, Mute-/Unmute- und Systemtöne lösen dadurch
#   keine HF-Aussendung aus.
# - Sind andere/nicht-VoIP Programme an FunkGateway_TX angeschlossen, bleibt
#   das generische FunkGateway-Verhalten erhalten.

# 0.5.9.19:
# - Alle Einstellungsseiten sind vertikal scrollfähig.
# - Neuer Selbstrücklauf-Schutz mit frei einstellbaren Standardwerten und
#   getrennten Triggern für VoIP, Bake, Rogerbeep, Schutzansagen und manuelle TX.
# - Lange innerhalb der Rücklaufschutzzeit beginnende Funkdurchgänge werden
#   als verlorener Durchgang erkannt und können eine Wiederholungs-WAV auslösen.
# - Rufzeichenbaken warten auf wirklich freien Funk-/VoIP-Weg. Es gibt nur eine
#   fällige Bake; der Intervalltimer startet erst nach tatsächlichem Bake-Ende.
# - Neue GitHub-Update-Seite mit Releaseprüfung, Paketwahl und SHA256-Prüfung.

# 0.5.9.19:
# - Neuer Papagei-/Echotest-Modus.
# - Funkdurchgang wird aufgenommen und nach Funkende zeitversetzt über HF zurückgesendet.
# - Maximale Aufnahmedauer und Wiedergabeverzögerung sind frei einstellbar.
# - VoIP kann während Papageibetrieb stummgeschaltet werden.
# - Eigene Papageibake ersetzt im Papageibetrieb die normale Rufzeichenbake.
# - Papageibake wartet auf freien Kanal und startet ihren Intervalltimer erst nach tatsächlichem Ende neu.

# 0.5.9.19:
# - Papagei schaltet PTT jetzt vor der WAV-Wiedergabe ein.
# - Eigene PTT-Vorlaufzeit für Papagei frei einstellbar (Standard: 1200 ms).
# - Damit wird der Anfang der Echo-Wiedergabe nicht mehr verschluckt.

# 0.5.9.19:
# - Neuer RX-Vorlaufpuffer für den Papagei (Standard 1500 ms, 0–5000 ms).
# - Der Puffer merkt sich RX-Audio bereits vor der eigentlichen Funkerkennung.
# - So wird der Anfang kurzer Wörter oder Zahlen beim Echo nicht abgeschnitten.
# - RX-Vorlaufpuffer und PTT-Vorlauf sind getrennte Einstellungen.

# 0.5.9.19:
# - Papagei arbeitet während eines Durchgangs exklusiv; VoIP und normale Rogerbeeps funken nicht dazwischen.
# - Optionaler Papagei-Rogerbeep bleibt in derselben PTT-Aussendung.
# - Papageibake schaltet PTT jetzt vor ihrer WAV ein; eigener Vorlauf einstellbar.
# - Selbstrücklauf-Schutz gilt auch vor einer neuen Papagei-Aufnahme.
# - Capture-Wächter verwirft unvollständige Aufnahmen bei einem parec-Ausfall.

# 0.5.9.19:
# - Papagei puffert RX, der noch innerhalb des Selbstrücklauf-Schutzfensters beginnt.
# - Kurze Signale bleiben Rücklauf; lange Signale werden ab der Schwelle "echter Durchgang" zur Papagei-Aufnahme hochgestuft.
# - Der Anfang bleibt durch Vorlauf- und Kandidatenpuffer vollständig erhalten.

# 0.5.9.19:
# - Eigener PTT-Nachlauf für die Papageibake (Standard 800 ms, 0–5000 ms).
# - Bake-Ablauf: PTT EIN -> Vorlauf -> WAV -> Nachlauf -> PTT AUS.
# - Verhindert abgeschnittene Enden der Papageibaken-WAV.

# 0.5.9.19:
# - Neue DTMF-Fernsteuerung aus echtem Funk-RX.
# - * startet standardmäßig die DTMF-Steuersitzung, # beendet sie.
# - DTMF-Töne werden intern erkannt und standardmäßig nicht nach VoIP übertragen.
# - Frei definierbare Codes für Papagei/VoIP, TS/Mumble Mute/Deaf und Raumwechsel.
# - Raumlisten kommen aus TeamSpeak ClientQuery bzw. Mumble Ice/SSH.

# 0.5.9.19:
# - DTMF-Erkennung robuster, insbesondere für die Ziffer 4.
# - Exakte Goertzel-Frequenzen statt gerundeter 20-Hz-Bins.
# - Größere Toleranz für unterschiedliche DTMF-Tonpegel über Funk.

# 0.5.9.19:
# - Neuer PDF-Export im DTMF-Reiter.
# - Druckfertige A4-Liste mit allen aktuellen DTMF-Codes und Raumzielen.

# 0.5.9.19:
# - DTMF-Vollzugsmeldungen über Funk.
# - Separate WAVs für „Papagei aktiv“ und „Gateway/VoIP aktiv“.
# - Optionale Standard-WAV für sonstige DTMF-Befehle.

# 0.5.9.19:
# - Hotfix für die WAV-Auswahl der DTMF-Vollzugsmeldungen.
# - Die drei Dateiauswahl-Buttons verwenden jetzt den vorhandenen WAV-Dateidialog.

# 0.5.9.19:
# - Hotfix für feste DTMF-Codes nach Einführung der Funk-Vollzugsmeldungen.
# - DTMF-Sitzungen werden bei Fehlern jetzt immer sauber beendet.

# 0.5.9.19:
# - Hotfix: DTMF-Vollzugsmeldung wartete wegen falscher PTT-Zustandsprüfung endlos.
# - Sendestatus wird jetzt korrekt über self.tx ausgewertet.

# 0.5.9.19:
# - Optionale DTMF-PIN-AUTH mit zeitlich begrenzter Freigabe.
# - PIN gehasht gespeichert, in Logs maskiert, Fehlversuchs-Sperre.
# - AUTH-Pflicht pro Funktion und pro Raumwechsel einstellbar.

# 0.5.9.19:
# - TOTP als zweites DTMF-AUTH-Verfahren.
# - Authenticator-kompatible otpauth-URI.
# - Replay-Schutz, 6–8 Stellen, Zeitraum/Toleranz einstellbar.

# 0.5.9.19:
# - Sicherheitsabfrage vor dem Überschreiben eines vorhandenen TOTP-Geheimnisses.
# - Standardantwort Nein; bei Abbruch bleibt die bestehende Authenticator-Einrichtung gültig.

# 0.5.9.19: TOTP-QR-Code lokal mit qrencode anzeigen.

# 0.5.9.19:
# - *91# wird beim Einschalten des Papageis nicht mehr mit aufgenommen.
# - „Papagei aktiv“ wartet auf echtes Funkende.
# - Interne DTMF-Vollzugsmeldungen gelangen nicht in den Papagei-Vorlaufpuffer.

# 0.5.9.19:
# - DTMF-Steuerdurchgänge lösen keinen normalen Rogerbeep mehr aus.
# - Vollzugsmeldungen warten auf echte RX/TX-Aktivität, nicht auf rx_was_active.
# - Wartelog entprellt; neuester Betriebsartbefehl verwirft ältere wartende Mode-ACKs.

# 0.5.9.19:
# - Betriebsart-Vollzugsmeldungen haben Vorrang vor neuen Papagei-Aufnahmen.
# - Papagei startet erst nach „Papagei aktiv“ wieder eine Aufnahme.

# 0.5.9.19:
# - Reihenfolge im *91#-Übergang korrigiert.
# - Funkende des DTMF-Steuerdurchgangs wird vor der Pending-ACK-Sperre verarbeitet.
# - „Papagei aktiv“ kann dadurch direkt nach Funkende senden.

# 0.5.9.19:
# - DTMF-Vollzugsmeldungen halten PTT bis zum tatsächlichen Ende von paplay.
# - 500-ms-Tail startet erst nach Ende der WAV; längere „Papagei aktiv“-WAVs werden nicht mehr abgeschnitten.

# 0.5.9.19:
# - Einstellbarer PTT-Nachlauf für DTMF-Vollzugsmeldungen.
# - Standard 2500 ms, um gepuffertes Audio im virtuellen Audio-Pfad nicht abzuschneiden.

# 0.5.9.19:
# - VoIP-Wiedergabestreams werden im Papageibetrieb tatsächlich auf FunkGateway_TX stummgeschaltet.
# - Verhindert TeamSpeak/Mumble-Audio, das sich während Papagei/Bake/ACK in eine HF-Aussendung mischt.

# 0.5.9.19:
# - Harte Papagei-Audio-Isolation: kompletter FunkGateway_TX-Monitor zum Funkgerät stumm.
# - Papagei/Bake/DTMF-ACK laufen im Papageibetrieb direkt zum Funkgeräte-Ausgang.
# - Verhindert Mischbetrieb mit laufendem TeamSpeak/Mumble auf HF.

# 0.5.9.19:
# - Protokollansicht standardmäßig kompakt.
# - Checkbox „Ausführliches Log“ blendet technische Detailmeldungen ein.
# - Die Logdatei auf der Festplatte bleibt immer vollständig.