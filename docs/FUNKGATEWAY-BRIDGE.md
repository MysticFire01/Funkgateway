# FunkGateway Mumble Bridge

## Für normale Gatewaybetreiber

Im FunkGateway unter **Integrationen → Mumble** den Modus **Bridge des Server-Admins (Normalnutzer)** auswählen.

Vom Admin werden nur benötigt:

1. HTTPS-Adresse der Bridge
2. persönliches `fgw_...`-Token

Das Murmur-Ice-Read-/Write-Secret darf nicht an normale Gatewaybetreiber ausgegeben werden.

Ist beim Admin noch keine Bridge vorhanden, kann im FunkGateway das mitgelieferte **Admin-Paket gespeichert und weitergegeben** werden.

## Für Server-Admins / eigene Server

Admins können alternativ Direktes Ice oder Ice über SSH nutzen. Dann werden passende `Murmur.ice`, Ice-Port und Secrets benötigt. Secrets werden nicht in `config.json` persistiert.

## Sicherheitsmodell der Bridge

Die Bridge bindet jedes Token serverseitig an genau einen Gateway-Benutzer sowie einen Normal- und einen Störungsraum. Der Client kann keine beliebigen Benutzer oder Channels übergeben.

Eine Bridge mit echtem Ice-Secret gehört auf einen vom Server-Admin kontrollierten Rechner. Eine lokale Bridge auf einem untrusted Funkrechner würde das globale Secret nicht zuverlässig vor dessen Besitzer schützen.
