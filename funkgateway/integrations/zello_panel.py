"""Native Zello Friends & Family channel connection panel (initial alpha).
Uses the official secure Channel API; audio streaming is not yet implemented.
"""
import json
from PySide6.QtCore import QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QHBoxLayout,QLabel,
                               QLineEdit,QPushButton,QCheckBox,QGroupBox)

class ZelloPanel(QWidget):
    connectedChanged = Signal(bool)
    talkerChanged = Signal(str)
    statusChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected = False
        self.talker_name = ""
        self._requested_disconnect = False
        self._ws = QWebSocket()
        self._ws.connected.connect(self._socket_connected)
        self._ws.disconnected.connect(self._socket_disconnected)
        self._ws.textMessageReceived.connect(self._message)
        self._ws.errorOccurred.connect(self._socket_error)
        outer = QVBoxLayout(self)
        heading = QLabel("<h3>Zello · Friends & Family</h3>")
        outer.addWidget(heading)
        info = QLabel("Nativer Kanal-Client (Alpha): offizielle Zello Channel API. "
                      "Diese erste Ausbaustufe testet Anmeldung und Verbindungsstatus. "
                      "Empfangen und Senden von Sprache sind noch nicht freigeschaltet.")
        info.setWordWrap(True)
        outer.addWidget(info)
        group = QGroupBox("Kanalverbindung")
        form = QFormLayout(group)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.channel = QLineEdit()
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Sample Development Token (30 Tage gültig)")
        self.show_secrets = QCheckBox("Passwort und Token anzeigen")
        self.show_secrets.toggled.connect(self._show_secrets)
        form.addRow("Zello-Benutzer:",self.username)
        form.addRow("Passwort:",self.password)
        form.addRow("Kanal:",self.channel)
        form.addRow("API-Token:",self.token)
        form.addRow("",self.show_secrets)
        outer.addWidget(group)
        buttons = QHBoxLayout()
        self.connect_btn = QPushButton("Verbinden")
        self.disconnect_btn = QPushButton("Trennen")
        self.disconnect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self.connect_channel)
        self.disconnect_btn.clicked.connect(self.disconnect_channel)
        buttons.addWidget(self.connect_btn)
        buttons.addWidget(self.disconnect_btn)
        outer.addLayout(buttons)
        self.status = QLabel("Zello getrennt")
        self.status.setWordWrap(True)
        self.speaker = QLabel("Sprecher: —")
        outer.addWidget(self.status)
        outer.addWidget(self.speaker)
        help_label = QLabel('Token über https://developers.zello.com/ erstellen. '
                            'Zello unterstützt hier nur jeweils einen Friends-&-Family-Kanal. '
                            'Zugangsdaten bleiben in dieser Version nur im Arbeitsspeicher und '
                            'werden nicht in der FunkGateway-Konfiguration gespeichert.')
        help_label.setWordWrap(True)
        outer.addWidget(help_label)
        outer.addStretch(1)

    def _show_secrets(self, visible):
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.password.setEchoMode(mode)
        self.token.setEchoMode(mode)

    def _set_status(self, message):
        self.status.setText("Zello: " + message)
        self.statusChanged.emit(message)

    def connect_channel(self):
        if self._ws.state() != QAbstractSocket.SocketState.UnconnectedState:
            return
        if not all((self.username.text().strip(), self.password.text(),
                    self.channel.text().strip(), self.token.text().strip())):
            self._set_status("Benutzer, Passwort, Kanal und API-Token erforderlich")
            return
        self._requested_disconnect = False
        self.connect_btn.setEnabled(False)
        self._set_status("Verbinde …")
        self._ws.open(QUrl("wss://zello.io/ws"))

    def _socket_connected(self):
        payload = {
            "command": "logon", "seq": 1,
            "auth_token": self.token.text().strip(),
            "username": self.username.text().strip(),
            "password": self.password.text(),
            "channels": [self.channel.text().strip()]
        }
        self._ws.sendTextMessage(json.dumps(payload))
        self._set_status("Anmeldung läuft …")

    def _message(self, raw):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return
        if data.get("seq") == 1 and ("success" in data or "error" in data):
            if data.get("success"):
                self.connected = True
                self.connect_btn.setEnabled(False)
                self.disconnect_btn.setEnabled(True)
                self._set_status("Verbunden mit " + self.channel.text().strip())
                self.connectedChanged.emit(True)
            else:
                self._set_status("Anmeldung fehlgeschlagen: " +
                                 str(data.get("error", "unbekannter Fehler")))
                self._ws.close()
        elif data.get("command") == "on_stream_start":
            sender = str(data.get("from", "") or data.get("username", "") or "Unbekannt")
            self.talker_name = sender
            self.speaker.setText("Sprecher: " + sender)
            self.talkerChanged.emit(sender)
        elif data.get("command") == "on_stream_stop":
            self.talker_name = ""
            self.speaker.setText("Sprecher: —")
            self.talkerChanged.emit("")

    def _socket_error(self, error):
        self._set_status("Verbindungsfehler: " + self._ws.errorString())

    def _socket_disconnected(self):
        was_connected = self.connected
        self.connected = False
        self.talker_name = ""
        self.speaker.setText("Sprecher: —")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self._set_status("Getrennt")
        if was_connected:
            self.connectedChanged.emit(False)
        self.talkerChanged.emit("")

    def disconnect_channel(self):
        self._requested_disconnect = True
        self._ws.close()

    def closeEvent(self, event):
        self.disconnect_channel()
        super().closeEvent(event)
