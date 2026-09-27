# Audio-Routing

`FunkGateway_TX` ist ein virtueller **Ausgang**.

Signalweg:

```text
TeamSpeak / Mumble / FRN
          |
          v
   FunkGateway_TX
          |
          +--> Audio erkannt --> PTT EIN
          |
          v
 echte Soundkarte zum Funkgerät
          |
          v
       Funkgerät
```

Die VoIP-Anwendung kann Ein- und Ausgabe auf **Standard/Default** lassen. FunkGateway erkennt unterstützte VoIP-Streams und verschiebt sie je nach Betriebsart automatisch auf `FunkGateway_TX` bzw. `FunkGateway_RX_Input`. Beim Wechsel auf PC-User werden sie wieder auf die aktuellen System-Defaults geroutet.


## RX capture device (0.5.5)
`funkgateway_rx.monitor` is automatically remapped to the regular capture source `funkgateway_rx_source`, shown as **FunkGateway_RX_Input**. This is an internal routing target; supported VoIP clients normally remain configured to **Default** input/output and are moved automatically by FunkGateway.
