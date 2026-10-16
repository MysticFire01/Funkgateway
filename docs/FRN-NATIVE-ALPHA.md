# FRN Native – Alpha in FunkGateway UI 0.6.0

Die native FRN-Unterstützung ist direkt unter **Integrationen → FRN · Alpha** eingebaut. Sie ergänzt TeamSpeak und Mumble und ersetzt diese Integrationen nicht.

## Enthalten

- FRN-SystemManager-Liste für DE Alternative, DE Original und Russland
- Serversuche und getrennte Auswahl von Server und Raum
- manuelle Raumeingabe für nicht veröffentlichte Räume
- direkte Raumliste des verbundenen Servers über `NET_NAMES`
- Raumwechsel ohne Verlust des vorgemerkten Zielraums
- Teilnehmerliste mit Live-Funkstatus
- getrennte FRN-RX- und FRN-TX-Pegel
- native GSM 06.10 WAV49 Audioverbindung
- globale FRN-PTT im PC-User-Modus
- PTT wahlweise Halten oder Klick/Verriegelung
- optionale, frei einstellbare automatische TX-Abschaltung
- im Funk-Gateway-Modus keine manuelle FRN-PTT oder Verriegelung
- FRN-Zustand in der globalen Statusleiste und im Systemstatus

## Teilnehmerstatus

- **Grün:** Teilnehmer ist verbunden und idle.
- **Rot:** anderer Teilnehmer spricht; der Sprecher wird vom FRN-Server gemeldet.
- **Orange:** FunkGateway selbst sendet gerade, entweder per PC-User-PTT oder durch Gateway-TX.

Der eigene Eintrag wird beim TX lokal sofort orange dargestellt und muss nicht auf eine verzögerte Sprecher-Rückmeldung des Servers warten.

## Aktuelle Raumbelegung

Für den **aktuell verbundenen Raum** wird die Client-Zahl direkt aus der empfangenen FRN-Teilnehmerliste aktualisiert.

Die Belegung der **anderen Räume** wird etwa alle **20 Sekunden** schonend über den ausgewählten FRN-SystemManager nachgeladen. Dabei bleiben Serverauswahl, Raumwahl und die laufende FRN-Verbindung erhalten. Räume, die nur über `NET_NAMES` bekannt sind und für die der SystemManager keine Zahl liefert, werden mit `–` angezeigt.

## Client-Klasse und VX

Standardmäßig wählt FunkGateway die FRN-Client-Klasse passend zur Betriebsart:

- **PC-User:** PC Only, `CL=2`
- **Funk-Gateway:** Gateway, `CL=1`

Die Auswahl kann für legitime Kompatibilitätstests manuell geändert werden. FunkGateway gibt sich dabei nicht als fremder offizieller Client aus.

Standard-VX der aktuellen V6-Alpha: `20261016`.

Beim ersten Login-Schritt werden sowohl klassische FRN-Antworten als auch Servervarianten unterstützt, die die konfigurierte VX-Kennung exakt zurückspiegeln.

## Trennen und Raumwechsel

Ein echter Klick auf **Trennen** leert sitzungsbezogene Daten wie Teilnehmer, aktiven Sprecher, direkte Server-Raumliste und Pegel. Die globale Serverliste, der Netzwerkfilter und die Serversuche bleiben verfügbar.

Ein interner Disconnect für einen Raumwechsel löscht den vorgemerkten Zielraum nicht. Wird der bereits aktive Raum durch Auswahl oder Listen-Refresh erneut ausgelöst, wird dies still ignoriert und nicht mehrfach geloggt.

## Alpha-Hinweis

Die native FRN-Protokoll- und Audioanbindung ist weiterhin experimentell. Unterschiedliche FRN-Serverversionen können sich im Handshake und in Zusatzfunktionen unterscheiden. Für GSM 06.10 WAV49 wird unter Debian `libgsm1` benötigt; der Installer installiert dieses Paket mit.
