# Architektur

`main.py` startet nur Qt und das Hauptfenster.

- `funkgateway/main_window.py` – GUI und Ablaufsteuerung
- `funkgateway/audio.py` – FunkGateway_TX, Audio-Bridge, Pegelerkennung
- `funkgateway/ptt.py` – PTT-Hardwarebackends
- `funkgateway/ports.py` – serielle Portsuche
- `funkgateway/tones.py` – CW/DTMF-Erzeugung
- `funkgateway/helptext.py` – Hilfe für Anwender
- `funkgateway/constants.py` – Version, Konfigurationspfade

Das Ziel ist, Hardware und GUI möglichst unabhängig zu halten. So kann später z. B. ein neuer PTT-Adapter ergänzt werden, ohne die Audio-Erkennung neu zu schreiben.
