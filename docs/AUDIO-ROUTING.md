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

Die Anwendung selbst muss keine serielle PTT unterstützen. Sie muss nur ihren Wiedergabeausgang auf `FunkGateway_TX` stellen können.


## RX capture device (0.5.5)
`funkgateway_rx.monitor` is automatically remapped to the regular capture source `funkgateway_rx_source`, shown to desktop clients as **FunkGateway_RX_Input**. This avoids clients that do not enumerate monitor sources reliably.
