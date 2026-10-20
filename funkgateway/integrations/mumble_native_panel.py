from __future__ import annotations

import html
import re
from datetime import datetime

from PySide6.QtCore import Qt, QSettings, QThread, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QBrush
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QSpinBox,QPushButton,
    QComboBox,QCheckBox,QListWidget,QListWidgetItem,QMessageBox,QInputDialog,QGroupBox,
    QPlainTextEdit,QSlider,QDialog,QDialogButtonBox,QMenu,QScrollArea, QTabWidget, QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView, QFileDialog
)

try:
    import sounddevice as sd
except Exception:
    sd=None

from .mumble_native import MumbleNativeClient
from .mumble_public import MumblePublicServerLoader
from .frn_panel import HotkeyCaptureButton
from .emoji_picker import emoji_button
from .mumble_channel_editor import ChannelEditor
from .mumble_acl_dialog import MumbleAclDialog
from .mumble_acl_classic import MumbleAclClassicDialog
from .mumble_registered_panel import MumbleRegisteredPanel
from .mumble_ban_panel import MumbleBanPanel
from ..hotkeys import LocalPttHotkey
from ..global_hotkey import GlobalPttHotkey
from ..mumble_certificates import (
    list_certificates, create_certificate, import_pkcs12, import_pem,
    export_pem, export_pkcs12, delete_certificate, certificate_backend_status,
    CERT_DIR,
)


DEFAULT_MUMBLE_FAVORITES = [
    {"name":"Mumble-Funk Hauptserver","host":"voice.mumble-funk.de","port":64738,
     "username":"","locked":True},
    {"name":"FreiesFunkNetz","host":"mumble.freiesfunknetz.com","port":64738,
     "username":"","locked":False},
    {"name":"RadioBunker / DN9LO","host":"dn9lo.de","port":64738,
     "username":"","locked":False},
    {"name":"QSO4YOU","host":"mumble.qso4you.com","port":64738,
     "username":"","locked":False},
]


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
        self.local_ptt_hotkey=LocalPttHotkey(self)
        self.global_ptt_hotkey=GlobalPttHotkey(self)
        self.local_ptt_hotkey.pressed.connect(self._hotkey_ptt_press)
        self.local_ptt_hotkey.released.connect(self._hotkey_ptt_release)
        self.global_ptt_hotkey.pressed.connect(self._hotkey_ptt_press)
        self.global_ptt_hotkey.released.connect(self._hotkey_ptt_release)
        self.global_ptt_hotkey.statusChanged.connect(self._hotkey_status)
        self.client.chatReceived.connect(self._chat_received)
        self.settings=QSettings('FunkGateway','LinuxNativeMumble')
        self._user_volumes={}
        self._favorites=[]
        self._public_servers=[]
        self._public_source=""
        self._public_detail=""
        self._public_thread=None
        self._public_worker=None
        self._channel_rows=[]
        self._participant_rows=[]
        self._channel_expand_all=True
        self._initial_channel_focus_pending=False
        self._build()
        self._load_settings()
        self._refresh_favorites()
        self._configure_ptt_hotkey()

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
        outer=QVBoxLayout(self)
        self.mumble_tabs=QTabWidget(self)
        self.mumble_tabs.setUsesScrollButtons(True)
        self.mumble_tabs.tabBar().setExpanding(False)
        self.mumble_tabs.setElideMode(Qt.TextElideMode.ElideRight)
        outer.addWidget(self.mumble_tabs)
        self.mumble_tabs.currentChanged.connect(self._mumble_tab_changed)
        client_page=QWidget(self.mumble_tabs)
        v=QVBoxLayout(client_page)
        client_scroll=QScrollArea(self.mumble_tabs)
        client_scroll.setWidgetResizable(True)
        client_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        client_scroll.setWidget(client_page)
        self.mumble_tabs.addTab(client_scroll,"Verbindung")

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
        self.favorite_select=QComboBox()
        self.favorite_select.addItem("Manueller Server",None)
        self.favorite_select.currentIndexChanged.connect(self._favorite_selected)
        self.favorite_add=QPushButton("Favorit hinzufügen")
        self.favorite_edit=QPushButton("Bearbeiten")
        self.favorite_delete=QPushButton("Löschen")
        self.favorite_add.clicked.connect(self._favorite_add)
        self.favorite_edit.clicked.connect(self._favorite_edit)
        self.favorite_delete.clicked.connect(self._favorite_delete)
        favrow=QHBoxLayout()
        favrow.addWidget(self.favorite_select,1)
        favrow.addWidget(self.favorite_add)
        favrow.addWidget(self.favorite_edit)
        favrow.addWidget(self.favorite_delete)
        self.favorite_nick_label=QLabel("Favoriten-Nickname: allgemeiner Nickname")
        self.cert=QComboBox()
        self.cert.currentIndexChanged.connect(self._cert_changed)
        certrow=QHBoxLayout()
        certrow.addWidget(self.cert,1)
        open_cert_tab=QPushButton("Zertifikate verwalten …")
        open_cert_tab.clicked.connect(self._open_cert_tab)
        certrow.addWidget(open_cert_tab)

        buttons=QHBoxLayout()
        self.connect_btn=QPushButton("Verbinden"); self.disconnect_btn=QPushButton("Trennen")
        self.disconnect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self._connect); self.disconnect_btn.clicked.connect(self.client.disconnect)
        buttons.addWidget(self.connect_btn); buttons.addWidget(self.disconnect_btn)

        self.status=QLabel("Native Mumble: getrennt"); self.status.setWordWrap(True)
        self.current_channel=QLabel("—")
        self.mumble_audio_state=QLabel("Self-Mute: —  ·  Self-Deaf: —  ·  Server-Mute: —  ·  Server-Deaf: —")
        self.mumble_audio_state.setWordWrap(True)
        self.mumble_audio_state.setToolTip(
            "Self = eigene Stummschaltung, Server = vom Mumble-Server vorgegeben. "
            "Serverseitige Sperren können hier nicht selbst aufgehoben werden."
        )
        self._server_mute=False
        self._server_deaf=False
        self._self_mute_active=False
        self._self_deaf_active=False
        f.addRow("Favoriten:",favrow)
        f.addRow("",self.favorite_nick_label)
        f.addRow("Server:",self.host); f.addRow("Port:",self.port); f.addRow("Nickname:",self.nick)
        f.addRow("Passwort:",self.password); f.addRow("Start-Channel:",self.channel); f.addRow("Zertifikat:",certrow)
        f.addRow(buttons); f.addRow("Status:",self.status); f.addRow("Aktueller Channel:",self.current_channel)
        f.addRow("Mute / Deaf:",self.mumble_audio_state)
        v.addWidget(box)

        audio=QGroupBox("Audio / PC-PTT"); af=QFormLayout(audio)
        self.input=QComboBox(); self.output=QComboBox()
        self.refresh_audio=QPushButton("Audiogeräte neu laden"); self.refresh_audio.clicked.connect(self._refresh_audio)
        self.playback=QCheckBox("Mumble-Empfang direkt wiedergeben"); self.playback.setChecked(True)
        self.ptt_enabled=QCheckBox("PC-User Mikrofon-PTT aktiv"); self.ptt_enabled.setChecked(True)
        self.self_mute=QCheckBox("Eigenes Mikrofon stummschalten")
        self.self_mute.toggled.connect(self._self_mute_changed)
        self.self_deaf=QCheckBox("Eigenen Empfang taub schalten")
        self.self_deaf.toggled.connect(self._self_deaf_changed)
        self.ptt=QPushButton("Mumble PTT halten"); self.ptt.setMinimumHeight(42)
        self.ptt.pressed.connect(lambda:self.set_mumble_ptt(True))
        self.ptt.released.connect(lambda:self.set_mumble_ptt(False))
        self.ptt_hotkey=HotkeyCaptureButton()
        self.ptt_hotkey.set_hotkey("F10")
        self.ptt_hotkey.hotkeyChanged.connect(self._configure_ptt_hotkey)
        self.ptt_hotkey_scope=QComboBox()
        self.ptt_hotkey_scope.addItem("Nur FunkGateway","local")
        self.ptt_hotkey_scope.addItem("Systemweit (X11)","global")
        self.ptt_hotkey_scope.currentIndexChanged.connect(self._configure_ptt_hotkey)
        self.ptt_hotkey_status=QLabel("Mumble-Hotkey: lokal bereit")
        self.ptt_hotkey_status.setWordWrap(True)
        self.in_level=QLabel("Mikrofon: < -60 dBFS"); self.out_level=QLabel("Mumble: < -60 dBFS")
        af.addRow("Mikrofon:",self.input); af.addRow("Lautsprecher:",self.output); af.addRow("",self.playback)
        af.addRow("",self.ptt_enabled); af.addRow("",self.ptt); af.addRow("",self.refresh_audio)
        af.addRow("",self.self_mute); af.addRow("",self.self_deaf)
        self.mumble_audio_detail=QLabel(
            "Self-Mute: —  ·  Self-Deaf: —  ·  Server-Mute: —  ·  Server-Deaf: —"
        )
        self.mumble_audio_detail.setWordWrap(True)
        af.addRow("Mute/Deaf-Status:",self.mumble_audio_detail)
        self.master_volume=QSpinBox()
        self.master_volume.setRange(0,200)
        self.master_volume.setValue(100)
        self.master_volume.setSuffix(" %")
        self.master_volume.valueChanged.connect(self._master_volume_changed)
        af.addRow("TX:",self.in_level); af.addRow("RX:",self.out_level)
        af.addRow("Mumble-Empfang gesamt:",self.master_volume)
        af.addRow("Eigener Mumble-PTT-Hotkey:",self.ptt_hotkey)
        af.addRow("Hotkey-Bereich:",self.ptt_hotkey_scope)
        af.addRow("",self.ptt_hotkey_status)
        audio_page=QWidget(self.mumble_tabs)
        audio_layout=QVBoxLayout(audio_page)
        audio_layout.addWidget(QLabel(
            "<b>Mumble Audio und Push-to-Talk</b> – Mikrofon, Wiedergabe "
            "und eigener PTT-Hotkey."
        ))
        audio_layout.addWidget(audio)
        audio_layout.addStretch(1)
        self.mumble_tabs.addTab(audio_page,"Audio / PTT")

        # Channel browser gets its own entire tab, not a cramped area between
        # the connection settings and chat on the main client tab.
        channel_page=QWidget(self.mumble_tabs)
        channel_layout=QVBoxLayout(channel_page)
        channel_title=QLabel("<b>Channels des verbundenen Mumble-Servers</b>")
        channel_layout.addWidget(channel_title)
        chbox=QGroupBox("Channel-Baum und Benutzer")
        chv=QVBoxLayout(chbox)
        self.channels=QTreeWidget()
        self.channels.setHeaderLabels(["Channel / Benutzer", "Nutzer", "Status"])
        self.channels.setAlternatingRowColors(False)
        self.channels.setRootIsDecorated(True)
        self.channels.setIndentation(24)
        self.channels.setUniformRowHeights(True)
        self.channels.setMinimumHeight(420)
        self.channels.setSelectionMode(QAbstractItemView.SingleSelection)
        self.channels.header().setSectionResizeMode(0,QHeaderView.Stretch)
        self.channels.header().setSectionResizeMode(1,QHeaderView.ResizeToContents)
        self.channels.header().setSectionResizeMode(2,QHeaderView.ResizeToContents)
        self.channels.itemDoubleClicked.connect(self._move_channel)
        self.channels.setContextMenuPolicy(Qt.CustomContextMenu)
        self.channels.customContextMenuRequested.connect(self._channel_context_menu)
        self.refresh_channels=QPushButton("Channel-Liste aktualisieren")
        self.refresh_channels.clicked.connect(self._refresh_channels)
        self.expand_channels=QPushButton("Alle Räume aufklappen")
        self.expand_channels.clicked.connect(self._toggle_channel_expand)
        buttons=QHBoxLayout()
        self.locate_my_channel=QPushButton("⌖ Mein Raum")
        self.locate_my_channel.clicked.connect(self._locate_my_channel)
        self.channel_mute_button=QPushButton("Mikrofon stumm")
        self.channel_mute_button.setCheckable(True)
        self.channel_mute_button.toggled.connect(self.self_mute.setChecked)
        self.channel_deaf_button=QPushButton("Empfang taub")
        self.channel_deaf_button.setCheckable(True)
        self.channel_deaf_button.toggled.connect(self.self_deaf.setChecked)
        self.self_mute.toggled.connect(self._sync_quick_mumble_buttons)
        self.self_deaf.toggled.connect(self._sync_quick_mumble_buttons)
        buttons.addWidget(self.refresh_channels)
        buttons.addWidget(self.expand_channels)
        buttons.addWidget(self.locate_my_channel)
        buttons.addWidget(self.channel_mute_button)
        buttons.addWidget(self.channel_deaf_button)
        chv.addLayout(buttons)
        chv.addWidget(self.channels,1)
        self.channel_hint=QLabel(
            "Doppelklick auf einen Channel wechselt den Raum. "
            "Die Teilnehmer stehen eingerückt darunter. Rechtsklick auf "
            "einen Teilnehmer öffnet seine Audio-Einstellungen."
        )
        self.channel_hint.setWordWrap(True)
        chv.addWidget(self.channel_hint)

        userbox=QGroupBox("Teilnehmer"); uv=QVBoxLayout(userbox)
        self.speaker=QLabel("Aktive Sprecher: —"); self.speaker.setWordWrap(True)
        self.users=QListWidget()
        self.users.setContextMenuPolicy(Qt.CustomContextMenu)
        self.users.customContextMenuRequested.connect(self._user_context_menu)
        uv.addWidget(self.speaker); uv.addWidget(self.users)
        channel_layout.addWidget(chbox,1)
        self.mumble_tabs.addTab(channel_page,"Channels")
        # Separate user/chat controls from connection details.
        chat_page=QWidget(self.mumble_tabs)
        chat_page_layout=QVBoxLayout(chat_page)
        chat_page_layout.addWidget(userbox,1)
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
        typerow.addWidget(emoji_button(self.chat_input, 'mumble', chat_page))
        typerow.addWidget(self.chat_send)
        chatlayout.addLayout(typerow)
        chat_page_layout.addWidget(chatbox,2)
        self.mumble_tabs.addTab(chat_page,"Chat / TN")
        self.registered_panel=MumbleRegisteredPanel(self.client,self)
        self.mumble_tabs.addTab(self.registered_panel,"Benutzer")
        self.mumble_tabs.addTab(MumbleBanPanel(self.client,self),"Bannliste")

        publicbox=QGroupBox("Öffentliche Mumble-Serverliste")
        publiclayout=QVBoxLayout(publicbox)
        public_filters=QHBoxLayout()
        self.public_search=QLineEdit()
        self.public_search.setPlaceholderText("Name, Host oder Land suchen …")
        self.public_search.textChanged.connect(self._render_public_servers)
        self.public_country=QComboBox()
        self.public_country.addItem("Alle Länder","")
        self.public_country.currentIndexChanged.connect(self._render_public_servers)
        self.public_refresh=QPushButton("Originalliste laden")
        self.public_refresh.clicked.connect(self._load_public_servers)
        public_filters.addWidget(self.public_search,2)
        public_filters.addWidget(self.public_country,1)
        public_filters.addWidget(self.public_refresh)
        publiclayout.addLayout(public_filters)
        self.public_status=QLabel("Noch nicht geladen – zuerst offizielle Mumble-Liste")
        self.public_status.setWordWrap(True)
        publiclayout.addWidget(self.public_status)
        self.public_list=QListWidget()
        self.public_list.itemDoubleClicked.connect(self._connect_public_server)
        publiclayout.addWidget(self.public_list)
        self.public_use=QPushButton("Ausgewählten Server übernehmen (ohne Connect)")
        self.public_use.clicked.connect(self._use_public_server)
        publiclayout.addWidget(self.public_use)
        self.mumble_tabs.addTab(publicbox,"Server")

        cert_page=QWidget(self.mumble_tabs)
        certv=QVBoxLayout(cert_page)
        certv.addWidget(QLabel(
            "<b>Mumble-Zertifikatsverwaltung</b> – Zertifikate dienen als "
            "persönliche Mumble-Identität. Beim Export den privaten Schlüssel "
            "sicher aufbewahren."
        ))
        self.cert_manager=QComboBox()
        self.cert_manager.currentIndexChanged.connect(self._manager_cert_changed)
        certv.addWidget(self.cert_manager)
        self.cert_info=QLabel("Kein Zertifikat ausgewählt")
        self.cert_info.setWordWrap(True)
        self.cert_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        certv.addWidget(self.cert_info)
        certv.addWidget(QLabel("Zertifikat wird beim nächsten Verbindungsaufbau verwendet."))
        cert_actions=QGroupBox("Zertifikate verwalten")
        actions=QVBoxLayout(cert_actions)
        for buttons in (
            (("Neu erstellen",self._create_cert),
             ("Zertifikate aktualisieren",self._refresh_certs),
             ("Zertifikatsmodul prüfen",self._test_cert_backend)),
            (("P12 / PFX importieren",self._import_cert_p12),
             ("PEM + Schlüssel importieren",self._import_cert_pem)),
            (("P12 / PFX exportieren",self._export_cert_p12),
             ("PEM + Schlüssel exportieren",self._export_cert_pem)),
            (("Mit Zertifikat verbundenen Benutzer registrieren",self._register_current_user),),
            (("Ausgewähltes Zertifikat löschen",self._delete_cert),),
        ):
            row=QHBoxLayout()
            for label,callback in buttons:
                button=QPushButton(label)
                button.clicked.connect(callback)
                row.addWidget(button)
            actions.addLayout(row)
        certv.addWidget(cert_actions)
        self.cert_backend_label=QLabel("Zertifikatsmodul: noch nicht geprüft")
        self.cert_backend_label.setWordWrap(True)
        certv.addWidget(self.cert_backend_label)
        certv.addStretch(1)
        self.mumble_tabs.addTab(cert_page,"Zertifikate")
        for name,tip in (("Chat / TN","Chat und Teilnehmer"),("Benutzer","Registrierte Benutzer"),("Server","Öffentliche Mumble-Serverliste")):
            for idx in range(self.mumble_tabs.count()):
                if self.mumble_tabs.tabText(idx)==name:
                    self.mumble_tabs.setTabToolTip(idx,tip)
                    break

        self._refresh_audio()
        self._refresh_certs()

    def _refresh_audio(self):
        # ALSA hardware devices are often already owned by PipeWire/PulseAudio.
        # Offer PortAudio's default first, not device index 0 (often hw:0).
        selected_input=self.input.currentData() if self.input.count() else None
        selected_output=self.output.currentData() if self.output.count() else None
        self.input.blockSignals(True)
        self.output.blockSignals(True)
        self.input.clear()
        self.output.clear()
        self.input.addItem("System-Standardmikrofon (empfohlen)",None)
        self.output.addItem("System-Standardausgabe (empfohlen)",None)
        if sd is not None:
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
        for combo,old in ((self.input,selected_input),(self.output,selected_output)):
            idx=combo.findData(old)
            combo.setCurrentIndex(idx if idx>=0 else 0)
            combo.blockSignals(False)

    def _selected_cert(self):
        value=self.cert.currentData()
        return value if isinstance(value,dict) else None

    def _open_cert_tab(self):
        for i in range(self.mumble_tabs.count()):
            if self.mumble_tabs.tabText(i)=="Zertifikate":
                self.mumble_tabs.setCurrentIndex(i)
                break

    def _cert_changed(self,*_args):
        info=self._selected_cert()
        wanted=str(info.get("id") or "") if info else ""
        self.cert_manager.blockSignals(True)
        idx=next(
            (i for i in range(self.cert_manager.count())
             if isinstance(self.cert_manager.itemData(i),dict)
             and str(self.cert_manager.itemData(i).get("id") or "")==wanted),
            0
        )
        self.cert_manager.setCurrentIndex(idx)
        self.cert_manager.blockSignals(False)
        if info:
            self.cert_info.setText(
                "Name: "+str(info.get("name") or "")+"\n"+
                "Subjekt: "+str(info.get("subject") or "")+"\n"+
                "SHA-256: "+str(info.get("fingerprint") or "")+"\n"+
                "Gültig bis: "+str(info.get("not_after") or "")
            )
        else:
            self.cert_info.setText("Kein Zertifikat ausgewählt")
        self.settings.setValue("certificate_id",wanted)

    def _manager_cert_changed(self,*_args):
        data=self.cert_manager.currentData()
        selected=str(data.get("id") or "") if isinstance(data,dict) else ""
        index=next(
            (i for i in range(self.cert.count())
             if isinstance(self.cert.itemData(i),dict)
             and str(self.cert.itemData(i).get("id") or "")==selected),
            0
        )
        self.cert.setCurrentIndex(index)

    def _refresh_certs(self,*_args,select_id=None):
        previous=self._selected_cert()
        current_id=(select_id if select_id is not None
                    else (previous.get("id") if previous
                          else str(self.settings.value("certificate_id",""))))
        try:
            certs=list_certificates()
        except Exception as exc:
            self._error("Zertifikate konnten nicht gelesen werden: "+str(exc))
            return
        self.cert.blockSignals(True)
        self.cert_manager.blockSignals(True)
        self.cert.clear()
        self.cert_manager.clear()
        for combo in (self.cert,self.cert_manager):
            combo.addItem("Kein Zertifikat",None)
            for info in certs:
                combo.addItem(str(info.get("name") or info["id"]),dict(info))
            idx=next(
                (i for i in range(combo.count())
                 if isinstance(combo.itemData(i),dict)
                 and combo.itemData(i).get("id")==current_id),
                0
            )
            combo.setCurrentIndex(idx)
        self.cert.blockSignals(False)
        self.cert_manager.blockSignals(False)
        self._cert_changed()

    def _create_cert(self,*_args):
        name,ok=QInputDialog.getText(
            self,"Mumble-Zertifikat erstellen","Name der Identität:",
            text=self.nick.text().strip() or "FunkGateway Linux"
        )
        if not ok or not name.strip():
            return
        try:
            info=create_certificate(name.strip())
            self._refresh_certs(select_id=info["id"])
        except Exception as exc:
            QMessageBox.warning(self,"Mumble-Zertifikat",str(exc))

    def _test_cert_backend(self,*_args):
        result=certificate_backend_status()
        if result.get("ok"):
            self.cert_backend_label.setText(
                "Zertifikatsmodul: OK (cryptography "+
                str(result.get("version") or "")+")"
            )
        else:
            self.cert_backend_label.setText(
                "Zertifikatsmodul: Fehler – "+str(result.get("error") or "")
            )

    def _import_cert_p12(self):
        filename,_=QFileDialog.getOpenFileName(
            self,"Mumble-Zertifikat (P12/PFX) importieren","",
            "PKCS#12 (*.p12 *.pfx);;Alle Dateien (*)"
        )
        if not filename:
            return
        password,ok=QInputDialog.getText(
            self,"P12/PFX-Passwort",
            "Passwort (bei ungeschützten Dateien leer lassen):",
            QLineEdit.Password
        )
        if not ok:
            return
        try:
            info=import_pkcs12(filename,password or None)
            self._refresh_certs(select_id=info["id"])
        except Exception as exc:
            QMessageBox.warning(self,"Zertifikat importieren",str(exc))

    def _import_cert_pem(self):
        cert,_=QFileDialog.getOpenFileName(
            self,"PEM-Zertifikat auswählen","",
            "Zertifikate (*.pem *.crt *.cer);;Alle Dateien (*)"
        )
        if not cert:
            return
        key,_=QFileDialog.getOpenFileName(
            self,"Zugehörigen privaten PEM-Schlüssel auswählen","",
            "Private Schlüssel (*.pem *.key);;Alle Dateien (*)"
        )
        if not key:
            return
        try:
            info=import_pem(cert,key)
            self._refresh_certs(select_id=info["id"])
        except Exception as exc:
            QMessageBox.warning(self,"Zertifikat importieren",str(exc))

    def _cert_export_dir(self):
        CERT_DIR.mkdir(parents=True,exist_ok=True)
        return QFileDialog.getExistingDirectory(
            self,"Zielordner für Mumble-Zertifikat wählen",str(CERT_DIR),
            QFileDialog.ShowDirsOnly
        )

    def _export_cert_p12(self):
        info=self._selected_cert()
        if not info:
            QMessageBox.information(self,"Mumble-Zertifikate",
                                    "Bitte zuerst ein Zertifikat auswählen.")
            return
        folder=self._cert_export_dir()
        if not folder:
            return
        password,ok=QInputDialog.getText(
            self,"P12/PFX exportieren",
            "Export-Passwort (empfohlen, schützt den privaten Schlüssel):",
            QLineEdit.Password
        )
        if not ok:
            return
        if not password and QMessageBox.question(
            self,"Ungeschützter Export",
            "Ohne Passwort kann jeder mit Zugriff auf die P12-Datei Ihre "
            "Mumble-Identität verwenden. Trotzdem exportieren?",
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No
        )!=QMessageBox.Yes:
            return
        try:
            path=export_pkcs12(info["id"],folder,password or None)
            QMessageBox.information(self,"Zertifikat exportiert",
                                    "Export gespeichert:\n"+path)
        except Exception as exc:
            QMessageBox.warning(self,"Zertifikat exportieren",str(exc))

    def _export_cert_pem(self):
        info=self._selected_cert()
        if not info:
            QMessageBox.information(self,"Mumble-Zertifikate",
                                    "Bitte zuerst ein Zertifikat auswählen.")
            return
        folder=self._cert_export_dir()
        if not folder:
            return
        if QMessageBox.question(
            self,"Privater Schlüssel",
            "Beim PEM-Export wird auch der unverschlüsselte private Schlüssel "
            "gespeichert. Sicher verwahren! Fortfahren?",
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No
        )!=QMessageBox.Yes:
            return
        try:
            result=export_pem(info["id"],folder)
            QMessageBox.information(
                self,"Zertifikat exportiert",
                "Dateien:\n"+str(result["cert_path"])+
                "\n"+str(result["key_path"])
            )
        except Exception as exc:
            QMessageBox.warning(self,"Zertifikat exportieren",str(exc))

    def _register_current_user(self):
        if not self.client.connected:
            QMessageBox.information(
                self,"Mumble-Registrierung",
                "Zuerst mit dem gewünschten Zertifikat verbinden."
            )
            return
        if not self._selected_cert():
            QMessageBox.warning(
                self,"Mumble-Registrierung",
                "Bitte zuerst ein Zertifikat auswählen und damit verbinden."
            )
            return
        try:
            self.client.register_current_user()
            QMessageBox.information(
                self,"Mumble-Registrierung",
                "Registrierung beim Mumble-Server angefordert. "
                "Die Serverrechte entscheiden, ob sie zugelassen wird."
            )
        except Exception as exc:
            QMessageBox.warning(self,"Mumble-Registrierung",str(exc))

    def _delete_cert(self):
        info=self._selected_cert()
        if not info:
            return
        if self.client.connected:
            QMessageBox.warning(
                self,"Mumble-Zertifikat",
                "Bitte zuerst die Mumble-Verbindung trennen, "
                "bevor das aktive Zertifikat gelöscht wird."
            )
            return
        if QMessageBox.question(
            self,"Mumble-Zertifikat löschen",
            "Identität „"+str(info.get("name") or "")+"“ inklusive "
            "privatem Schlüssel unwiderruflich löschen?",
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No
        )!=QMessageBox.Yes:
            return
        try:
            delete_certificate(info["id"])
            self.settings.setValue("certificate_id","")
            self._refresh_certs(select_id="")
        except Exception as exc:
            QMessageBox.warning(self,"Zertifikat löschen",str(exc))

    def _refresh_favorites(self, selected=None):
        # Fixed favorite always first. Manual entry is the last option.
        old_host=self.host.text().strip().casefold()
        old_port=self.port.value()
        self.favorite_select.blockSignals(True)
        self.favorite_select.clear()
        for index,fav in enumerate(self._favorites):
            label=f"{fav['name']} — {fav['host']}:{fav['port']}"
            if fav.get("locked"):
                label+=" 🔒"
            self.favorite_select.addItem(label,index)
        self.favorite_select.addItem("Manueller Server",None)
        if selected is not None and 0<=selected<len(self._favorites):
            idx=selected
        elif selected is None:
            idx=next(
                (i for i,fav in enumerate(self._favorites)
                 if fav["host"].casefold()==old_host and fav["port"]==old_port),
                self.favorite_select.count()-1
            )
        else:
            idx=self.favorite_select.count()-1
        self.favorite_select.setCurrentIndex(idx)
        self.favorite_select.blockSignals(False)
        self._favorite_selected()

    def _favorite_selected(self,*_args):
        index=self.favorite_select.currentData()
        valid=isinstance(index,int) and 0<=index<len(self._favorites)
        can_edit=valid and not self._favorites[index].get("locked")
        self.favorite_edit.setEnabled(can_edit)
        self.favorite_delete.setEnabled(can_edit)
        if not valid:
            self.favorite_nick_label.setText("Favoriten-Nickname: allgemeiner Nickname")
            return
        fav=self._favorites[index]
        self.host.setText(fav["host"])
        self.port.setValue(fav["port"])
        self.favorite_nick_label.setText(
            "Favoriten-Nickname: "+(fav.get("username") or "allgemeiner Nickname")
        )

    def _favorite_form(self,existing=None):
        old=existing or {}
        title="Mumble-Favorit"
        values=[]
        for field,label,default in (
            ("name","Name:",old.get("name") or self.host.text().strip()),
            ("host","Hostname:",old.get("host") or self.host.text().strip()),
        ):
            value,ok=QInputDialog.getText(self,title,label,text=str(default))
            if not ok or not value.strip():
                return None
            values.append(value.strip())
        port,ok=QInputDialog.getInt(
            self,title,"Port:",int(old.get("port") or self.port.value()),1,65535,1
        )
        if not ok:
            return None
        username,ok=QInputDialog.getText(
            self,title,"Nickname nur für diesen Server (leer = allgemein):",
            text=str(old.get("username") or "")
        )
        if not ok:
            return None
        return {
            "name":values[0],"host":values[1],
            "port":int(port),"username":username.strip(),
        }

    def _favorite_add(self):
        data=self._favorite_form()
        if data is None:
            return
        if any(f["host"].casefold()==data["host"].casefold()
               and f["port"]==data["port"] for f in self._favorites):
            QMessageBox.information(self,"Mumble-Favoriten",
                "Für diesen Server ist bereits ein Favorit vorhanden.")
            return
        self._favorites.append(data)
        self._refresh_favorites(len(self._favorites)-1)
        self._save_settings()

    def _favorite_edit(self):
        index=self.favorite_select.currentData()
        if (not isinstance(index,int) or not 0<=index<len(self._favorites)
                or self._favorites[index].get("locked")):
            return
        data=self._favorite_form(self._favorites[index])
        if data is None:
            return
        self._favorites[index]=data
        self._refresh_favorites(index)
        self._save_settings()

    def _favorite_delete(self):
        index=self.favorite_select.currentData()
        if (not isinstance(index,int) or not 0<=index<len(self._favorites)
                or self._favorites[index].get("locked")):
            return
        fav=self._favorites[index]
        answer=QMessageBox.question(
            self,"Mumble-Favorit löschen",
            f"Favorit {fav['name']} wirklich löschen?"
        )
        if answer!=QMessageBox.Yes:
            return
        del self._favorites[index]
        self._refresh_favorites()
        self._save_settings()

    def _load_public_servers(self):
        if self._public_thread is not None:
            return
        self.public_refresh.setEnabled(False)
        self.public_status.setText("Lade vollständige offizielle Mumble-Serverliste …")
        self._public_detail=""
        self._public_source=""
        worker=MumblePublicServerLoader()
        thread=QThread(self)
        self._public_thread=thread
        self._public_worker=worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._public_loaded)
        worker.error.connect(self._public_error)
        worker.sourceChanged.connect(self._public_source_changed)
        worker.sourceDetail.connect(self._public_source_detail)
        worker.progress.connect(self._public_progress)
        worker.loaded.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._public_finished)
        thread.start()

    def _public_source_detail(self,reason):
        self._public_detail=str(reason or "")

    def _public_source_changed(self,source,total):
        self._public_source=str(source)
        if source=="official":
            self.public_status.setText(f"Offizielle Mumble-Liste: {total} Server")
            self.public_status.setStyleSheet("")
        else:
            self.public_status.setText(
                f"ACHTUNG: Fallback-Liste ({total} Server). "
                "Originalliste fehlgeschlagen – Details im Tooltip."
            )
            self.public_status.setToolTip(self._public_detail)
            self.public_status.setStyleSheet("color:#C77A14;font-weight:bold;")

    def _public_progress(self,done,total):
        if total:
            source="Original" if self._public_source=="official" else "Fallback"
            self.public_status.setText(
                f"{source}: Live-Status {done}/{total} Server"
            )

    def _public_loaded(self,servers):
        self._public_servers=list(servers or [])
        countries=sorted({
            str(row.get("country") or "Unbekannt")
            for row in self._public_servers
        },key=str.casefold)
        previous=self.public_country.currentData() or ""
        self.public_country.blockSignals(True)
        self.public_country.clear()
        self.public_country.addItem("Alle Länder","")
        for country in countries:
            self.public_country.addItem(country,country)
        idx=self.public_country.findData(previous)
        self.public_country.setCurrentIndex(idx if idx>=0 else 0)
        self.public_country.blockSignals(False)
        self._render_public_servers()

    def _public_error(self,message):
        self.public_status.setText("Mumble-Serverliste fehlgeschlagen: "+str(message))
        self.public_status.setStyleSheet("color:#C77A14")
        self.public_status.setToolTip(str(message))

    def _public_finished(self):
        self._public_thread=None
        self._public_worker=None
        self.public_refresh.setEnabled(True)

    def _render_public_servers(self,*_args):
        query=self.public_search.text().strip().casefold()
        country=self.public_country.currentData() or ""
        self.public_list.clear()
        count=0
        for row in sorted(
            self._public_servers,
            key=lambda x:(str(x.get("country") or "").casefold(),
                          str(x.get("name") or "").casefold())
        ):
            if country and row.get("country")!=country:
                continue
            terms=" ".join(str(row.get(k) or "")
                           for k in ("name","host","country","region","provider"))
            if query and query not in terms.casefold():
                continue
            users=row.get("users")
            usertext=str(users) if isinstance(users,int) else "?"
            display=(
                f"{row.get('country') or 'Unbekannt'} | "
                f"{row.get('name') or row.get('host')} | "
                f"{row.get('host')}:{row.get('port')} | {usertext} Nutzer"
            )
            item=QListWidgetItem(display)
            item.setData(Qt.UserRole,dict(row))
            self.public_list.addItem(item)
            count+=1
        source=("Offizielle Mumble-Liste" if self._public_source=="official"
                else ("Fallback-Liste" if self._public_source else "Keine Quelle"))
        self.public_status.setText(
            f"{count} angezeigt / {len(self._public_servers)} insgesamt · {source}"
        )
        self.public_status.setToolTip(
            "Grund für Fallback: "+self._public_detail
            if self._public_source=="legacy-fallback" else ""
        )

    def _connect_public_server(self,item):
        """Double-click selects the server and starts the native connection."""
        if not self._use_public_server(item):
            return
        self.mumble_tabs.setCurrentIndex(0)
        self.status.setText(
            "Native Mumble: verbinde zu "
            + self.host.text().strip() + ":" + str(self.port.value()) + " …"
        )
        self._connect()

    def _use_public_server(self,item=None):
        if item is None or isinstance(item,bool):
            item=self.public_list.currentItem()
        if item is None:
            return False
        row=item.data(Qt.UserRole)
        if not isinstance(row,dict):
            return False
        host=str(row.get("host") or "").strip()
        port=int(row.get("port") or 64738)
        if not host:
            return False
        # Server-specific passwords and channel names must not leak into a new
        # public-list connection. Keep them only when choosing the same server.
        changed=(host.casefold()!=self.host.text().strip().casefold()
                 or port!=self.port.value())
        if changed:
            self.password.clear()
            self.channel.clear()
        self.host.setText(host)
        self.port.setValue(port)
        matched=None
        for index,fav in enumerate(self._favorites):
            if fav["host"].casefold()==host.casefold() and fav["port"]==port:
                matched=index
                break
        self._refresh_favorites(matched)
        if matched is None:
            self.host.setText(host)
            self.port.setValue(port)
        self._save_settings()
        return True

    def _hotkey_status(self,status):
        self.ptt_hotkey_status.setText("Mumble-Hotkey: "+str(status))

    def _configure_ptt_hotkey(self,*_args):
        key=self.ptt_hotkey.hotkey()
        scope=self.ptt_hotkey_scope.currentData() or "local"
        self.local_ptt_hotkey.set_hotkey("")
        self.global_ptt_hotkey.stop()
        self.global_ptt_hotkey.set_hotkey("")
        if not key:
            self._hotkey_status("deaktiviert")
        elif scope=="global":
            self.global_ptt_hotkey.set_hotkey(key)
            if not self.global_ptt_hotkey.start():
                self.local_ptt_hotkey.set_hotkey(key)
                self._hotkey_status("systemweit nicht verfügbar – lokal aktiv")
        else:
            self.local_ptt_hotkey.set_hotkey(key)
            self._hotkey_status("lokal aktiv")
        self._save_settings()

    def _hotkey_ptt_press(self):
        self.set_mumble_ptt(True)

    def _hotkey_ptt_release(self):
        self.set_mumble_ptt(False)

    def set_mumble_ptt(self,active):
        permitted=(self.client.connected and self.ptt_enabled.isChecked()
                   and not self.self_mute.isChecked() and not self.self_deaf.isChecked())
        if not permitted:
            active=False
        if active and (self._server_mute or self._server_deaf):
            active=False
        self.client.set_pc_ptt(bool(active))
        self.ptt.setText("Mumble PTT · SENDEN" if active else "Mumble PTT halten")
        self.ptt.setStyleSheet(
            "background:#C62828;color:#FFFFFF;font-weight:bold;" if active else ""
        )
        window=self.window()
        button=getattr(window,"mumble_ptt_top_btn",None)
        if button is not None:
            button.setText("Mumble TX AKTIV" if active else "Mumble PTT")
            button.setStyleSheet(
                "background:#C62828;color:#FFFFFF;font-weight:bold;" if active else ""
            )

    def stop_ptt_hotkeys(self):
        self.local_ptt_hotkey.set_hotkey("")
        self.global_ptt_hotkey.stop()
        self.set_mumble_ptt(False)

    def _load_settings(self):
        import json
        self.host.setText(str(self.settings.value("host","voice.mumble-funk.de")))
        self.port.setValue(int(self.settings.value("port",64738)))
        self.nick.setText(str(self.settings.value("nickname","FunkGateway Linux")))
        self.master_volume.blockSignals(True)
        self.master_volume.setValue(int(self.settings.value("master_volume",100)))
        self.master_volume.blockSignals(False)
        self.client.set_playback_volume(self.master_volume.value())
        self.ptt_hotkey.set_hotkey(str(self.settings.value("ptt_hotkey","F10")))
        scope=str(self.settings.value("ptt_hotkey_scope","local"))
        idx=self.ptt_hotkey_scope.findData(scope)
        self.ptt_hotkey_scope.blockSignals(True)
        self.ptt_hotkey_scope.setCurrentIndex(idx if idx>=0 else 0)
        self.ptt_hotkey_scope.blockSignals(False)
        try:
            values=json.loads(str(self.settings.value("user_volumes","{}")))
            if isinstance(values,dict):
                self._user_volumes={
                    str(k):max(0,min(200,int(v))) for k,v in values.items()
                }
        except (TypeError,ValueError):
            self._user_volumes={}
        self.client.set_user_volumes(self._user_volumes)
        # Preserve existing favorites. Restore the permanent server even if a
        # previous configuration removed or modified its entry.
        self._favorites=[dict(DEFAULT_MUMBLE_FAVORITES[0])]
        seen={(self._favorites[0]["host"].casefold(),self._favorites[0]["port"])}
        try:
            stored=json.loads(str(self.settings.value("favorites","[]")))
            if not isinstance(stored,list):
                stored=[]
        except (TypeError,ValueError):
            stored=[]
        # The other three defaults are seeded once on first start, and stay
        # user-editable/deletable afterwards.
        seed_defaults=not self.settings.contains("radio_favorites_seeded_v1")
        # First upgrade adds the three radio servers to existing installations
        # too. Later removal stays removed.
        source=list(DEFAULT_MUMBLE_FAVORITES[1:])+stored if seed_defaults else stored
        for item in source:
            if not isinstance(item,dict):
                continue
            host=str(item.get("host") or "").strip()
            try:
                port=int(item.get("port") or 64738)
            except (TypeError,ValueError):
                continue
            if not host or not 1<=port<=65535:
                continue
            key=(host.casefold(),port)
            if key in seen:
                continue
            seen.add(key)
            self._favorites.append({
                "name":str(item.get("name") or host).strip() or host,
                "host":host,"port":port,
                "username":str(item.get("username") or "").strip(),
                "locked":False,
            })
        if seed_defaults:
            self.settings.setValue("radio_favorites_seeded_v1",True)
            self.settings.setValue("favorites",json.dumps(self._favorites))
            self.settings.sync()
        self._refresh_favorites()

    def _save_settings(self):
        import json
        self.settings.setValue("host",self.host.text().strip())
        self.settings.setValue("port",self.port.value())
        self.settings.setValue("nickname",self.nick.text().strip())
        self.settings.setValue("master_volume",self.master_volume.value())
        self.settings.setValue("ptt_hotkey",self.ptt_hotkey.hotkey())
        self.settings.setValue("ptt_hotkey_scope",self.ptt_hotkey_scope.currentData())
        self.settings.setValue("user_volumes",json.dumps(self._user_volumes))
        self.settings.setValue("favorites",json.dumps(self._favorites))
        self.settings.sync()

    def _master_volume_changed(self,value):
        self.client.set_playback_volume(value)
        self._save_settings()

    def _change_user_volume(self,name,percent):
        self.client.set_user_volume(name,percent)
        key=self.client.volume_key(name)
        if int(percent)==100:
            self._user_volumes.pop(key,None)
        else:
            self._user_volumes[key]=int(percent)

    def _update_mumble_self_state(self,row=None):
        if row is None:
            self._server_mute=False
            self._server_deaf=False
            self._self_mute_active=False
            self._self_deaf_active=False
            text="Self-Mute: —  ·  Self-Deaf: —  ·  Server-Mute: —  ·  Server-Deaf: —"
        else:
            self._self_mute_active=bool(row.get("local_mute"))
            self._self_deaf_active=bool(row.get("local_deaf"))
            self._server_mute=bool(row.get("server_mute"))
            self._server_deaf=bool(row.get("server_deaf"))
            text=(
                "Self-Mute: "+("AN" if self._self_mute_active else "AUS")+
                "  ·  Self-Deaf: "+("AN" if self._self_deaf_active else "AUS")+
                "  ·  Server-Mute: "+("AKTIV" if self._server_mute else "AUS")+
                "  ·  Server-Deaf: "+("AKTIV" if self._server_deaf else "AUS")
            )
            for box,val in ((self.self_mute,self._self_mute_active),
                            (self.self_deaf,self._self_deaf_active)):
                box.blockSignals(True)
                box.setChecked(val)
                box.blockSignals(False)
        style=("color:#F2994A;font-weight:bold;"
               if self._server_mute or self._server_deaf or
               self._self_mute_active or self._self_deaf_active else "")
        self.mumble_audio_state.setText(text)
        self.mumble_audio_state.setStyleSheet(style)
        self.mumble_audio_detail.setText(text)
        self.mumble_audio_detail.setStyleSheet(style)
        if self._self_mute_active or self._self_deaf_active or self._server_mute or self._server_deaf:
            self.set_mumble_ptt(False)

    def _self_mute_changed(self,enabled):
        if not self.client.connected:
            self.self_mute.blockSignals(True)
            self.self_mute.setChecked(False)
            self.self_mute.blockSignals(False)
            return
        try:
            self.client.set_self_mute(enabled)
        except Exception as exc:
            self._error(str(exc))

    def _self_deaf_changed(self,enabled):
        if not self.client.connected:
            self.self_deaf.blockSignals(True)
            self.self_deaf.setChecked(False)
            self.self_deaf.blockSignals(False)
            return
        try:
            self.client.set_self_deaf(enabled)
        except Exception as exc:
            self._error(str(exc))

    @staticmethod
    def _mumble_user_status(row):
        tokens=[]
        registered=row.get("registered")
        if registered is True:
            tokens.append("✓ Registriert")
        elif registered is False:
            tokens.append("○ Gast")
        else:
            tokens.append("? Identität")
        if row.get("local_mute"):
            tokens.append("🔇 Self-Mute")
        if row.get("local_deaf"):
            tokens.append("🔇 Self-Deaf")
        if row.get("server_mute"):
            tokens.append("🔒 Server-Mute")
        if row.get("server_deaf"):
            tokens.append("🔒 Server-Deaf")
        if row.get("local_user_mute"):
            tokens.append("🔇 Lokal stumm")
        return "  ·  ".join(tokens)

    @staticmethod
    def _mumble_user_status_tooltip(row):
        registration=(
            "Am Server registriert (Benutzer-ID: "+str(row.get("user_id"))+")"
            if row.get("registered") is True else
            "Nicht registriert / Gast"
            if row.get("registered") is False else
            "Registrierungsstatus vom Server nicht verfügbar"
        )
        return str(row.get("name") or "")+"\n"+registration+"\n"+(
            "Rechtsklick: lokale Audio-Einstellungen / Self-Mute und Self-Deaf"
        )

    def _sync_quick_mumble_buttons(self,*_args):
        if not hasattr(self,"channel_mute_button"):
            return
        for button,checked,label in (
            (self.channel_mute_button,self.self_mute.isChecked(),"Mikrofon"),
            (self.channel_deaf_button,self.self_deaf.isChecked(),"Empfang"),
        ):
            button.blockSignals(True)
            button.setChecked(checked)
            button.setText(label+(" STUMM" if button is self.channel_mute_button and checked
                                  else " TAUB" if checked else " an"))
            button.blockSignals(False)

    def _locate_my_channel(self):
        self._initial_channel_focus_pending=True
        self._refresh_channels()
        self._focus_current_channel_once()

    def _refresh_channels_after_edit(self):
        # pymumble receives server channel updates asynchronously. Check more
        # than once without stealing the user's tree selection or scroll.
        for delay in (200, 650, 1200, 2200):
            QTimer.singleShot(delay, self._refresh_channels)

    def _channel_context_menu(self,pos):
        item=self.channels.itemAt(pos)
        if item is None:
            return
        data=item.data(0,Qt.UserRole)
        if not isinstance(data,dict):
            return
        if data.get("kind")=="user":
            self._show_mumble_user_menu(data,self.channels.viewport().mapToGlobal(pos))
            return
        if data.get("kind")!="channel" or not self.client.connected:
            return
        menu=QMenu(self)
        create=menu.addAction("Unterraum anlegen …")
        edit=menu.addAction("Raum bearbeiten …")
        edit.setEnabled(int(data.get("id",-1))!=0)
        acl=menu.addAction("Berechtigungen verwalten …")
        delete=menu.addAction("Raum löschen …")
        delete.setEnabled(int(data.get("id",-1))!=0)
        selected=menu.exec(self.channels.viewport().mapToGlobal(pos))
        if selected not in (create,edit,delete,acl):
            return
        if selected==acl:
            dialog=MumbleAclClassicDialog(self.client,int(data["id"]),str(data.get("name") or "Raum"),self)
            dialog.exec()
            return
        try:
            if selected==delete:
                channel_id=int(data["id"])
                name=str(data.get("name") or f"Raum {channel_id}")
                children=[row for row in self.client.channel_snapshot()
                          if row.get("parent")==channel_id]
                if children:
                    QMessageBox.warning(self,"Mumble – Raum löschen",
                        "Dieser Raum enthält Unterräume. Bitte zuerst die Unterräume entfernen.")
                    return
                answer=QMessageBox.question(
                    self,"Mumble – Raum wirklich löschen?",
                    f"Raum „{name}“ endgültig löschen?\\n"
                    "Der Mumble-Server muss die Berechtigung dazu erteilen.",
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer!=QMessageBox.StandardButton.Yes:
                    return
                self.client.delete_channel(channel_id)
                self._refresh_channels_after_edit()
                QMessageBox.information(self,"Mumble – Raumverwaltung",
                    "Löschanforderung gesendet. Ob der Raum entfernt wird, entscheidet der Server.")
                return
            if selected==create:
                dialog=ChannelEditor(self,create=True)
                if dialog.exec()!=QDialog.DialogCode.Accepted:
                    return
                values=dialog.values()
                self.client.create_channel(data["id"],values["name"],values["temporary"])
                # Creation is asynchronous. Newly created channel is identified
                # by parent+name, not by an assumed channel ID.
                def apply_position():
                    rows=self.client.channel_snapshot()
                    matches=[row for row in rows if row["parent"]==int(data["id"])
                             and row["name"]==values["name"]]
                    if len(matches)==1 and self.client.connected:
                        self.client.edit_channel(matches[0]["id"],values["name"],
                                                 values["description"],values["position"])
                QTimer.singleShot(1000,apply_position)
                self._refresh_channels_after_edit()
            else:
                details=self.client.channel_details(data["id"])
                dialog=ChannelEditor(self,create=False,details=details)
                if dialog.exec()!=QDialog.DialogCode.Accepted:
                    return
                values=dialog.values()
                self.client.edit_channel(data["id"],values["name"],
                                         values["description"],values["position"])
                self._refresh_channels_after_edit()
            QMessageBox.information(self,"Mumble-Raum",
                "Änderung an den Server gesendet. Falls das Recht fehlt, lehnt der Server sie ab.")
        except Exception as exc:
            QMessageBox.warning(self,"Mumble – Raumverwaltung",str(exc))

    def _show_mumble_user_menu(self,data,global_pos):
        # Never offer server moderation through ordinary right-click.
        if not self.client.connected:
            return
        menu=QMenu(self)
        if data.get("is_self"):
            mute=menu.addAction(
                "🔇 Eigenes Mikrofon wieder einschalten" if self.self_mute.isChecked()
                else "🔇 Eigenes Mikrofon stummschalten"
            )
            deaf=menu.addAction(
                "🔈 Eigenen Empfang wieder einschalten" if self.self_deaf.isChecked()
                else "🔇 Eigenen Empfang taub schalten"
            )
            server_mute=bool(data.get("server_mute"))
            server_deaf=bool(data.get("server_deaf"))
            if server_mute or server_deaf:
                menu.addSeparator()
                status=menu.addAction(
                    "🔒 Server-Mute: "+("AN" if server_mute else "AUS")+
                    " · Server-Deaf: "+("AN" if server_deaf else "AUS")
                )
                status.setEnabled(False)
            chosen=menu.exec(global_pos)
            if chosen==mute:
                self.self_mute.setChecked(not self.self_mute.isChecked())
            elif chosen==deaf:
                self.self_deaf.setChecked(not self.self_deaf.isChecked())
            return

        name=str(data.get("name") or "")
        volume=menu.addAction(
            f"🔊 Lautstärke einstellen … ({self.client.user_volume(name)} %)"
        )
        local=menu.addAction(
            "🔈 Lokale Stummschaltung aufheben" if data.get("local_user_mute")
            else "🔇 Diesen Teilnehmer nur für mich stummschalten"
        )
        kick=menu.addAction("Benutzer kicken …")
        ban=menu.addAction("Benutzer bannen …")
        chosen=menu.exec(global_pos)
        try:
            if chosen in (kick,ban):
                self._moderate_mumble_participant(data,chosen==ban)
            elif chosen==volume:
                self._user_volume_popup(name)
            elif chosen==local:
                self.client.set_local_user_mute(
                    data["session"],not data.get("local_user_mute")
                )
                # Local muting is not a server state; show immediately.
                self._participants(self.client.participants())
        except Exception as exc:
            self._error(str(exc))

    def _user_context_menu(self,pos):
        item=self.users.itemAt(pos)
        if item is None:
            return
        data=item.data(Qt.UserRole)
        if not isinstance(data,dict) or data.get("is_self"):
            return
        menu=QMenu(self)
        name=str(data.get("name") or "")
        volume=menu.addAction(
            f"🔊 Lautstärke einstellen … ({self.client.user_volume(name)} %)"
        )
        local=menu.addAction(
            "🔊 Lokale Stummschaltung aufheben" if data.get("local_user_mute")
            else "🔇 Lokal stummschalten"
        )
        menu.addSeparator()
        server_mute=menu.addAction(
            "🔒 Server-Mute aufheben" if data.get("server_mute")
            else "🔒 Serverseitig stummschalten"
        )
        server_deaf=menu.addAction(
            "🔒 Server-Deaf aufheben" if data.get("server_deaf")
            else "🔒 Serverseitig taub schalten"
        )
        server_mute.setToolTip("Erfordert Mumble-Serverrechte")
        server_deaf.setToolTip("Erfordert Mumble-Serverrechte")
        kick=menu.addAction("Benutzer kicken …")
        ban=menu.addAction("Benutzer bannen …")
        chosen=menu.exec(self.users.viewport().mapToGlobal(pos))
        try:
            if chosen==volume:
                self._user_volume_popup(name)
            elif chosen==local:
                self.client.set_local_user_mute(
                    data["session"],not data.get("local_user_mute")
                )
            elif chosen==server_mute:
                self.client.set_server_user_mute(
                    data["session"],not data.get("server_mute")
                )
            elif chosen==server_deaf:
                self.client.set_server_user_deaf(
                    data["session"],not data.get("server_deaf")
                )
            elif chosen in (kick,ban):
                self._moderate_mumble_participant(data,chosen==ban)
        except Exception as exc:
            self._error(str(exc))

    def _moderate_mumble_participant(self,data,ban):
        name=str(data.get("name") or "Teilnehmer")
        reason,ok=QInputDialog.getText(self,"Mumble – "+("Bannen" if ban else "Kicken"),
                        "Grund für "+name+" (optional):")
        if not ok:
            return
        confirm=QMessageBox.question(self,"Mumble – Aktion bestätigen",
            ("Benutzer „"+name+"“ dauerhaft bannen?" if ban
             else "Benutzer „"+name+"“ vom Server kicken?"),
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm!=QMessageBox.StandardButton.Yes:
            return
        try:
            self.client.moderate_user(int(data["session"]),ban=ban,reason=reason)
            QMessageBox.information(self,"Mumble",
                "Anforderung gesendet. Der Server prüft die Berechtigungen.")
        except Exception as exc:
            QMessageBox.warning(self,"Mumble – Aktion abgelehnt",str(exc))

    def _user_volume_popup(self,name):
        old=self.client.user_volume(name)
        dlg=QDialog(self)
        dlg.setWindowTitle("Mumble-Lautstärke – "+name)
        dlg.setMinimumWidth(390)
        layout=QVBoxLayout(dlg)
        layout.addWidget(QLabel("Lokale Empfangslautstärke für "+name))
        row=QHBoxLayout()
        slider=QSlider(Qt.Horizontal)
        slider.setRange(0,200)
        slider.setValue(old)
        value=QSpinBox()
        value.setRange(0,200)
        value.setSuffix(" %")
        value.setValue(old)
        slider.valueChanged.connect(value.setValue)
        value.valueChanged.connect(slider.setValue)
        value.valueChanged.connect(lambda n:self._change_user_volume(name,n))
        row.addWidget(slider,1)
        row.addWidget(value)
        layout.addLayout(row)
        reset=QPushButton("Auf 100 % zurücksetzen")
        reset.clicked.connect(lambda:value.setValue(100))
        layout.addWidget(reset)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec()==QDialog.Accepted:
            self._save_settings()
        else:
            self._change_user_volume(name,old)

    def _chat_line(self,source,message):
        plain=html.unescape(re.sub(r"<[^>]*>"," ",str(message or "")))
        plain=plain.replace(chr(13)," ").replace(chr(10)," ")
        self.chat_log.appendPlainText(
            f"[{datetime.now():%H:%M:%S}] {source}: {plain}"
        )

    def _chat_received(self,item):
        who=self.client.chat_sender_name(item.get("actor"))
        scope="Privat" if item.get("sessions") else "Channel"
        self._chat_line(f"{scope} · {who}",item.get("message"))

    def _send_chat(self):
        message=self.chat_input.text().strip()
        if not message:
            return
        try:
            dest=self.client.send_chat(message,self.chat_target.currentData())
            if dest is not None:
                self._chat_line("Ich → "+dest,message)
                self.chat_input.clear()
        except Exception as exc:
            self._error(str(exc))

    def _connect(self):
        self._save_settings()
        favorite_index=self.favorite_select.currentData()
        favorite=(self._favorites[favorite_index]
                  if isinstance(favorite_index,int)
                  and 0<=favorite_index<len(self._favorites) else None)
        nickname=self.nick.text().strip()
        if (favorite is not None
                and favorite["host"].casefold()==self.host.text().strip().casefold()
                and favorite["port"]==self.port.value()):
            nickname=favorite.get("username") or nickname
        cert=self.cert.currentData()
        certfile=cert.get("cert_path","") if isinstance(cert,dict) else ""
        keyfile=cert.get("key_path","") if isinstance(cert,dict) else ""
        try:
            self.client.connect_async(
                self.host.text().strip(),self.port.value(),nickname,
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
        self.chat_send.setEnabled(on)
        if on:
            self._update_mumble_self_state()
            self._initial_channel_focus_pending=True
            self._refresh_channels()
            self._focus_current_channel_once()
        else:
            self._update_mumble_self_state()
            self._initial_channel_focus_pending=False
            self._channel_rows=[]
            self._participant_rows=[]
            self.channels.clear(); self.users.clear(); self.current_channel.setText("—")
            self.chat_target.clear()
            self.chat_target.addItem("Aktueller Channel (öffentlich)",None)
            for control in (self.self_mute,self.self_deaf):
                control.blockSignals(True)
                control.setChecked(False)
                control.blockSignals(False)

    def _status(self,text):
        self.status.setText(str(text))

    def _channel_changed(self,name):
        self.current_channel.setText(str(name or "—"))

    def _mumble_tab_changed(self,index):
        if self.mumble_tabs.tabText(index)=="Channels":
            # Channel details may arrive after the connected signal.
            self._refresh_channels()
            self._focus_current_channel_once()

    def _focus_current_channel_once(self):
        """Locate our channel only on first visit after connecting.

        Normal participant/speaker updates must never steal scroll position.
        """
        if not self._initial_channel_focus_pending:
            return
        if self.mumble_tabs.tabText(self.mumble_tabs.currentIndex())!="Channels":
            return
        current=next(
            (row for row in self._channel_rows if row.get("current")),
            None
        )
        if current is None:
            return  # Wait for the server's own channel to be reported.
        target_id=current.get("id")
        def find(node):
            data=node.data(0,Qt.UserRole)
            if (isinstance(data,dict) and data.get("kind")=="channel"
                    and data.get("id")==target_id):
                return node
            for i in range(node.childCount()):
                hit=find(node.child(i))
                if hit is not None:
                    return hit
            return None
        item=None
        for i in range(self.channels.topLevelItemCount()):
            item=find(self.channels.topLevelItem(i))
            if item is not None:
                break
        if item is None:
            return
        parent=item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent=parent.parent()
        item.setExpanded(True)
        self.channels.setCurrentItem(item)
        self.channels.scrollToItem(
            item,QAbstractItemView.ScrollHint.PositionAtCenter
        )
        self._initial_channel_focus_pending=False

    def _toggle_channel_expand(self):
        self._channel_expand_all=not self._channel_expand_all
        if self._channel_expand_all:
            self.channels.expandAll()
            self.expand_channels.setText("Alle Räume zuklappen")
        else:
            self.channels.collapseAll()
            self.expand_channels.setText("Alle Räume aufklappen")

    def _refresh_channels(self):
        snapshot=self.client.channel_snapshot()
        if snapshot != self._channel_rows:
            self._channel_rows=snapshot
            self._render_channels()

    def _render_channels(self):
        channels=self._channel_rows
        participants=self._participant_rows
        old_selected=self.channels.currentItem()
        selected=None
        if old_selected is not None:
            data=old_selected.data(0,Qt.UserRole)
            if isinstance(data,dict):
                selected=(data.get("kind"),data.get("id"),data.get("session"))
        # Remember manual expansion state, including when the tree is updated
        # every 0.5s as speakers join, leave or change channel.
        expanded={}
        def remember(node):
            data=node.data(0,Qt.UserRole)
            if isinstance(data,dict) and data.get("kind")=="channel":
                expanded[data.get("id")]=node.isExpanded()
            for i in range(node.childCount()):
                remember(node.child(i))
        for i in range(self.channels.topLevelItemCount()):
            remember(self.channels.topLevelItem(i))
        # Tree rebuilds must never bring the selected row back into view.
        # Save scrollbars before Qt clears/reselects items.
        vertical=self.channels.verticalScrollBar()
        horizontal=self.channels.horizontalScrollBar()
        vpos=vertical.value()
        hpos=horizontal.value()
        self.channels.setUpdatesEnabled(False)
        self.channels.blockSignals(True)
        try:
            self.channels.clear()
            by_id={}
            for row in channels:
                cid=row["id"]
                label=("▶  " if row.get("current") else "📁  ")+str(row.get("name") or "")
                item=QTreeWidgetItem([label,str(int(row.get("users") or 0))])
                item.setData(0,Qt.UserRole,{"kind":"channel",**row})
                item.setToolTip(0,"Doppelklick: Channel betreten")
                if row.get("current"):
                    font=item.font(0)
                    font.setBold(True)
                    item.setFont(0,font)
                    item.setToolTip(0,"Aktueller Channel")
                by_id[cid]=item
            for row in sorted(channels,key=lambda r:(int(r.get("position") or 0),str(r.get("name") or "").casefold(),int(r["id"]))):
                cid=row["id"]
                parent=row.get("parent")
                if parent in by_id and parent!=cid:
                    by_id[parent].addChild(by_id[cid])
                else:
                    self.channels.addTopLevelItem(by_id[cid])
            for row in sorted(participants,key=lambda x:str(x.get("name") or "").casefold()):
                cid=row.get("channel_id")
                if cid not in by_id:
                    continue
                kind=("whisper" if row.get("speech_mode")=="whisper"
                      else ("self" if row.get("is_self") else "talk")) if row.get("talking") else "idle"
                name=str(row.get("name") or "")
                user=QTreeWidgetItem(["  "+name,"",self._mumble_user_status(row)])
                user.setIcon(0,self._mouth_icon(kind))
                user.setData(0,Qt.UserRole,{"kind":"user",**row})
                user.setToolTip(0,self._mumble_user_status_tooltip(row))
                by_id[cid].addChild(user)
            for cid,item in by_id.items():
                if cid in expanded:
                    item.setExpanded(expanded[cid])
                elif self._channel_expand_all or any(
                    row.get("channel_id")==cid for row in participants
                ):
                    item.setExpanded(True)
            # A selected item is remembered without automatically scrolling
            # to it. Avoid setCurrentItem's EnsureVisible behavior by restoring
            # the viewport position after selection below.
            if selected:
                def restore(item):
                    data=item.data(0,Qt.UserRole)
                    if (isinstance(data,dict) and
                        (data.get("kind"),data.get("id"),data.get("session"))==selected):
                        self.channels.setCurrentItem(item)
                        return True
                    return any(restore(item.child(i)) for i in range(item.childCount()))
                for i in range(self.channels.topLevelItemCount()):
                    if restore(self.channels.topLevelItem(i)):
                        break
        finally:
            vertical.setValue(min(vpos,vertical.maximum()))
            horizontal.setValue(min(hpos,horizontal.maximum()))
            self.channels.blockSignals(False)
            self.channels.setUpdatesEnabled(True)
        self._focus_current_channel_once()

    def _move_channel(self,item,column=0):
        data=item.data(0,Qt.UserRole)
        if not isinstance(data,dict) or data.get("kind")!="channel":
            return
        path=dict(self.client.channel_paths()).get(data["id"],data.get("name",""))
        if self.client.move_to_path(path):
            self.channel.setText(path)
            self._refresh_channels()

    def _update_speaker_icons(self):
        """Update speaking/mute icons in place, without rebuilding or scrolling."""
        by_session={int(row["session"]):row for row in self._participant_rows
                    if row.get("session") is not None}
        def walk(node):
            data=node.data(0,Qt.UserRole)
            if isinstance(data,dict) and data.get("kind")=="user":
                row=by_session.get(data.get("session"))
                if row is not None:
                    talking=bool(row.get("talking"))
                    kind=("whisper" if row.get("speech_mode")=="whisper"
                          else ("self" if row.get("is_self") else "talk")
                          ) if talking else "idle"
                    if (data.get("talking")!=talking or
                            data.get("speech_mode")!=row.get("speech_mode")):
                        node.setIcon(0,self._mouth_icon(kind))
                    if data!=dict({"kind":"user",**row}):
                        node.setText(2,self._mumble_user_status(row))
                        node.setToolTip(0,self._mumble_user_status_tooltip(row))
                        node.setData(0,Qt.UserRole,{"kind":"user",**row})
            for index in range(node.childCount()):
                walk(node.child(index))
        for index in range(self.channels.topLevelItemCount()):
            walk(self.channels.topLevelItem(index))

    def _participants(self,rows):
        self_row=next((row for row in rows if row.get("is_self")),None)
        self._update_mumble_self_state(self_row)
        self._sync_quick_mumble_buttons()
        new_rows=list(rows or [])
        previous_structure={
            (row.get("session"),row.get("name"),row.get("channel_id"))
            for row in self._participant_rows
        }
        new_structure={
            (row.get("session"),row.get("name"),row.get("channel_id"))
            for row in new_rows
        }
        if new_rows != self._participant_rows:
            self._participant_rows=new_rows
            if new_structure!=previous_structure:
                self._channel_rows=self.client.channel_snapshot()
                self._render_channels()
            else:
                self._update_speaker_icons()
        choices=[("Aktueller Channel (öffentlich)",None)]
        choices.extend((str(row.get("name") or ""),row.get("session"))
                       for row in rows if not row.get("is_self"))
        current=[(self.chat_target.itemText(i),self.chat_target.itemData(i))
                 for i in range(self.chat_target.count())]
        if choices!=current:
            previous=self.chat_target.currentData()
            popup=self.chat_target.view().isVisible()
            scroll=self.chat_target.view().verticalScrollBar().value() if popup else None
            self.chat_target.blockSignals(True)
            self.chat_target.clear()
            for name,session in choices:
                self.chat_target.addItem(name,session)
            idx=self.chat_target.findData(previous)
            self.chat_target.setCurrentIndex(idx if idx>=0 else 0)
            self.chat_target.blockSignals(False)
            if popup and scroll is not None:
                self.chat_target.view().verticalScrollBar().setValue(scroll)
        self.users.clear()
        for row in rows:
            if row.get("talking"):
                kind="whisper" if row.get("speech_mode")=="whisper" else ("self" if row.get("is_self") else "talk")
            else:
                kind="idle"
            item=QListWidgetItem(self._mouth_icon(kind),f"{row.get('name','')} — {row.get('channel','')}")
            item.setData(Qt.UserRole,dict(row))
            self.users.addItem(item)

    def _speakers(self,names):
        self.speaker.setText("Aktive Sprecher: "+(", ".join(names) if names else "—"))

    def _input_level(self,db):
        self.in_level.setText(f"Mikrofon: {db:.1f} dBFS" if db>-60 else "Mikrofon: < -60 dBFS")

    def _output_level(self,db):
        self.out_level.setText(f"Mumble: {db:.1f} dBFS" if db>-60 else "Mumble: < -60 dBFS")

    def _error(self,text):
        self.status.setText(str(text))
        QMessageBox.warning(self,"Mumble",str(text))
