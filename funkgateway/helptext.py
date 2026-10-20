"""Kategorisierte FunkGateway-Hilfe in einfacher Sprache (Linux und Windows).

Keine externen Bilder oder Webdienste erforderlich.
"""
def build_help_html(platform="linux"):
    windows = str(platform).lower().startswith("win")
    specific = ("""<p><b>Windows:</b> Audio wird über Windows-Soundgeräte und zum Teil WASAPI verarbeitet.
    COM-Ports steuern RTS oder DTR. Manche Schutzfunktionen des Linux-Originals sind noch
    nicht vollständig auf Windows übertragen. Ein als <i>experimentell</i> bezeichneter
    Rücklaufschutz schützt bislang nicht alle Audio-Wege. Er ersetzt keine Funkaufsicht.</p>"""
    if windows else """<p><b>Linux:</b> FunkGateway nutzt unter anderem ALSA, PulseAudio beziehungsweise
    PipeWire sowie virtuelle Audio-Geräte. Die automatische Umleitung unterstützt den
    Gateway- und Papagei-Betrieb. Manche Funktionen hängen von der Installation und
    den Rechten des Betriebssystems ab.</p>""")
    sections = [
    ("start", "1. FunkGateway für Einsteiger", """
      <p>FunkGateway verbindet Programme für Sprache über das Internet mit einer Funkanlage.
      Es kann auch als normaler PC-Funkclient oder als Papagei arbeiten.
      <b>PTT</b> bedeutet: die Sprechtaste schaltet den Sender ein.
      <b>RX</b> bedeutet: ein Funksignal wird empfangen.
      <b>TX</b> bedeutet: ein Signal wird gesendet.</p>
      <ol>
      <li>Wähle zuerst die Betriebsart <b>PC-User</b> und teste Audio ohne Funkgerät.</li>
      <li>Verbinde genau einen Dienst, zum Beispiel FRN oder Mumble.</li>
      <li>Prüfe Mikrofon, Lautsprecher und Pegel. Sprich leise und normal.</li>
      <li>Wechsle erst dann auf <b>Funk-Gateway</b> und wähle den richtigen RX-Eingang und TX-Ausgang.</li>
      <li>Nutze bei der PTT zuerst den <b>Test-Modus</b>, ohne eine Funkanlage anzuschließen.</li>
      <li>Erst wenn alles stimmt, wähle die tatsächliche serielle Steuerung und teste kurz.</li>
      <li>Aktiviere Schutzfunktionen und kontrolliere, ob die PTT nach jeder Sendung abfällt.</li>
      </ol>
      <p><b>Wichtig:</b> Ein Häkchen oder eine grüne Statusanzeige beweist noch nicht,
      dass am Funkgerät wirklich Audio oder PTT ankommt. Teste mit einem zweiten
      Empfänger und halte geltende Funkregeln ein.</p>"""),
    ("modes","2. Die vier Betriebsarten","""
      <p><b>PC-User:</b> Du sprichst selbst über Mikrofon und PTT. Das ist der richtige
      Modus zum Kennenlernen der Integrationen. Die Mumble-PC-PTT lässt sich aktivieren
      und wieder ausschalten.</p>
      <p><b>Funk-Gateway:</b> Stimmen aus dem Internet gehen zum Funkgerät.
      Funksignale gehen zurück ins Internet. Die normalen Sendetasten der PC-Benutzer
      dürfen hier nicht gleichzeitig die automatische Funksteuerung auslösen.</p>
      <p><b>Funk-Papagei:</b> Das Gerät nimmt einen Funkdurchgang auf und gibt ihn
      nach dem Ende über Funk wieder. Wartezeit, Vorlauf und maximale Aufnahmedauer
      verhindern zu schnelle oder zu lange Antworten.</p>
      <p><b>VoIP-Papagei:</b> Nimmt Sprache aus einem Internet-Sprachdienst auf und
      spielt sie anschließend wieder ab. Die geeignete Audioquelle hängt vom
      jeweiligen System und Dienst ab.</p>"""),
    ("audio","3. Audio – Quellen, Pegel und Fehlersuche","""
      <p><b>Eingang:</b> Hier kommt Sprache her, zum Beispiel von der USB-Soundkarte
      des Funkempfängers. <b>Ausgang:</b> Hier geht Sprache hin, zum Beispiel zur
      Funkanlage. Eingang und Ausgang dürfen nicht versehentlich in einer
      Rückkopplungs-Schleife verbunden werden.</p>
      <p><b>Schwelle:</b> Ein Signal gilt erst ab einer bestimmten Lautstärke als aktiv.
      Der Pegel wird oft in <b>dBFS</b> angezeigt. Nahe 0 dBFS ist sehr laut.
      Ein Wert wie −40 dBFS ist deutlich leiser.</p>
      <p><b>Hysterese:</b> Die Einschaltschwelle ist höher als die Ausschaltschwelle.
      Dadurch flattert die PTT nicht, wenn der Pegel leicht schwankt.</p>
      <p><b>Haltezeit / Hang:</b> Die PTT bleibt nach kurzen Sprachpausen
      noch einen Moment aktiv. <b>Mindest-TX-Zeit:</b> Sehr kurze Impulse
      führen nicht sofort zu einem hektischen An- und Abschalten.</p>
      <p><b>Vorlauf / Preroll:</b> Speichert etwas Audio vor dem eigentlichen
      Erkennen des Signals. So wird der Wortanfang weniger leicht abgeschnitten.</p>
      <p><b>Verstärkung:</b> Zu wenig Pegel ist kaum verständlich; zu viel Pegel
      verzerrt. Erhöhe die Lautstärke vorsichtig. Vermeide Clipping.</p>
      <p><b>Linux:</b> Virtuelle PulseAudio-/PipeWire-Wege übernehmen bei unterstützten
      Betriebsarten einen Teil des Routings. <b>Windows:</b> Windows-Audiogeräte
      und WASAPI-Loopback können benutzt werden. Nicht jedes Programm lässt sich
      automatisch auf denselben Audioweg umleiten.</p>
      <p><b>Echo oder Hall?</b> Prüfe, ob die Wiedergabe im Sprachdienst und im
      Windows- oder Linux-Mixer gleichzeitig verstärkt wird. Kontrolliere, ob
      der Ausgang versehentlich als Eingang aufgenommen wird.</p>"""),
    ("radio","4. Funkgerät, PTT, COM-Port und RX","""
      <p><b>Serielle PTT:</b> FunkGateway schaltet über RTS oder DTR eine Leitung
      am seriellen Anschluss. Wähle den passenden Port und die vom Interface
      benötigte Leitung. <b>Invertieren</b> kehrt die Schaltlogik um.
      Eine falsche Einstellung kann dazu führen, dass der Sender dauerhaft sendet.</p>
      <p><b>COS / Squelch:</b> Zeigt an, ob die Empfangsseite belegt ist.
      Es kann ein Hardware-Signal oder eine Erkennung durch Audiolautstärke
      verwendet werden. Kurze Störimpulse sollten keinen gültigen Funkdurchgang auslösen.</p>
      <p><b>RX-Bestätigung:</b> Das Signal muss eine Mindestzeit anliegen.
      <b>RX-Nachlauf:</b> Kurze Sprechpausen beenden den Durchgang nicht sofort.</p>
      <p><b>Rogerbeep:</b> Ein kurzer Ton nach einem Durchgang.
      Je nach Version sind CW-K, Tonfolgen oder eigene WAV-Dateien verfügbar.
      Halte Lautstärke und Häufigkeit niedrig, damit keine Schleife entsteht.</p>
      <p><b>Rufzeichenbake:</b> Sendet in bestimmten Abständen ein Rufzeichen
      oder eine aufgenommene Ansage. Das ist kein Ersatz für die Prüfung,
      welche Identifikationspflichten für deine Funkanwendung gelten.</p>
      <p><b>TOT:</b> Maximale Sendedauer. Der Sender wird bei zu langer PTT
      abgeschaltet. <b>NOT-AUS:</b> Die Sendefreigabe wird sofort beendet.
      Beide Funktionen gehören zu jedem längeren Test.</p>"""),
    ("frn","5. FRN – Räume, Benutzer und Senden","""
      <p>FRN verbindet mehrere Benutzer und Gateways über einen Server.
      Trage Server, Raum und die nötigen Zugangsdaten ein. Verbinde dich.
      Die Teilnehmerliste zeigt, wer im Raum ist.</p>
      <p>Für den <b>PC-User</b> kannst du eine manuelle PTT-Taste oder einen
      Hotkey einstellen. Bei einer Integration in ein automatisches Gateway
      darf der eigene PC-Hotkey keine zweite Aussendung auslösen.
      Nutze das eingebaute Chatfenster, falls der Server es unterstützt.</p>
      <p>Wenn keine Sprache zu hören ist: Verbindung, richtige Raumwahl,
      Ausgabe-Gerät und lokale Stummschaltung prüfen.</p>"""),
    ("mumble","6. Mumble – Client, Channels, Rechte und PTT","""
      <p>Mumble bietet Sprachräume, die hier <b>Channels</b> heißen.
      Du kannst einem Server beitreten, einen Channel auswählen,
      Nachrichten schreiben und – mit passenden Serverrechten –
      Räume oder Benutzer verwalten.</p>
      <p>Der integrierte Mumble-Client kann unter unterstützten Plattformen
      selbst eine Verbindung aufbauen. Ein Mumble-Zertifikat hilft bei der
      dauerhaften Identität. Zugangstoken für geschützte Räume sind nicht
      dasselbe wie ein Serverpasswort.</p>
      <p><b>Eigene Stummschaltung</b> verhindert, dass dein Mikrofon sendet.
      <b>Taub schalten</b> bedeutet, dass du nichts mehr hörst.
      Berechtigungen für Administration, Bannlisten und Raumänderungen
      hängen von den Serverrechten ab.</p>
      <p><b>PC-User-Mumble-PTT:</b> Die Option „PC-User Mikrofon-PTT aktiv“
      muss eingeschaltet sein. Danach kannst du die PTT drücken.
      Dies sollte bei aktuellen Versionen auch nach dem Verbinden gehen.
      Wenn die Sprechanzeige nicht reagiert: Mikrofon, eigene Mute-/Deaf-Schaltung,
      Berechtigungen und Verbindungsstatus prüfen.</p>
      <p>Bei einem Verbindungsabbruch können alte Teilnehmerdaten kurz sichtbar
      bleiben. Verlasse dich deshalb nicht allein auf die Channel-Liste
      als Nachweis einer funktionsfähigen Verbindung.</p>"""),
    ("ts","7. TeamSpeak und das FunkGateway-Audio-Bridge-Plugin","""
      <p>Die TeamSpeak-Integration kann den aktiven Raum, Benutzer und
      Sprecher anzeigen und – wenn die Rechte passen – den Gateway-Client
      in einen anderen Channel bewegen. <b>ClientQuery</b> dient zur Steuerung
      des TeamSpeak-Clients. Es ist nicht die Audio-Übertragung.</p>
      <p><b>Das FunkGateway TeamSpeak 3 Audio Bridge Plugin (Windows):</b>
      Es übernimmt Funk-Audio direkt von FunkGateway und speist es als
      Mikrofon-Audio in TeamSpeak 3 ein. Die Verbindung läuft nur lokal
      auf dem PC über UDP-Port 39582 (127.0.0.1).
      Während Audio eingespeist wird, benutzt das Plugin vorübergehend
      die laufende Sprachübertragung und stellt anschließend den vorherigen
      PTT- oder Sprachaktivierungsmodus wieder her.</p>
      <ol>
      <li>Installiere das zu deinem Windows-Release gehörende Plugin.</li>
      <li>Starte TeamSpeak 3 danach neu und aktiviere das Plugin.</li>
      <li>Wähle im FunkGateway die <b>TeamSpeak-Plugin-Brücke</b>, wenn sie
      für deinen Aufbau vorgesehen ist.</li>
      <li>Prüfe die Plugin-Verbindung und wähle den Funk-RX-Eingang.</li>
      <li>Teste mit einem kurzen Funkdurchgang, ob im richtigen
      TeamSpeak-Channel wirklich Audio ankommt.</li>
      </ol>
      <p><b>Wichtig:</b> Das Plugin ersetzt nicht ClientQuery. Beide haben
      unterschiedliche Aufgaben. Ein Plugin-Status „bereit“ bedeutet
      nicht automatisch, dass die PTT des Funkgeräts richtig arbeitet.
      Das Plugin ist für TeamSpeak 3 gedacht, nicht automatisch für
      jede andere TeamSpeak-Version.</p>
      <p><b>Channel Commander:</b> Kann bei Funk-RX gesetzt werden,
      sofern der verwendete Client dies unterstützt und richtig konfiguriert ist.</p>"""),
    ("other","8. Zello und weitere Integrationen","""
      <p><b>Zello-Zugang:</b> Für die Zello-Channel-API brauchst du
      einen Zello-Benutzernamen, das passende Passwort, den Kanalnamen
      und einen API-Token. Den Token musst du bei
      <a href="https://developers.zello.com/">developers.zello.com</a>
      beantragen oder einrichten. Klicke in der Zello-Integration
      auf „Neuen API-Token anfordern“. Das ist eine externe Webseite.
      Trage den erhaltenen Token danach in FunkGateway ein.
      Bewahre Passwort und Token sicher auf und teile sie nicht mit anderen.</p>
      <p><b>Wichtig:</b> Zello nutzt eine eigene Channel-API.
      Je nach Version sind einzelne Funktionen noch Alpha oder eingeschränkt.
      Ein erfolgreicher Login bedeutet nicht, dass bereits eine vollständige
      Audioübertragung über alle Zello-Wege vorhanden ist.</p>
      <p>Zello und andere Sprachprogramme können je nach unterstützter
      Schnittstelle eingebunden sein. Prüfe zuerst deren Verbindung,
      Audiogeräte und eigene Sendetaste. Eine Verbindung allein bedeutet
      nicht, dass Funk-Audio korrekt weitergereicht wird.</p>
      <p>Bei einer Verbindung zu einem automatischen Gateway müssen
      manuelle PC-PTT und automatische Funk-PTT klar getrennt bleiben.
      Nicht jede Integration unterstützt dieselben Raum-, Chat-,
      Sprecher- oder Administrationsfunktionen.</p>"""),
    ("parrot","9. Papagei, Aufnahmen, CW und DTMF","""
      <p><b>Funk-Papagei:</b> Nimmt ein empfangenes Signal auf und gibt es
      erst nach dem Ende des Durchgangs wieder. Stelle eine maximale
      Aufnahmezeit ein. Ein kurzer Vorlauf schützt den Wortanfang.
      Die Verzögerung vor dem Abspielen verhindert ein zu frühes Senden.</p>
      <p><b>VoIP-Papagei:</b> Funktioniert ähnlich, verwendet aber
      Audio aus einem Internet-Sprachdienst. Prüfe besonders,
      dass Wiedergabe nicht direkt wieder zur Aufnahme wird.</p>
      <p><b>CW:</b> Morsezeichen, zum Beispiel für ein Rufzeichen.
      <b>DTMF:</b> Töne von Telefontastaturen, mit denen bestimmte
      Befehle ausgelöst werden können. Nutze Zugangsschutz, sofern vorhanden.
      Teste Fernsteuerbefehle zunächst ohne echte Hardware-PTT.</p>"""),
    ("safety","10. Schutz und unbeaufsichtigter Betrieb","""
      <p><b>Rücklaufschutz:</b> Nach eigener Funk-Aussendung kann ein kurzes
      Signal über den Empfänger zurückkommen. Wird es wieder ins Internet
      gesendet, entsteht möglicherweise eine Endlosschleife.
      Ein Schutzfenster kann solche Rückläufe erkennen und unterdrücken.</p>
      <p><b>Ein langer neuer Funkdurchgang ist nicht automatisch ein Rücklauf.</b>
      Er muss anders behandelt werden als ein kurzer Impuls.
      Die Schutzfunktion darf Funker nicht unnötig aussperren.</p>
      <p><b>Wiederholte Rückläufe:</b> Können eine Abschaltung auslösen.
      <b>Dauer-RX:</b> Ein dauernd offener Empfänger darf nicht endlos
      Sprache ins Netz übertragen. <b>TOT:</b> Verhindert eine
      dauerhaft eingeschaltete Funk-PTT.</p>
      <p><b>Linux:</b> Die Originalversion besitzt umfangreichere Schutz-
      und Störungsraumfunktionen. <b>Windows:</b> Ein als experimentell
      gekennzeichneter Rücklaufschutz ist noch nicht auf sämtliche
      Audio-Wege ausgedehnt. Deshalb kann nicht jeder Rücklauf sicher
      abgefangen werden.</p>
      <p><b>Unattended = ohne Bediener:</b> Ein unbeaufsichtigter Sender
      braucht verlässliche Hardware, unabhängige Begrenzungen, sichere
      Verbindungserkennung und Tests unter realistischen Fehlerbedingungen.
      Nutze die Software nicht als alleinige Sicherheitseinrichtung.
      Für Tests nach Änderungen bleibe am Funkgerät und prüfe,
      dass bei Strom-, Netzwerk- oder Programmfehlern keine PTT hängen bleibt.</p>"""),
    ("problems","11. Wenn etwas nicht funktioniert","""
      <p><b>Ich höre niemanden:</b> Verbindung, Raum, Lautsprecher,
      Ausgabe-Auswahl, eigene Taubschaltung und Windows-/Linux-Lautstärke prüfen.</p>
      <p><b>Andere hören mich nicht:</b> PTT-Freigabe, Mikrofon, Eingangspegel,
      Mute, Serverrechte und tatsächlichen Sendestatus prüfen.</p>
      <p><b>Die PTT hängt:</b> NOT-AUS betätigen, Funkgerät ausschalten,
      serielle Leitung und invertierte PTT-Logik prüfen. Erst ohne
      angeschlossene Funkanlage erneut testen.</p>
      <p><b>Audio hallt:</b> Doppeltes Routing, Monitor-Funktion,
      Echo vom Lautsprecher ins Mikrofon und die Mischung von
      Anwendung und System-Audio überprüfen.</p>
      <p><b>TeamSpeak-Plugin sendet nicht:</b> TeamSpeak 3 neu starten,
      Plugin aktivieren, lokale Erreichbarkeit kontrollieren und prüfen,
      ob die Audio-Bridge statt einer bloßen ClientQuery-Verbindung
      eingeschaltet ist.</p>
      <p><b>Nach einem Update:</b> Versionsnummer ansehen,
      Einstellungen kontrollieren, erst im Testbetrieb starten und
      Fehlermeldungen im Log notieren.</p>"""),
    ("glossary","12. Wörterbuch – Fachwörter einfach erklärt","""
      <p><b>Gateway:</b> Brücke zwischen Funk und Internet.
      <b>PTT:</b> Sprechtaste / Sender einschalten.
      <b>RX:</b> Empfang. <b>TX:</b> Senden.
      <b>COS:</b> Anzeige, dass der Funkkanal belegt ist.
      <b>Squelch:</b> Rauschsperre des Empfängers.
      <b>VOX:</b> Senden oder Erkennen durch Sprachlautstärke.
      <b>Hang:</b> Nachlaufzeit. <b>Hysterese:</b> Unterschied zwischen
      Ein- und Ausschaltschwelle. <b>TOT:</b> Abschaltung nach zu
      langer Sendezeit. <b>DTMF:</b> Fernsteuertöne.
      <b>CW:</b> Morsezeichen. <b>WAV:</b> Audiodatei.
      <b>COM-Port:</b> Serieller Anschluss unter Windows.
      <b>RTS/DTR:</b> Elektrische Steuerleitungen eines seriellen Anschlusses.
      <b>WASAPI:</b> Windows-Technik zur Audioaufnahme und -wiedergabe.
      <b>Loopback:</b> Aufnahme von Audio, das der Computer gerade abspielt.
      <b>ClientQuery:</b> Steuerschnittstelle von TeamSpeak 3.
      <b>Unattended:</b> Betrieb ohne ständig anwesenden Bediener.</p>""")
    ]
    menu = " · ".join('<a href="#%s">%s</a>' % (key, title) for key,title,_ in sections)
    content = "".join('<a name="%s"></a><h2>%s</h2>%s<p><a href="#oben">↑ Zur Übersicht</a></p><hr>' % (key,title,body) for key,title,body in sections)
    return ("""<html><body><a name="oben"></a>
      <h1>FunkGateway – Handbuch in einfacher Sprache</h1>
      <p><b>FunkGateway für Einsteiger:</b> von der ersten Verbindung
      bis zum Funk-Gateway. Für Linux und Windows.</p>
      <p><b>Kapitel auswählen:</b> """+menu+"""</p><hr>"""+specific+content+"""</body></html>""")

HELP_HTML = build_help_html("linux")
