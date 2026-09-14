# Hardware-Hinweise

PTT-Anschlüsse von Funkgeräten dürfen nicht ungeprüft direkt an PC-Schnittstellen angeschlossen werden. Für serielle RTS/DTR- oder GPIO-Steuerung wird eine geeignete Transistor-/Optokoppler-Schaltung empfohlen.

Unterstützte Gerätenamen:
- echte serielle Ports: `/dev/ttyS*`
- USB-Seriell: `/dev/ttyUSB*`
- USB ACM: `/dev/ttyACM*`
- CM108/CM119: typischerweise `/dev/hidraw*`
- Linux GPIO: typischerweise `/dev/gpiochip*`
