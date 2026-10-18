"""Native Zello Friends & Family channel connection panel (initial alpha).
Uses the official secure Channel API; audio streaming is not yet implemented.
"""
import json
import base64
import struct
import threading
import queue
import time
import webbrowser
from datetime import datetime, timezone
from PySide6.QtCore import QUrl, Signal, QTimer, Qt
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QHBoxLayout,QLabel,
                               QLineEdit,QPushButton,QCheckBox,QGroupBox,QComboBox)

class ZelloPanel(QWidget):
    connectedChanged = Signal(bool)
    talkerChanged = Signal(str)
    statusChanged = Signal(str)
    audioError = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected = False
        self.channel_online = False
        self.talker_name = ""
        self._requested_disconnect = False
        self._streams = {}
        self._rx_packet_counts = {}
        self._audio_queue = queue.Queue(maxsize=120)
        self._audio_stop = threading.Event()
        self._audio_thread = None
        self._last_packet = 0.0
        self._known_speakers = set()
        self._tx_recipient = ""
        self._tx_seq = 2
        self._tx_pending = False
        self._tx_request_seq = None
        self._tx_requested_at = 0.0
        self._tx_timeout = QTimer(self)
        self._tx_timeout.setSingleShot(True)
        self._tx_timeout.timeout.connect(self._tx_request_timeout)
        self._tx_wanted = False
        self._tx_stream_id = None
        self._tx_input = None
        self._tx_encoder = None
        self._tx_queue = queue.Queue(maxsize=40)
        self._tx_timer = QTimer(self)
        self._tx_timer.setInterval(20)
        self._tx_timer.timeout.connect(self._flush_tx)
        self._rx_timer = QTimer(self)
        self._rx_timer.setInterval(350)
        self._rx_timer.timeout.connect(self._check_audio_timeout)
        self.audioError.connect(self._audio_error)
        self._ws = QWebSocket()
        self._ws.connected.connect(self._socket_connected)
        self._ws.disconnected.connect(self._socket_disconnected)
        self._ws.textMessageReceived.connect(self._message)
        self._ws.binaryMessageReceived.connect(self._binary_message)
        self._ws.errorOccurred.connect(self._socket_error)
        outer = QVBoxLayout(self)
        heading = QLabel("<h3>Zello · Friends & Family</h3>")
        outer.addWidget(heading)
        info = QLabel("Nativer Kanal-Client (Alpha): offizielle Zello Channel API. "
                      "Diese Alpha-Version empfängt Opus-Sprache und zeigt den Sprecher an. "
                      "Senden: PTT gedrückt halten, dann loslassen.")
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
        self.token_portal_btn=QPushButton("Neuen API-Token anfordern")
        self.token_portal_btn.clicked.connect(lambda: webbrowser.open("https://developers.zello.com/"))
        form.addRow("",self.token_portal_btn)
        self.token_expiry=QLabel("Token-Ablauf: noch nicht geprüft")
        self.token_expiry.setWordWrap(True)
        self.token.textChanged.connect(self._token_updated)
        form.addRow("",self.token_expiry)
        self.save_credentials_btn=QPushButton("Zello-Zugangsdaten speichern")
        self.save_credentials_btn.clicked.connect(self.save_credentials)
        form.addRow("",self.save_credentials_btn)
        self.credential_status=QLabel("Benutzer und Kanal in FunkGateway-Konfiguration; Passwörter im System-Schlüsselbund.")
        self.credential_status.setWordWrap(True)
        form.addRow("",self.credential_status)
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
        self.channel_status=QLabel("Kanalstatus: nicht geprüft")
        self.channel_status.setWordWrap(True)
        outer.addWidget(self.channel_status)
        outer.addWidget(self.speaker)
        self.audio_status=QLabel("Audioempfang: bereit")
        outer.addWidget(self.audio_status)
        self.rx_diagnostic=QLabel("RX-Diagnose: noch keine Übertragung")
        self.rx_diagnostic.setWordWrap(True)
        self.rx_diagnostic.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.rx_diagnostic)
        self.rx_detail=QLabel("RX-Details: Noch kein Stream empfangen")
        self.rx_detail.setWordWrap(True)
        self.rx_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.rx_detail)
        self.copy_rx_btn=QPushButton("RX-Diagnose kopieren")
        self.copy_rx_btn.clicked.connect(self._copy_rx_diagnostic)
        outer.addWidget(self.copy_rx_btn)
        target_box=QGroupBox("Zello – Gesprächsziel")
        target_form=QFormLayout(target_box)
        self.target_mode=QComboBox()
        self.target_mode.addItem("An alle im Kanal","all")
        self.target_mode.addItem("Bestimmten Kanalteilnehmer ansprechen","user")
        self.target_user=QComboBox()
        self.target_user.setEditable(True)
        self.target_user.setInsertPolicy(QComboBox.NoInsert)
        self.target_user.setPlaceholderText("Benutzername")
        self.target_user.setEnabled(False)
        self.target_mode.currentIndexChanged.connect(self._target_mode_changed)
        self.add_contact_btn=QPushButton("Teilnehmer merken")
        self.add_contact_btn.clicked.connect(self._remember_contact)
        target_form.addRow("Sendeziel:",self.target_mode)
        target_form.addRow("Kanalteilnehmer:",self.target_user)
        target_form.addRow("",self.add_contact_btn)
        self.users_online=QLabel("Teilnehmer online: —")
        target_form.addRow("",self.users_online)
        note=QLabel("Die Channel API liefert Teilnehmerzahlen, aber keine vollständige "
                    "Namensliste. Bekannte Sprecher und manuell gemerkte Namen "
                    "stehen zur Auswahl. Direktnachrichten funktionieren nur "
                    "zu Teilnehmern desselben Kanals.")
        note.setWordWrap(True)
        target_form.addRow("",note)
        outer.addWidget(target_box)
        self.ptt_btn=QPushButton("Zello PTT halten")
        self.ptt_btn.setMinimumHeight(48)
        self.ptt_btn.setEnabled(False)
        self.ptt_btn.pressed.connect(lambda:self.set_ptt(True))
        self.ptt_btn.released.connect(lambda:self.set_ptt(False))
        outer.addWidget(self.ptt_btn)
        self.tx_status=QLabel("Zello TX: bereit")
        outer.addWidget(self.tx_status)
        self.tx_diagnostic=QLabel("PTT-Diagnose: noch kein Sendeversuch")
        self.tx_diagnostic.setWordWrap(True)
        self.tx_diagnostic.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.tx_diagnostic)
        help_label = QLabel('Token über https://developers.zello.com/ erstellen. '
                            'Zello unterstützt hier nur jeweils einen Friends-&-Family-Kanal. '
                            'Zugangsdaten bleiben in dieser Version nur im Arbeitsspeicher und '
                            'werden nicht in der FunkGateway-Konfiguration gespeichert.')
        help_label.setWordWrap(True)
        outer.addWidget(help_label)
        outer.addStretch(1)

    def to_config(self):
        return {"username":self.username.text().strip(),
                "channel":self.channel.text().strip(),
                "known_speakers":sorted(self._known_speakers)}

    def load_config(self,data):
        if not isinstance(data,dict):
            data={}
        self.username.setText(str(data.get("username","") or ""))
        self.channel.setText(str(data.get("channel","") or ""))
        self._known_speakers=set(
            str(x).strip() for x in data.get("known_speakers",[])
            if isinstance(x,str) and x.strip())
        self.target_user.clear()
        self.target_user.addItems(sorted(self._known_speakers,key=str.casefold))
        self.target_user.setCurrentIndex(-1)
        try:
            import keyring
            values=json.loads(keyring.get_password("FunkGateway.Zello","credentials") or "{}")
            if values.get("username")==self.username.text().strip():
                self.password.setText(str(values.get("password","")))
                self.token.setText(str(values.get("token","")))
                self.credential_status.setText("Zello-Zugangsdaten aus System-Schlüsselbund geladen.")
        except Exception:
            self.credential_status.setText("Kein Schlüsselbund verfügbar; Passwort und Token bitte eingeben.")

    def save_credentials(self):
        window=self.window()
        try:
            if hasattr(window,"save_cfg"):
                window.save_cfg()
        except Exception as exc:
            self.credential_status.setText("Konfiguration nicht gespeichert: "+str(exc))
            return
        try:
            import keyring
            from keyring.errors import KeyringError
            values=json.dumps({"username":self.username.text().strip(),
                               "password":self.password.text(),
                               "token":self.token.text()})
            keyring.set_password("FunkGateway.Zello","credentials",values)
            self.credential_status.setText(
                "Gespeichert: Benutzer/Kanal in config.json; Passwort/Token im System-Schlüsselbund.")
        except Exception as exc:
            self.credential_status.setText(
                "Benutzer/Kanal gespeichert. Passwort/Token NICHT gespeichert: "+
                str(exc)+" – System-Schlüsselbund prüfen.")

    def _token_updated(self, value):
        """Read JWT expiry locally; never transmit the token for inspection."""
        try:
            encoded=value.split(".")[1]
            data=json.loads(base64.urlsafe_b64decode(encoded+"="*(-len(encoded)%4)))
            expiry=datetime.fromtimestamp(int(data["exp"]),timezone.utc)
            local=expiry.astimezone()
            days=(expiry-datetime.now(timezone.utc)).total_seconds()/86400
            note="ABGELAUFEN" if days<=0 else ("läuft in weniger als 3 Tagen ab" if days<3 else "gültig laut Token")
            self.token_expiry.setText("Token-Ablauf: "+local.strftime("%d.%m.%Y %H:%M")+" – "+note)
        except (ValueError,TypeError,IndexError,KeyError,OverflowError):
            self.token_expiry.setText("Token-Ablauf: nicht auslesbar")

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
        self.channel_online=False
        self.channel_status.setText("Kanalstatus: wartet auf Zello …")
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
                self._start_audio()
                self.connect_btn.setEnabled(False)
                self.disconnect_btn.setEnabled(True)
                self.ptt_btn.setEnabled(False)
                self.channel_status.setText("Kanalstatus: Anmeldung erfolgreich; warte auf Kanalstatus")
                self._set_status("Verbunden mit " + self.channel.text().strip())
                self.connectedChanged.emit(True)
            else:
                self._set_status("Anmeldung fehlgeschlagen: " +
                                 str(data.get("error", "unbekannter Fehler")))
                self._ws.close()
        elif data.get("command") == "on_channel_status":
            if str(data.get("channel","")).casefold() == self.channel.text().strip().casefold():
                self.channel_online=(data.get("status")=="online")
                error=str(data.get("error") or "")
                label="online" if self.channel_online else "offline"
                self.channel_status.setText("Kanalstatus: "+label+(" – "+error if error else ""))
                self.users_online.setText("Teilnehmer online: "+str(data.get("users_online","—")))
                self.ptt_btn.setEnabled(bool(self.connected and self.channel_online))
                if not self.channel_online:
                    self._stop_tx()
        elif self._tx_pending and data.get("seq") == self._tx_request_seq:
            elapsed=time.monotonic()-self._tx_requested_at
            self.tx_diagnostic.setText("PTT-Diagnose: Serverantwort nach %.2f s: success=%s, stream_id=%s, error=%s" % (elapsed, data.get("success"), data.get("stream_id","—"), data.get("error","—")))
            self._tx_pending=False
            self._tx_timeout.stop()
            self._tx_request_seq=None
            if data.get("success") and "stream_id" in data:
                self._tx_stream_id=int(data["stream_id"])
                if self._tx_wanted:
                    self._begin_microphone()
                else:
                    self._stop_tx()
            else:
                self._tx_wanted=False
                self.tx_status.setText("Zello TX abgelehnt: "+str(data.get("error","unbekannt")))
                self._update_ptt_ui()
        elif self._tx_pending and ("success" in data or "error" in data):
            # Report unexpected response IDs, but never log arbitrary server
            # payloads (which might contain sensitive fields).
            self.tx_diagnostic.setText(
                "PTT-Diagnose: Antwort mit unerwarteter seq=%s (erwartet %s), "
                "success=%s, error=%s" %
                (data.get("seq","—"), self._tx_request_seq,
                 data.get("success","—"), data.get("error","—")))
        elif data.get("command") == "on_stream_start":
            try:
                if data.get("codec") != "opus":
                    raise ValueError("Codec nicht Opus")
                stream_id=int(data["stream_id"])
                h=base64.b64decode(data["codec_header"],validate=True)
                rate,frames,frame_ms=struct.unpack("<HBB",h)
                if rate not in (8000,12000,16000,24000,48000) or frames not in (1,2):
                    raise ValueError("Opus-Header nicht unterstützt")
                import opuslib
                decoder=opuslib.Decoder(rate,1)
                # The API documents "from" and optional "for" for both
                # regular and targeted channel transmissions. Avoid guessing
                # an identity when the server omits the sender field.
                sender=next((str(data[key]).strip() for key in
                             ("from","sender","username","from_user")
                             if isinstance(data.get(key),str) and data[key].strip()),"")
                recipient=data.get("for")
                target="gezielt" if isinstance(recipient,str) and recipient.strip() else "Kanal"
                present=",".join(k for k in ("from","sender","username","from_user","for")
                                 if k in data) or "keine"
                self.rx_diagnostic.setText(
                    f"RX-Diagnose: {target} · Absenderfelder: {present} · "
                    +("Sprecher erkannt" if sender else "kein Absender übermittelt"))
                # List field names only; never display the full inbound JSON.
                fields=", ".join(sorted(str(key) for key in data.keys()))
                self._rx_packet_counts[stream_id]=0
                self.rx_detail.setText(
                    f"RX-Details: Ereignis on_stream_start · Stream-ID {stream_id} · "
                    f"Felder: {fields} · Opus {rate} Hz / {frame_ms} ms · "
                    "Audiopakete: 0")
                if not sender:
                    self.rx_diagnostic.setText(
                        "RX-Diagnose: Absender nicht vom Server übermittelt "
                        "(Übertragungsart nicht sicher bestimmbar)")
                speaker=sender or "Unbekannt"
                self._streams[stream_id]=(decoder,rate,speaker)
                self._last_packet=time.monotonic()
                self._set_speaker(speaker)
                self.audio_status.setText("Audioempfang: "+speaker)
            except Exception as exc:
                self.audio_status.setText("Opus-Startfehler: "+str(exc))
        elif data.get("command") == "on_stream_stop":
            try:
                ended=int(data["stream_id"])
                self._streams.pop(ended,None)
                count=self._rx_packet_counts.pop(ended,0)
                self.rx_detail.setText(self.rx_detail.text()+f" · Stream beendet ({count} Pakete)")
            except (ValueError,TypeError,KeyError):
                pass
            if not self._streams:
                self._set_speaker("")
                self.audio_status.setText("Audioempfang: bereit")

    def _copy_rx_diagnostic(self):
        # Share only diagnostic labels, never credentials or raw server payloads.
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(
            self.rx_diagnostic.text()+"\\n"+self.rx_detail.text())

    def _send_command(self, command, **kwargs):
        seq=self._tx_seq
        self._tx_seq+=1
        self._ws.sendTextMessage(json.dumps(dict(command=command,seq=seq,**kwargs)))
        return seq

    def _update_ptt_ui(self):
        active=bool(self._tx_wanted or self._tx_stream_id is not None)
        self.ptt_btn.setText("Zello TX AKTIV" if active else "Zello PTT halten")
        self.ptt_btn.setStyleSheet("background:#E58B22;color:black;font-weight:bold;" if active else "")

    def set_ptt(self,active):
        active=bool(active) and self.connected and self.channel_online
        if active:
            if self._tx_wanted or self._tx_pending or self._tx_stream_id is not None:
                return
            recipient=self.target_user.currentText().strip() if self.target_mode.currentData()=="user" else ""
            if self.target_mode.currentData()=="user" and not recipient:
                self.tx_status.setText("Zello TX: bitte Kanalteilnehmer auswählen")
                return
            self._tx_recipient=recipient
            self._tx_wanted=True
            try:
                import opuslib
                self._tx_encoder=opuslib.Encoder(16000,1,"voip")
            except Exception as exc:
                self._tx_wanted=False
                self.tx_status.setText("Opus-Encoder fehlt: "+str(exc))
                return
            header=base64.b64encode(struct.pack("<HBB",16000,1,20)).decode("ascii")
            self._tx_pending=True
            payload=dict(channel=self.channel.text().strip(),type="audio",codec="opus",
                         codec_header=header,packet_duration=20)
            if self._tx_recipient:
                payload["for"]=self._tx_recipient
            self._tx_request_seq=self._send_command("start_stream",**payload)
            self._tx_requested_at=time.monotonic()
            self.tx_diagnostic.setText("PTT-Diagnose: start_stream gesendet, seq="+str(self._tx_request_seq)+", Kanal="+self.channel.text().strip())
            self._tx_timeout.start(6000)
            self.tx_status.setText("Zello TX: Freigabe wird angefordert …")
        else:
            self._tx_wanted=False
            if not self._tx_pending and self._tx_stream_id is not None:
                self._stop_tx()
        self._update_ptt_ui()

    def _tx_request_timeout(self):
        if not self._tx_pending:
            return
        self._tx_pending=False
        self._tx_wanted=False
        self._tx_request_seq=None
        self._tx_encoder=None
        self.tx_status.setText("Zello TX: keine Antwort vom Server innerhalb von 6 Sekunden")
        self.tx_diagnostic.setText("PTT-Diagnose: Timeout ohne passende Antwort auf start_stream")
        self._update_ptt_ui()

    def _begin_microphone(self):
        try:
            import sounddevice as sd
            def callback(indata,frames,time_info,status):
                if not self._tx_wanted:
                    return
                try:
                    self._tx_queue.put_nowait(bytes(indata))
                except queue.Full:
                    pass
            self._tx_input=sd.RawInputStream(samplerate=16000,channels=1,
                                             dtype="int16",blocksize=320,
                                             callback=callback,latency="low")
            self._tx_input.start()
            self._tx_timer.start()
            self.tx_status.setText("Zello TX: Mikrofon sendet")
        except Exception as exc:
            self.tx_status.setText("Zello Mikrofon: "+str(exc))
            self._stop_tx()

    def _flush_tx(self):
        if not self._tx_wanted or self._tx_stream_id is None:
            return
        for _ in range(5):
            try:
                pcm=self._tx_queue.get_nowait()
            except queue.Empty:
                break
            try:
                packet=self._tx_encoder.encode(pcm,320)
                self._ws.sendBinaryMessage(bytes([1])+struct.pack("!II",self._tx_stream_id,0)+packet)
            except Exception as exc:
                self.tx_status.setText("Zello TX-Fehler: "+str(exc))
                self._stop_tx()
                break

    def _stop_tx(self):
        self._tx_wanted=False
        self._tx_timer.stop()
        self._tx_timeout.stop()
        if self._tx_input is not None:
            try:
                self._tx_input.stop()
                self._tx_input.close()
            except Exception:
                pass
            self._tx_input=None
        # Drain microphone samples before stop_stream for a complete last packet.
        if self._tx_stream_id is not None and self.connected:
            while not self._tx_queue.empty():
                try:
                    pcm=self._tx_queue.get_nowait()
                    packet=self._tx_encoder.encode(pcm,320)
                    self._ws.sendBinaryMessage(bytes([1])+struct.pack("!II",self._tx_stream_id,0)+packet)
                except Exception:
                    break
            self._send_command("stop_stream",channel=self.channel.text().strip(),
                               stream_id=self._tx_stream_id)
        self._tx_stream_id=None
        self._tx_recipient=""
        self._tx_pending=False
        self._tx_request_seq=None
        self._tx_encoder=None
        while not self._tx_queue.empty():
            try: self._tx_queue.get_nowait()
            except queue.Empty: break
        self._update_ptt_ui()
        self.tx_status.setText("Zello TX: bereit")

    def _target_mode_changed(self, *_args):
        self.target_user.setEnabled(self.target_mode.currentData()=="user")

    def _remember_contact(self):
        name=self.target_user.currentText().strip()
        if not name:
            return
        if name not in self._known_speakers:
            self._known_speakers.add(name)
            self.target_user.addItem(name)
        self.target_user.setCurrentText(name)
        window=self.window()
        if hasattr(window,"save_cfg"):
            window.save_cfg()

    def _set_speaker(self,name):
        if self.talker_name==name:
            return
        self.talker_name=name
        if name and name!="Unbekannt" and name not in self._known_speakers:
            self._known_speakers.add(name)
            self.target_user.addItem(name)
        self.speaker.setText("Sprecher: "+(name or "—"))
        self.talkerChanged.emit(name)

    def _binary_message(self,data):
        raw=bytes(data)
        if not self.connected or len(raw)<10 or raw[0]!=1:
            return
        stream_id,packet_id=struct.unpack("!II",raw[1:9])
        stream=self._streams.get(stream_id)
        if not stream:
            return
        decoder,rate,speaker=stream
        try:
            pcm=decoder.decode(raw[9:],int(rate*.12),False)
            self._rx_packet_counts[stream_id]=self._rx_packet_counts.get(stream_id,0)+1
            count=self._rx_packet_counts[stream_id]
            if count==1 or count%50==0:
                self.rx_detail.setText(
                    f"RX-Details: Stream-ID {stream_id} · Pakete: {count} · "
                    f"letzte Paket-ID: {packet_id} · Sprecher: {speaker} · Opus {rate} Hz")
            self._last_packet=time.monotonic()
            self._set_speaker(speaker)
            try:
                self._audio_queue.put_nowait((rate,pcm))
            except queue.Full:
                self._audio_queue.get_nowait()
                self._audio_queue.put_nowait((rate,pcm))
        except Exception as exc:
            self.audio_status.setText("Opus-Dekodierung: "+str(exc))

    def _audio_worker(self):
        try:
            import sounddevice as sd
            import audioop
            with sd.RawOutputStream(samplerate=48000,channels=1,dtype="int16",latency="low") as output:
                state=None
                old_rate=None
                while not self._audio_stop.is_set():
                    try:
                        rate,pcm=self._audio_queue.get(timeout=.15)
                    except queue.Empty:
                        continue
                    if rate!=old_rate:
                        state=None
                        old_rate=rate
                    if rate!=48000:
                        pcm,state=audioop.ratecv(pcm,2,1,rate,48000,state)
                    if pcm and not self._audio_stop.is_set():
                        output.write(pcm)
        except Exception as exc:
            self.audioError.emit(str(exc))

    def _audio_error(self,message):
        self.audio_status.setText("Audioausgabe: "+message)

    def _start_audio(self):
        if self._audio_thread and self._audio_thread.is_alive():
            return
        self._audio_stop.clear()
        self._audio_thread=threading.Thread(target=self._audio_worker,daemon=True)
        self._audio_thread.start()
        self._rx_timer.start()

    def _clear_audio(self):
        self._rx_timer.stop()
        self._audio_stop.set()
        self._streams.clear()
        self._rx_packet_counts.clear()
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        self._set_speaker("")
        self.rx_diagnostic.setText("RX-Diagnose: noch keine Übertragung")

    def _check_audio_timeout(self):
        if self.talker_name and time.monotonic()-self._last_packet>2.5:
            self._set_speaker("")
            self.audio_status.setText("Audioempfang: wartet")

    def _socket_error(self, error):
        self._set_status("Verbindungsfehler: " + self._ws.errorString())

    def _socket_disconnected(self):
        self._stop_tx()
        self.ptt_btn.setEnabled(False)
        self._clear_audio()
        self.channel_online=False
        self.channel_status.setText("Kanalstatus: getrennt")
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
        self._stop_tx()
        self.ptt_btn.setEnabled(False)
        self._clear_audio()
        self._requested_disconnect = True
        self._ws.close()

    def closeEvent(self, event):
        self.disconnect_channel()
        super().closeEvent(event)
