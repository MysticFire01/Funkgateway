from __future__ import annotations

import html
import re
from datetime import datetime

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QBrush
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QSpinBox,QPushButton,
    QComboBox,QCheckBox,QListWidget,QListWidgetItem,QMessageBox,QInputDialog,QGroupBox,
    QPlainTextEdit,QSlider,QDialog,QDialogButtonBox,QMenu
)

try:
    import sounddevice as sd
except Exception:
    sd=None

from .mumble_native import MumbleNativeClient
from ..mumble_certificates import list_certificates, create_certificate


class MumbleNativePanel(QWidget):
    """Compact native Mumble client UI for Linux."""

    def __init__(self,parent=None):
        super().__init__(parent)
        self.client=MumbleNativeClient(self)
        self.client.status.connect(self._status)
        self.client.connectedChanged.connect(self._connected)
        self.client.channelChanged.connect(self._channel_changed)
        self.client.participantsChanged.connect(self._participants)
        self.client.speakersChanged.connect(self._speakers)
        self.client.inputLevel.connect(self._input_level)
        self.client.outputLevel.connect(self._output_level)
        self.client.error.connect(self._error)
        self.client.chatReceived.connect(self._chat_received)
        self.settings=QSettings('FunkGateway','LinuxNativeMumble')
        self._user_volumes={}
        self._build()
        self._load_settings()

    @staticmethod
    def _mouth_icon(kind):
        colors={"idle":"#2E9D57","talk":"#E53935","self":"#F2994A","whisper":"#2F80ED"}
        pix=QPixmap(24,17); pix.fill(Qt.transparent)
        p=QPainter(pix); p.setRenderHint(QPainter.Antialiasing,True)
        c=QColor(colors.get(kind,colors["idle"]))
        p.setPen(QPen(c,1.5)); p.setBrush(QBrush(c))
        path=QPainterPath()
        path.moveTo(2,8.5)
        path.cubicTo(6,3,9,4,12,6)
        path.cubicTo(15,4,18,3,22,8.5)
        path.cubicTo(18,14,6,14,2,8.5)
        p.drawPath(path)
        p.setPen(QPen(QColor("#202020"),1)); p.drawLine(5,9,19,9)
        p.end()
        return QIcon(pix)

    def _build(self):
        v=QVBoxLayout(self)

        info=QLabel(
            "<b>Nativer Mumble-Client</b><br>"
            "FunkGateway verbindet sich selbst mit dem Mumble-Server. "
            "Der normale Mumble-Desktop-Client ist dafür nicht nötig."
        )
        info.setWordWrap(True); v.addWidget(info)

        box=QGroupBox("Verbindung"); f=QFormLayout(box)
        self.host=QLineEdit("voice.mumble-funk.de")
        self.port=QSpinBox(); self.port.setRange(1,65535); self.port.setValue(64738)
        self.nick=QLineEdit("FunkGateway Linux")
        self.password=QLineEdit(); self.password.setEchoMode(QLineEdit.Password)
        self.channel=QLineEdit(); self.channel.setPlaceholderText("optional: Channel/Pfad")
        self.cert=QComboBox()
        self.refresh_cert=QPushButton("Zertifikate neu laden"); self.refresh_cert.clicked.connect(self._refresh_certs)
        self.create_cert=QPushButton("Neues Zertifikat"); self.create_cert.clicked.connect(self._create_cert)
        certrow=QHBoxLayout(); certrow.addWidget(self.cert,1); certrow.addWidget(self.refresh_cert); certrow.addWidget(self.create_cert)

        buttons=QHBoxLayout()
        self.connect_btn=QPushButton("Verbinden"); self.disconnect_btn=QPushButton("Trennen")
        self.disconnect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self._connect); self.disconnect_btn.clicked.connect(self.client.disconnect)
        buttons.addWidget(self.connect_btn); buttons.addWidget(self.disconnect_btn)

        self.status=QLabel("Native Mumble: getrennt"); self.status.setWordWrap(True)
        self.current_channel=QLabel("—")
        f.addRow("Server:",self.host); f.addRow("Port:",self.port); f.addRow("Nickname:",self.nick)
        f.addRow("Passwort:",self.password); f.addRow("Start-Channel:",self.channel); f.addRow("Zertifikat:",certrow)
        f.addRow(buttons); f.addRow("Status:",self.status); f.addRow("Aktueller Channel:",self.current_channel)
        v.addWidget(box)

        audio=QGroupBox("Audio / PC-PTT"); af=QFormLayout(audio)
        self.input=QComboBox(); self.output=QComboBox()
        self.refresh_audio=QPushButton("Audiogeräte neu laden"); self.refresh_audio.clicked.connect(self._refresh_audio)
        self.playback=QCheckBox("Mumble-Empfang direkt wiedergeben"); self.playback.setChecked(True)
        self.ptt_enabled=QCheckBox("PC-User Mikrofon-PTT aktiv"); self.ptt_enabled.setChecked(True)
        self.ptt=QPushButton("Mumble PTT halten"); self.ptt.setMinimumHeight(42)
        self.ptt.pressed.connect(lambda:self.client.set_pc_ptt(True))
        self.ptt.released.connect(lambda:self.client.set_pc_ptt(False))
        self.in_level=QLabel("Mikrofon: < -60 dBFS"); self.out_level=QLabel("Mumble: < -60 dBFS")
        af.addRow("Mikrofon:",self.input); af.addRow("Lautsprecher:",self.output); af.addRow("",self.playback)
        af.addRow("",self.ptt_enabled); af.addRow("",self.ptt); af.addRow("",self.refresh_audio)
        self.master_volume=QSpinBox()
        self.master_volume.setRange(0,200)
        self.master_volume.setValue(100)
        self.master_volume.setSuffix(" %")
        self.master_volume.valueChanged.connect(self._master_volume_changed)
        af.addRow("TX:",self.in_level); af.addRow("RX:",self.out_level)
        af.addRow("Mumble-Empfang gesamt:",self.master_volume)
        v.addWidget(audio)

        cols=QHBoxLayout()
        chbox=QGroupBox("Channels"); chv=QVBoxLayout(chbox)
        self.channels=QListWidget(); self.channels.itemDoubleClicked.connect(self._move_channel)
        self.refresh_channels=QPushButton("Channel-Liste aktualisieren"); self.refresh_channels.clicked.connect(self._refresh_channels)
        chv.addWidget(self.channels); chv.addWidget(self.refresh_channels)

        userbox=QGroupBox("Teilnehmer"); uv=QVBoxLayout(userbox)
        self.speaker=QLabel("Aktive Sprecher: —"); self.speaker.setWordWrap(True)
        self.users=QListWidget()
        self.users.setContextMenuPolicy(Qt.CustomContextMenu)
        self.users.customContextMenuRequested.connect(self._user_context_menu)
        uv.addWidget(self.speaker); uv.addWidget(self.users)
        cols.addWidget(chbox,1); cols.addWidget(userbox,1)
        v.addLayout(cols,1)
        chatbox=QGroupBox("Mumble Chat")
        chatlayout=QVBoxLayout(chatbox)
        self.chat_log=QPlainTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.document().setMaximumBlockCount(1000)
        chatlayout.addWidget(self.chat_log)
        targetrow=QHBoxLayout()
        self.chat_target=QComboBox()
        self.chat_target.addItem("Aktueller Channel (öffentlich)",None)
        targetrow.addWidget(QLabel("Empfänger:"))
        targetrow.addWidget(self.chat_target,1)
        chatlayout.addLayout(targetrow)
        typerow=QHBoxLayout()
        self.chat_input=QLineEdit()
        self.chat_input.setPlaceholderText("Nachricht eingeben …")
        self.chat_input.returnPressed.connect(self._send_chat)
        self.chat_send=QPushButton("Senden")
        self.chat_send.clicked.connect(self._send_chat)
        self.chat_send.setEnabled(False)
        typerow.addWidget(self.chat_input,1)
        typerow.addWidget(self.chat_send)
        chatlayout.addLayout(typerow)
        v.addWidget(chatbox)

        self._refresh_audio()
        self._refresh_certs()

    def _refresh_audio(self):
        self.input.clear(); self.output.clear()
        if sd is None:
            return
        try:
            devices=sd.query_devices()
            for idx,dev in enumerate(devices):
                name=str(dev.get("name") or f"Gerät {idx}")
                if int(dev.get("max_input_channels") or 0)>0:
                    self.input.addItem(f"{idx}: {name}",idx)
                if int(dev.get("max_output_channels") or 0)>0:
                    self.output.addItem(f"{idx}: {name}",idx)
        except Exception as exc:
            self._error("Audiogeräte: "+str(exc))

    def _refresh_certs(self):
        current=self.cert.currentData() if self.cert.count() else None
        current_id=current.get("id") if isinstance(current,dict) else ""
        self.cert.clear(); self.cert.addItem("Kein Zertifikat",None)
        for info in list_certificates():
            self.cert.addItem(info.get("name") or info["id"],info)
        if current_id:
            for i in range(self.cert.count()):
                data=self.cert.itemData(i)
                if isinstance(data,dict) and data.get("id")==current_id:
                    self.cert.setCurrentIndex(i); break

    def _create_cert(self):
        name,ok=QInputDialog.getText(self,"Mumble Zertifikat","Name:",text=self.nick.text().strip() or "FunkGateway Linux")
        if not ok or not name.strip(): return
        try:
            info=create_certificate(name.strip())
            self._refresh_certs()
            for i in range(self.cert.count()):
                data=self.cert.itemData(i)
                if isinstance(data,dict) and data.get("id")==info.get("id"):
                    self.cert.setCurrentIndex(i); break
        except Exception as exc:
            self._error("Zertifikat: "+str(exc))

    def _connect(self):
        cert=self.cert.currentData()
        certfile=cert.get("cert_path","") if isinstance(cert,dict) else ""
        keyfile=cert.get("key_path","") if isinstance(cert,dict) else ""
        try:
            self.client.connect_async(
                self.host.text().strip(),self.port.value(),self.nick.text().strip(),
                self.password.text(),self.channel.text().strip(),
                certfile=certfile,keyfile=keyfile,
                playback=self.playback.isChecked(),
                output_device=self.output.currentData(),
                input_device=self.input.currentData(),
                pc_ptt_enabled=self.ptt_enabled.isChecked(),
            )
        except Exception as exc:
            self._error(str(exc))

    def _connected(self,on):
        self.connect_btn.setEnabled(not on); self.disconnect_btn.setEnabled(on); self.ptt.setEnabled(on)
        if on:
            self._refresh_channels()
        else:
            self.channels.clear(); self.users.clear(); self.current_channel.setText("—")

    def _status(self,text):
        self.status.setText(str(text))

    def _channel_changed(self,name):
        self.current_channel.setText(str(name or "—"))

    def _refresh_channels(self):
        self.channels.clear()
        for row in sorted(self.client.channel_snapshot(),key=lambda r:(r.get("parent") or -1,str(r.get("name") or "").casefold())):
            marker="▶ " if row.get("current") else ""
            item=QListWidgetItem(f"{marker}{row.get('name','')} ({int(row.get('users') or 0)})")
            item.setData(Qt.UserRole,row)
            self.channels.addItem(item)

    def _move_channel(self,item):
        data=item.data(Qt.UserRole)
        if not isinstance(data,dict): return
        wanted=str(data.get("name") or "")
        if self.client.move_to_path(wanted):
            self.channel.setText(wanted)
            self._refresh_channels()

    def _participants(self,rows):
        self.users.clear()
        for row in rows:
            if row.get("talking"):
                kind="whisper" if row.get("speech_mode")=="whisper" else ("self" if row.get("is_self") else "talk")
            else:
                kind="idle"
            item=QListWidgetItem(self._mouth_icon(kind),f"{row.get('name','')} — {row.get('channel','')}")
            self.users.addItem(item)
        self._refresh_channels()

    def _speakers(self,names):
        self.speaker.setText("Aktive Sprecher: "+(", ".join(names) if names else "—"))

    def _input_level(self,db):
        self.in_level.setText(f"Mikrofon: {db:.1f} dBFS" if db>-60 else "Mikrofon: < -60 dBFS")

    def _output_level(self,db):
        self.out_level.setText(f"Mumble: {db:.1f} dBFS" if db>-60 else "Mumble: < -60 dBFS")

    def _error(self,text):
        self.status.setText(str(text))
        QMessageBox.warning(self,"Mumble",str(text))
