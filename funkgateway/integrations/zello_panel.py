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
import re
from html import unescape
from urllib.parse import urlencode
from html.parser import HTMLParser
from datetime import datetime, timezone
from PySide6.QtCore import QUrl, Signal, QTimer, Qt, QEvent, QDateTime
from PySide6.QtGui import QKeySequence
from PySide6.QtNetwork import QAbstractSocket, QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWebSockets import QWebSocket
from ..hotkeys import LocalPttHotkey
from ..global_hotkey import GlobalPttHotkey
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QHBoxLayout,QLabel,
                               QLineEdit,QPushButton,QCheckBox,QGroupBox,QComboBox,QListWidget,QListWidgetItem,QTabWidget,QSlider,QApplication)

class ZelloPanel(QWidget):
    connectedChanged = Signal(bool)
    talkerChanged = Signal(str)
    statusChanged = Signal(str)
    audioError = Signal(str)
    pttStateChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected = False
        self.channel_online = False
        self.talker_name = ""
        self._requested_disconnect = False
        self._streams = {}
        self._rx_packet_counts = {}
        self._rx_event_details = {}
        self._audio_queue = queue.Queue(maxsize=120)
        self._audio_stop = threading.Event()
        self._audio_thread = None
        self._last_packet = 0.0
        self._known_speakers = set()
        self._ptt_hotkey_setting = ""
        self._ptt_hotkey_scope = "local"
        self._hotkey_applied=False
        self._channel_favorites = set()
        self._pending_channel_switch = ""
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
        self.rx_packets=QLabel("RX-Audio: noch keine Pakete")
        self.rx_packets.setWordWrap(True)
        self.rx_packets.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.rx_packets)
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
        directory=QGroupBox("Buddyliste (lokal)")
        directory_form=QVBoxLayout(directory)
        directory_form.addWidget(QLabel("Buddys – bekannte Zello-Namen"))
        buddy_row=QHBoxLayout()
        self.buddy_search=QLineEdit()
        self.buddy_search.setPlaceholderText("Buddys filtern")
        self.buddy_search.textChanged.connect(self._refresh_directories)
        buddy_row.addWidget(self.buddy_search)
        self.buddy_add=QLineEdit()
        self.buddy_add.setPlaceholderText("Buddy hinzufügen")
        buddy_row.addWidget(self.buddy_add)
        add_buddy=QPushButton("+")
        add_buddy.clicked.connect(self._add_buddy)
        buddy_row.addWidget(add_buddy)
        directory_form.addLayout(buddy_row)
        self.buddy_list=QListWidget()
        self.buddy_list.setMaximumHeight(105)
        self.buddy_list.itemDoubleClicked.connect(self._choose_buddy)
        directory_form.addWidget(self.buddy_list)
        buddy_actions=QHBoxLayout()
        choose_buddy=QPushButton("Buddy als Kanalziel wählen")
        choose_buddy.clicked.connect(self._choose_buddy)
        remove_buddy=QPushButton("Buddy entfernen")
        remove_buddy.clicked.connect(self._remove_buddy)
        buddy_actions.addWidget(choose_buddy)
        buddy_actions.addWidget(remove_buddy)
        directory_form.addLayout(buddy_actions)
        channels_box=QGroupBox("Kanalfavoriten (lokal)")
        channels_form=QVBoxLayout(channels_box)
        channels_form.addWidget(QLabel("Kanäle – gespeicherte Favoriten"))
        channel_row=QHBoxLayout()
        self.channel_search=QLineEdit()
        self.channel_search.setPlaceholderText("Favoriten durchsuchen")
        self.channel_search.textChanged.connect(self._refresh_directories)
        channel_row.addWidget(self.channel_search)
        self.channel_add=QLineEdit()
        self.channel_add.setPlaceholderText("Kanalnamen eintragen")
        channel_row.addWidget(self.channel_add)
        add_channel=QPushButton("+")
        add_channel.clicked.connect(self._add_favorite)
        channel_row.addWidget(add_channel)
        channels_form.addLayout(channel_row)
        self.channel_list=QListWidget()
        self.channel_list.setMaximumHeight(105)
        self.channel_list.itemDoubleClicked.connect(self._switch_to_favorite)
        channels_form.addWidget(self.channel_list)
        channel_actions=QHBoxLayout()
        choose_channel=QPushButton("Zum Favoriten wechseln")
        choose_channel.clicked.connect(self._switch_to_favorite)
        remove_channel=QPushButton("Favorit entfernen")
        remove_channel.clicked.connect(self._remove_favorite)
        channel_actions.addWidget(choose_channel)
        channel_actions.addWidget(remove_channel)
        channels_form.addLayout(channel_actions)
        note=QLabel("Nur lokal gespeicherte Namen: keine Online-Kanalsuche und "
                    "kein Zello-Kontaktbuch. Doppelklick wechselt automatisch den Kanal. "
                    "Gezielte PTT ist nur innerhalb des verbundenen Kanals möglich.")
        note.setWordWrap(True)
        channels_form.addWidget(note)
        outer.addWidget(directory)
        outer.addWidget(channels_box)
        self._refresh_directories()
        hotkey_row=QHBoxLayout()
        self.hotkey_edit=QLineEdit()
        self.hotkey_edit.setPlaceholderText("z. B. F9 oder Ctrl+Shift+Z")
        self.hotkey_scope=QComboBox()
        self.hotkey_scope.addItem("Nur FunkGateway","local")
        self.hotkey_scope.addItem("Systemweit (X11)","global")
        self.capture_hotkey_btn=QPushButton("Taste erfassen")
        self.capture_hotkey_btn.clicked.connect(self._start_hotkey_capture)
        self._capturing_hotkey=False
        self.hotkey_apply=QPushButton("Hotkey übernehmen")
        self.hotkey_apply.clicked.connect(self._configure_hotkey)
        hotkey_row.addWidget(QLabel("Zello-PTT-Hotkey:"))
        hotkey_row.addWidget(self.hotkey_edit)
        hotkey_row.addWidget(self.capture_hotkey_btn)
        hotkey_row.addWidget(self.hotkey_scope)
        hotkey_row.addWidget(self.hotkey_apply)
        outer.addLayout(hotkey_row)
        self.hotkey_status=QLabel("Zello-Hotkey: deaktiviert")
        outer.addWidget(self.hotkey_status)
        self._local_hotkey=LocalPttHotkey(self)
        self._global_hotkey=GlobalPttHotkey(self)
        self._local_hotkey.pressed.connect(lambda:self.set_ptt(True))
        self._local_hotkey.released.connect(lambda:self.set_ptt(False))
        self._global_hotkey.pressed.connect(lambda:self.set_ptt(True) if not self._capturing_hotkey else None)
        self._global_hotkey.released.connect(lambda:self.set_ptt(False))
        self._global_hotkey.statusChanged.connect(self.hotkey_status.setText)
        audio_controls=QHBoxLayout()
        self.mic_gain=QSlider(Qt.Orientation.Horizontal)
        self.mic_gain.setRange(0,300)
        self.mic_gain.setValue(100)
        self.mic_gain_value=QLabel("100 %")
        self.mic_gain.valueChanged.connect(lambda n:self.mic_gain_value.setText(f"{n} %"))
        self.rx_volume=QSlider(Qt.Orientation.Horizontal)
        self.rx_volume.setRange(0,200)
        self.rx_volume.setValue(100)
        self.rx_volume_value=QLabel("100 %")
        self.rx_volume.valueChanged.connect(lambda n:self.rx_volume_value.setText(f"{n} %"))
        self.rx_volume.valueChanged.connect(self._set_rx_gain)
        audio_controls.addWidget(QLabel("Mikrofonverstärkung"))
        audio_controls.addWidget(self.mic_gain,1)
        audio_controls.addWidget(self.mic_gain_value)
        audio_controls.addWidget(QLabel("Wiedergabe"))
        audio_controls.addWidget(self.rx_volume,1)
        audio_controls.addWidget(self.rx_volume_value)
        audio_box=QGroupBox("Zello Audio")
        audio_box.setLayout(audio_controls)
        outer.addWidget(audio_box)
        self.mic_gain.sliderReleased.connect(self._save_directory)
        self.rx_volume.sliderReleased.connect(self._save_directory)
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
        help_label = QLabel('Der API-Token wird über developers.zello.com erstellt. '
                            'Der Client verbindet sich mit jeweils einem Kanal. '
                            'Benutzer und Kanäle werden lokal gespeichert; '
                            'Passwort und Token im System-Schlüsselbund.')
        help_label.setWordWrap(True)
        outer.addWidget(help_label)

        # Same compact tab layout concept as the other integrations.
        # Move existing widgets without reconnecting signals or recreating clients.
        tabs=QTabWidget(self)
        self.zello_tabs=tabs
        pages={}
        for title in ("Verbindung","Kanäle","Entdecken","Public Directory","Buddys","Diagnose"):
            page=QWidget()
            layout=QVBoxLayout(page)
            layout.setContentsMargins(8,8,8,8)
            pages[title]=layout
            tabs.addTab(page,title)
        def move_widget(widget, destination):
            outer.removeWidget(widget)
            pages[destination].addWidget(widget)
        move_widget(group,"Verbindung")
        outer.removeItem(buttons)
        pages["Verbindung"].addLayout(buttons)
        move_widget(help_label,"Verbindung")
        move_widget(audio_box,"Verbindung")
        # Compact side-by-side channel controls: target on the left,
        # saved favorites on the right. Preserve existing widget signals.
        channel_columns=QHBoxLayout()
        channel_columns.setSpacing(12)
        outer.removeWidget(target_box)
        outer.removeWidget(channels_box)
        channel_columns.addWidget(target_box,1)
        channel_columns.addWidget(channels_box,1)
        pages["Kanäle"].addLayout(channel_columns)
        # External discovery is explicitly separate from the official Channel API.
        # Only exact names published as text on the cited directory are preloaded.
        discovery=QGroupBox("Öffentliche Kanäle entdecken (externe Verzeichnisse)")
        discovery_layout=QVBoxLayout(discovery)
        discovery_hint=QLabel(
            "Keine weltweite Zello-Kanalsuche: Hier kannst du bekannte Namen "
            "in einer kleinen öffentlichen Verzeichnis-Auswahl filtern. "
            "Für weitere Ergebnisse öffnet sich die externe Websuche. "
            "Eine Verbindung bestätigt erst der Zello-Server.")
        discovery_hint.setWordWrap(True)
        discovery_layout.addWidget(discovery_hint)
        discover_row=QHBoxLayout()
        self.discover_query=QLineEdit()
        self.discover_query.setPlaceholderText("Geladene Kanäle durchsuchen, z. B. Süd, Funk")
        self.discover_query.textChanged.connect(self._search_discovery)
        self.discover_web=QPushButton("Online aktualisieren")
        self.discover_web.clicked.connect(self._fetch_discovery)
        discover_row.addWidget(self.discover_query,1)
        discover_row.addWidget(self.discover_web)
        discovery_layout.addLayout(discover_row)
        self.discover_results=QListWidget()
        self.discover_results.itemDoubleClicked.connect(self._discover_select)
        discovery_layout.addWidget(self.discover_results)
        discover_actions=QHBoxLayout()
        pick_discover=QPushButton("Als Favorit speichern")
        pick_discover.clicked.connect(self._discover_favorite)
        switch_discover=QPushButton("Mit Kanal verbinden")
        switch_discover.clicked.connect(self._discover_connect)
        discover_actions.addWidget(pick_discover)
        discover_actions.addWidget(switch_discover)
        discovery_layout.addLayout(discover_actions)
        self.discover_status=QLabel("80 Kanalnummern; 9 Namen mit geprüften Zusätzen, übrige aus Bildtabellen noch ungeprüft.")
        self.discover_status.setWordWrap(True)
        discovery_layout.addWidget(self.discover_status)
        source_link=QPushButton("Quelle anzeigen (optional)")
        source_link.clicked.connect(lambda:webbrowser.open(
            "https://www.cb-digitalfunk.de/kanal%C3%BCbersicht"))
        discovery_layout.addWidget(source_link)
        pages["Entdecken"].addWidget(discovery)
        # All 80 numbered entries; suffixes beyond the published HTML text
        # require verification against the image tables before connecting.
        suffixes={1:"Rufkanal Deutschland",2:"Ruf-Nord",3:"Ruf-West",
                  4:"Ruf-Ost",5:"Ruf-Süd",9:"Trucker",10:"Trucker",
                  19:"Jugend",20:"Jugend"}
        self._discovery_entries=[
            "Digital Funk Kanal {:02d}{}".format(
                number, " ("+suffixes[number]+")" if number in suffixes else "")
            for number in range(1,81)]
        self._discovery_verified=set(suffixes)
        self._discovery_sources={}
        self._discovery_network=QNetworkAccessManager(self)
        self._discovery_busy=False
        self._discovery_replies=[]
        self._search_discovery()
        QTimer.singleShot(0,self._fetch_discovery)
        public_box=QGroupBox("FunkGateway Community Directory · Zello")
        public_layout=QVBoxLayout(public_box)
        info=QLabel("Offene, von der Community eingereichte Kanäle. "
                    "Nur freigegebene Einträge aus unserem GitHub-Verzeichnis werden angezeigt. "
                    "Keine globale Zello-Suche und keine garantierte Erreichbarkeit.")
        info.setWordWrap(True)
        public_layout.addWidget(info)
        public_row=QHBoxLayout()
        self.public_search=QLineEdit()
        self.public_search.setPlaceholderText("Öffentliche Kanäle durchsuchen")
        self.public_search.textChanged.connect(self._filter_public_directory)
        public_reload=QPushButton("Liste aktualisieren")
        public_reload.clicked.connect(self._load_public_directory)
        public_row.addWidget(self.public_search,1)
        public_row.addWidget(public_reload)
        public_layout.addLayout(public_row)
        self.public_results=QListWidget()
        self.public_results.itemDoubleClicked.connect(self._public_save_favorite)
        public_layout.addWidget(self.public_results)
        public_actions=QHBoxLayout()
        public_fav=QPushButton("Als Favorit speichern")
        public_fav.clicked.connect(self._public_save_favorite)
        public_submit=QPushButton("Kanal öffentlich vorschlagen")
        public_submit.clicked.connect(self._public_submit)
        public_actions.addWidget(public_fav)
        public_actions.addWidget(public_submit)
        public_layout.addLayout(public_actions)
        self.public_description=QLineEdit()
        self.public_description.setMaxLength(160)
        self.public_description.setPlaceholderText("Optionale öffentliche Beschreibung (keine Zugangsdaten)")
        public_layout.addWidget(self.public_description)
        self.public_status=QLabel("Öffentliches Verzeichnis noch nicht geladen.")
        self.public_status.setWordWrap(True)
        public_layout.addWidget(self.public_status)
        self.public_updated=QLabel("Letzte erfolgreiche Aktualisierung: noch keine")
        public_layout.addWidget(self.public_updated)
        pages["Public Directory"].addWidget(public_box)
        self._public_entries=[]
        self._public_states={}
        self._public_network=QNetworkAccessManager(self)
        self._public_busy=False
        self._public_reload_button=public_reload
        QTimer.singleShot(0,self._load_public_directory)
        move_widget(directory,"Buddys")
        for widget in (self.rx_diagnostic,self.rx_detail,self.rx_packets,
                       self.copy_rx_btn,self.tx_diagnostic):
            move_widget(widget,"Diagnose")
        for layout in pages.values():
            layout.addStretch(1)
        outer.insertWidget(outer.indexOf(self.ptt_btn),tabs,1)
        # Connection overview and PTT remain visible independently of the tab.
        # TX troubleshooting details are on the Diagnose tab.
        outer.addStretch(1)

    def to_config(self):
        return {"username":self.username.text().strip(),
                "channel":self.channel.text().strip(),
                "known_speakers":sorted(self._known_speakers),
                "channel_favorites":sorted(self._channel_favorites),
                "ptt_hotkey":self._ptt_hotkey_setting,
                "ptt_hotkey_scope":self._ptt_hotkey_scope,
                "mic_gain":self.mic_gain.value(),
                "rx_volume":self.rx_volume.value()}

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
        self._channel_favorites=set(str(x).strip() for x in data.get("channel_favorites",[])
                                    if isinstance(x,str) and x.strip())
        self._refresh_directories()
        self.hotkey_edit.setText(str(data.get("ptt_hotkey","") or ""))
        idx=self.hotkey_scope.findData(data.get("ptt_hotkey_scope","local"))
        self.hotkey_scope.setCurrentIndex(max(0,idx))
        self._configure_hotkey(save=False)
        self.mic_gain.setValue(max(0,min(300,int(data.get("mic_gain",100)))))
        self.rx_volume.setValue(max(0,min(200,int(data.get("rx_volume",100)))))
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
                self.pttStateChanged.emit(bool(self._tx_wanted))
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
                # Some Zello clients emit contactName (without "from") for
                # contact-directed audio. Treat it as a display label only.
                contact_name=data.get("contactName")
                contact_label=(contact_name.strip() if isinstance(contact_name,str) else "")
                if not sender and contact_label:
                    sender=contact_label
                recipient=data.get("for")
                target=("gezielt/Kontakt" if "contactName" in data
                        else "gezielt" if isinstance(recipient,str) and recipient.strip()
                        else "Kanal")
                present=",".join(k for k in ("from","sender","username","from_user","contactName","for")
                                 if k in data) or "keine"
                self.rx_diagnostic.setText(
                    f"RX-Diagnose: {target} · Absenderfelder: {present} · "
                    +("Sprecher erkannt" if sender else "kein Absender übermittelt"))
                # List field names only; never display the full inbound JSON.
                fields=", ".join(sorted(str(key) for key in data.keys()))
                self._rx_packet_counts[stream_id]=0
                event_details=(
                    f"RX-Details: Ereignis on_stream_start · Stream-ID {stream_id} · "
                    f"Felder: {fields} · Opus {rate} Hz / {frame_ms} ms")
                self._rx_event_details[stream_id]=event_details
                self.rx_detail.setText(event_details)
                self.rx_packets.setText(f"RX-Audio: Stream-ID {stream_id} · Pakete: 0 · Opus {rate} Hz")
                if contact_label and not any(
                        isinstance(data.get(k),str) and data[k].strip()
                        for k in ("from","sender","username","from_user")):
                    self.rx_diagnostic.setText(
                        "RX-Diagnose: Kontaktübertragung · contactName vorhanden "
                        "(Anzeigename, nicht verifizierter Benutzername)")
                elif not sender:
                    self.rx_diagnostic.setText(
                        "RX-Diagnose: Absender nicht vom Server übermittelt "
                        "(Übertragungsart nicht sicher bestimmbar)")
                speaker=sender or "Sprecher nicht übermittelt"
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
                detail=self._rx_event_details.pop(ended,self.rx_detail.text())
                self.rx_detail.setText(detail+" · Stream beendet")
                self.rx_packets.setText(f"RX-Audio: Stream-ID {ended} · beendet · {count} Pakete")
            except (ValueError,TypeError,KeyError):
                pass
            if not self._streams:
                self._set_speaker("")
                self.audio_status.setText("Audioempfang: bereit")

    def _copy_rx_diagnostic(self):
        # Share only diagnostic labels, never credentials or raw server payloads.
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(
            self.rx_diagnostic.text()+"\\n"+self.rx_detail.text()+"\\n"+self.rx_packets.text())

    def _send_command(self, command, **kwargs):
        seq=self._tx_seq
        self._tx_seq+=1
        self._ws.sendTextMessage(json.dumps(dict(command=command,seq=seq,**kwargs)))
        return seq

    def _update_ptt_ui(self):
        active=bool(self._tx_wanted or self._tx_stream_id is not None)
        self.ptt_btn.setText("Zello TX AKTIV" if active else "Zello PTT halten")
        self.ptt_btn.setStyleSheet("background:#E58B22;color:black;font-weight:bold;" if active else "")
        self.pttStateChanged.emit(active)

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
                packet=self._tx_encoder.encode(self._scale_pcm(pcm,self.mic_gain.value()/100),320)
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
                    packet=self._tx_encoder.encode(self._scale_pcm(pcm,self.mic_gain.value()/100),320)
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

    def _start_hotkey_capture(self):
        """Capture keys without a keyboard grab, so the UI cannot be locked."""
        if self._capturing_hotkey:
            self._finish_hotkey_capture(None)
            return
        self._capturing_hotkey=True
        # Keep the existing listener alive during capture. A repeated F9 should
        # not stop/restart pynput or block the Qt event loop.
        self.capture_hotkey_btn.setText("Abbrechen (Esc)")
        self.hotkey_status.setText("Jetzt Taste drücken; Esc bricht ab")
        QApplication.instance().installEventFilter(self)
        self.capture_hotkey_btn.setFocus()

    def eventFilter(self,obj,event):
        if not self._capturing_hotkey:
            return super().eventFilter(obj,event)
        if event.type()!=QEvent.Type.KeyPress:
            return super().eventFilter(obj,event)
        if event.isAutoRepeat():
            return True
        key=event.key()
        if key==Qt.Key.Key_Escape:
            self._finish_hotkey_capture(None)
            return True
        modifiers={Qt.Key.Key_Control:"Ctrl",Qt.Key.Key_Alt:"Alt",
                   Qt.Key.Key_Shift:"Shift",Qt.Key.Key_Meta:"Meta"}
        if key in modifiers:
            name=modifiers[key]
        else:
            name=QKeySequence(event.keyCombination()).toString(
                QKeySequence.SequenceFormat.PortableText)
        if name:
            self._finish_hotkey_capture(name)
        return True

    def _finish_hotkey_capture(self,name):
        if not self._capturing_hotkey:
            return
        self._capturing_hotkey=False
        QApplication.instance().removeEventFilter(self)
        self.capture_hotkey_btn.setText("Taste erfassen")
        if name:
            self.hotkey_edit.setText(name)
        self._configure_hotkey(save=bool(name))

    @staticmethod
    def _scale_pcm(pcm, factor):
        import audioop
        if factor==1.0:
            return pcm
        return audioop.mul(pcm,2,factor)

    def _configure_hotkey(self, *_args, save=True):
        value=self.hotkey_edit.text().strip()
        scope=self.hotkey_scope.currentData() or "local"
        old_value=self._ptt_hotkey_setting
        old_scope=self._ptt_hotkey_scope
        if value==old_value and scope==old_scope and self._hotkey_applied:
            self.hotkey_status.setText("Zello-Hotkey unverändert – bereits aktiv" if value else "Zello-Hotkey: deaktiviert")
            if save:
                self._save_directory()
            return
        self.set_ptt(False)
        self._local_hotkey.set_hotkey("")
        self._global_hotkey.stop()
        self._ptt_hotkey_setting=value
        self._ptt_hotkey_scope=scope
        self._hotkey_applied=True
        if not value:
            self.hotkey_status.setText("Zello-Hotkey: deaktiviert")
        elif scope=="global":
            self._global_hotkey.set_hotkey(value)
            if self._global_hotkey.start():
                self.hotkey_status.setText("Zello-Hotkey: systemweit aktiv")
            else:
                self._local_hotkey.set_hotkey(value)
                self.hotkey_status.setText("Zello-Hotkey: lokal aktiv (global nicht verfügbar)")
        else:
            self._local_hotkey.set_hotkey(value)
            self.hotkey_status.setText("Zello-Hotkey: lokal aktiv")
        if save:
            self._save_directory()

    def stop_ptt_hotkeys(self):
        self._local_hotkey.set_hotkey("")
        self._global_hotkey.stop()

    def _save_directory(self):
        window=self.window()
        if hasattr(window,"save_cfg"):
            window.save_cfg()

    @staticmethod
    def _extract_directory_names(raw):
        """Read only explicitly named channels; never treat search snippets as names."""
        class TextCollector(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.parts=[]
            def handle_data(self,data):
                self.parts.append(data)
        parser=TextCollector()
        parser.feed(raw)
        text=unescape(" ".join(parser.parts))
        text=re.sub(r"\\s+"," ",text)
        found=re.findall(
            r"Digital Funk Kanal\\s+(?:0[1-9]|[1-7][0-9]|80)\\s*"
            r"\\([^)]{2,75}\\)",text,flags=re.IGNORECASE)
        return sorted(set(n.strip() for n in found),key=str.casefold)

    def _fetch_discovery(self,*_args):
        if self._discovery_busy:
            return
        self._discovery_busy=True
        self.discover_web.setEnabled(False)
        self.discover_status.setText("Lade öffentliche Kanalverzeichnisse direkt in FunkGateway …")
        url="https://www.cb-digitalfunk.de/kanal%C3%BCbersicht"
        request=QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent",b"FunkGateway/0.6 ChannelDirectory")
        request.setTransferTimeout(10000)
        reply=self._discovery_network.get(request)
        self._discovery_replies.append(reply)
        reply.finished.connect(lambda reply=reply:self._finish_discovery(reply))

    def _finish_discovery(self,reply):
        self._discovery_busy=False
        self.discover_web.setEnabled(True)
        if reply in self._discovery_replies:
            self._discovery_replies.remove(reply)
        try:
            if reply.error()!=QNetworkReply.NetworkError.NoError:
                raise RuntimeError(reply.errorString())
            raw=bytes(reply.readAll())
            if len(raw)>2_000_000:
                raise ValueError("Verzeichnisantwort zu groß")
            names=self._extract_directory_names(raw.decode("utf-8","replace"))
            if not names:
                raise ValueError("Keine erkennbaren Kanalnamen in der Quelle")
            verified={int(x.group(1)) for name in names if (x:=re.match(r"Digital Funk Kanal (\\d{2})",name))}
            existing={int(x.group(1)):x for name in self._discovery_entries if (x:=re.match(r"Digital Funk Kanal (\\d{2})",name))}
            for name in names:
                match=re.match(r"Digital Funk Kanal (\\d{2})",name)
                if match:
                    existing[int(match.group(1))]=name
            self._discovery_entries=[existing[k] for k in sorted(existing)]
            self._discovery_verified.update(verified)
            self._search_discovery()
            self.discover_status.setText(
                f"{len(names)} textbasierte Kanalnamen abgeglichen; 80 Nummern angezeigt. "
                "Namen sind extern veröffentlicht, Online-Status nicht verifiziert.")
        except Exception as exc:
            self._search_discovery()
            self.discover_status.setText(
                "Verzeichnis momentan nicht erreichbar ("+str(exc)+"). "
                "Die zuletzt geladenen Einträge bleiben sichtbar.")
        finally:
            reply.deleteLater()

    def _search_discovery(self,*_args):
        query=self.discover_query.text().strip().casefold()
        self.discover_results.clear()
        for name in self._discovery_entries:
            if query in name.casefold():
                self.discover_results.addItem(name)

    def _discovery_name(self):
        item=self.discover_results.currentItem()
        if item is None:
            return ""
        name=item.text().strip()
        match=re.match(r"Digital Funk Kanal (\\d{2})",name)
        if match and int(match.group(1)) not in self._discovery_verified:
            self.discover_status.setText(
                "Kanal "+match.group(1)+" ist noch nicht anhand der Bildtabelle "
                "überprüft. Bitte den vollständigen Namen mit allen Zusätzen "
                "der Originalquelle vergleichen.")
            return ""
        return name

    def _discover_select(self,*_args):
        name=self._discovery_name()
        if name:
            self.channel_add.setText(name)
            self.channel.setText(name)
            self.discover_status.setText("Kanal übernommen: "+name+
                " – Favorit speichern oder Verbindung herstellen.")

    def _discover_favorite(self,*_args):
        name=self._discovery_name()
        if name:
            self._channel_favorites.add(name)
            self.channel_add.setText(name)
            self._refresh_directories()
            self._save_directory()
            self.discover_status.setText("Favorit gespeichert: "+name)

    def _discover_connect(self,*_args):
        name=self._discovery_name()
        if not name:
            return
        if self._tx_wanted or self._tx_pending or self._tx_stream_id is not None:
            self.discover_status.setText("Bitte vor dem Kanalwechsel PTT loslassen.")
            return
        if self.connected and self.channel.text().strip()==name:
            self.discover_status.setText("Bereits mit diesem Kanal verbunden.")
            return
        if self._ws.state()!=QAbstractSocket.SocketState.UnconnectedState:
            self._pending_channel_switch=name
            self.disconnect_channel()
        else:
            self.channel.setText(name)
            self.connect_channel()

    def _load_public_directory(self,*_args):
        if self._public_busy:
            return
        self._public_busy=True
        self._public_reload_button.setEnabled(False)
        url=QUrl("https://raw.githubusercontent.com/MysticFire01/Funkgateway/main/community/zello_channels.json")
        # Unique URL on every request avoids stale raw.githubusercontent.com CDN caches.
        from PySide6.QtCore import QUrlQuery
        query=QUrlQuery()
        query.addQueryItem("_fg_refresh",str(QDateTime.currentMSecsSinceEpoch()))
        url.setQuery(query)
        request=QNetworkRequest(url)
        request.setTransferTimeout(12000)
        request.setRawHeader(b"User-Agent",b"FunkGateway-CommunityDirectory")
        request.setRawHeader(b"Cache-Control",b"no-cache, no-store")
        request.setRawHeader(b"Pragma",b"no-cache")
        request.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                             QNetworkRequest.CacheLoadControl.AlwaysNetwork)
        self.public_status.setText("Lade freigegebenes Community-Verzeichnis …")
        reply=self._public_network.get(request)
        reply.finished.connect(lambda reply=reply:self._public_loaded(reply))

    def _public_loaded(self,reply):
        try:
            if reply.error()!=QNetworkReply.NetworkError.NoError:
                raise RuntimeError(reply.errorString())
            raw=bytes(reply.readAll())
            if len(raw)>1024*1024:
                raise ValueError("Verzeichnis zu groß")
            document=json.loads(raw.decode("utf-8"))
            if document.get("version")!=1 or not isinstance(document.get("channels"),list):
                raise ValueError("Unbekanntes Verzeichnisformat")
            cleaned=[]
            seen=set()
            for entry in document["channels"][:1000]:
                if not isinstance(entry,dict) or entry.get("platform")!="zello":
                    continue
                name=entry.get("name")
                if not isinstance(name,str) or not (1<=len(name)<=120):
                    continue
                name=name.strip()
                if not name or name.casefold() in seen:
                    continue
                seen.add(name.casefold())
                cleaned.append({"name":name,"description":str(entry.get("description",""))[:160]})
            self._public_entries=cleaned
            self._public_states={}
            self._filter_public_directory()
            self._load_public_status()
            self.public_updated.setText(
                "Letzte erfolgreiche Aktualisierung: "+
                QDateTime.currentDateTime().toString("dd.MM.yyyy HH:mm:ss"))
            self.public_status.setText(
                f"{len(cleaned)} freigegebene Community-Kanäle geladen. "
                "Status nicht live überprüft.")
        except Exception as exc:
            self.public_status.setText(
                "Community-Verzeichnis derzeit nicht verfügbar: "+str(exc))
        finally:
            self._public_busy=False
            self._public_reload_button.setEnabled(True)
            reply.deleteLater()

    def _load_public_status(self):
        url=QUrl("https://raw.githubusercontent.com/MysticFire01/Funkgateway/main/community/zello_status.json")
        query=QUrlQuery()
        query.addQueryItem("_fg_refresh",str(QDateTime.currentMSecsSinceEpoch()))
        url.setQuery(query)
        request=QNetworkRequest(url)
        request.setTransferTimeout(9000)
        reply=self._public_network.get(request)
        reply.finished.connect(lambda reply=reply:self._public_status_loaded(reply))

    def _public_status_loaded(self,reply):
        try:
            if reply.error()!=QNetworkReply.NetworkError.NoError:
                raise RuntimeError(reply.errorString())
            raw=bytes(reply.readAll())
            if len(raw)>1024*1024:
                raise ValueError("Statusantwort zu groß")
            payload=json.loads(raw.decode("utf-8"))
            if payload.get("version")!=1 or not isinstance(payload.get("channels"),list):
                raise ValueError("Unbekanntes Statusformat")
            result={}
            now=QDateTime.currentDateTimeUtc()
            for entry in payload["channels"][:1000]:
                if not isinstance(entry,dict):
                    continue
                name=entry.get("name")
                stamp=entry.get("checked_at")
                if not isinstance(name,str) or not isinstance(stamp,str):
                    continue
                checked=QDateTime.fromString(stamp,Qt.DateFormat.ISODate)
                if not checked.isValid() or abs(checked.secsTo(now))>24*3600:
                    continue
                state=entry.get("status")
                if state in ("reachable","unverified"):
                    result[name.casefold()]={"status":state,"checked_at":stamp}
            self._public_states=result
            self._filter_public_directory()
        except Exception:
            # No new observation must never be represented as offline.
            pass
        finally:
            reply.deleteLater()

    def _filter_public_directory(self,*_args):
        term=self.public_search.text().strip().casefold()
        self.public_results.clear()
        for entry in self._public_entries:
            if term in (entry["name"]+" "+entry["description"]).casefold():
                observed=self._public_states.get(entry["name"].casefold(), {})
                label=("✓ Geprüft erreichbar" if observed.get("status")=="reachable"
                       else "Nicht bestätigt" if observed.get("status")=="unverified"
                       else "Nicht geprüft")
                item=QListWidgetItem(entry["name"]+
                    (" — "+entry["description"] if entry["description"] else "")+
                    "  ["+label+"]")
                item.setData(Qt.ItemDataRole.UserRole,entry["name"])
                self.public_results.addItem(item)

    def _public_save_favorite(self,*_args):
        item=self.public_results.currentItem()
        if item is None:
            return
        name=item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(name,str) or not name:
            return
        self._channel_favorites.add(name)
        self._refresh_directories()
        self._save_directory()
        self.public_status.setText("Als Favorit gespeichert: "+name)

    def _public_submit(self,*_args):
        item=self.channel_list.currentItem()
        name=item.text().strip() if item else ""
        if not name:
            self.public_status.setText(
                "Bitte zuerst unter Kanäle einen eigenen Favoriten auswählen.")
            return
        if len(name)>120 or "\n" in name or "\r" in name:
            self.public_status.setText("Ungültiger Kanalname.")
            return
        if any(entry["name"].strip().casefold()==name.casefold()
               for entry in self._public_entries):
            self.public_status.setText(
                "Dieser Kanal ist bereits im öffentlichen Verzeichnis vorhanden. "
                "Keine erneute Einreichung nötig.")
            return
        description=self.public_description.text().strip()
        url=("https://funkgateway-directory-api.xanadu97348.workers.dev/submit?"
             +urlencode({"channel":name,"description":description}))
        if webbrowser.open(url):
            self.public_status.setText(
                "Öffentliches Einreichungsformular geöffnet. "
                "Bitte Angaben prüfen und dort selbst absenden. "
                "Eine GitHub-Anmeldung ist nicht erforderlich.")
        else:
            self.public_status.setText(
                "Browser konnte nicht geöffnet werden. "
                "Einreichungsseite: "+url.split("?")[0])

    def _refresh_directories(self, *_args):
        buddy_filter=self.buddy_search.text().strip().casefold()
        channel_filter=self.channel_search.text().strip().casefold()
        self.buddy_list.clear()
        for name in sorted((x for x in self._known_speakers
                            if buddy_filter in x.casefold()),key=str.casefold):
            speaking=bool(self.talker_name and name.casefold()==self.talker_name.casefold())
            item=QListWidgetItem(("🎙 " if speaking else "● ")+name)
            item.setData(Qt.ItemDataRole.UserRole,name)
            self.buddy_list.addItem(item)
        self.channel_list.clear()
        self.channel_list.addItems(sorted((x for x in self._channel_favorites
                                           if channel_filter in x.casefold()),key=str.casefold))

    def _add_buddy(self):
        name=self.buddy_add.text().strip()
        if not name: return
        self._known_speakers.add(name)
        if self.target_user.findText(name)<0:
            self.target_user.addItem(name)
        self.buddy_add.clear()
        self._refresh_directories()
        self._save_directory()

    def _remove_buddy(self):
        item=self.buddy_list.currentItem()
        if item is None: return
        name=item.data(Qt.ItemDataRole.UserRole) or item.text()
        self._known_speakers.discard(name)
        idx=self.target_user.findText(name)
        if idx>=0: self.target_user.removeItem(idx)
        self._refresh_directories()
        self._save_directory()

    def _choose_buddy(self, item=None):
        # QListWidget.itemDoubleClicked passes the clicked item; the button
        # passes a bool. Handle both without relying on selection timing.
        if item is None or isinstance(item,bool):
            item=self.buddy_list.currentItem()
        if item is None:
            return
        name=str(item.data(Qt.ItemDataRole.UserRole) or item.text()).strip()
        if not name:
            return
        self.target_mode.setCurrentIndex(1)
        self.target_user.setCurrentText(name)
        self.zello_tabs.setCurrentIndex(1)
        self.tx_status.setText("Zello-Ziel gewählt: "+name+" (im aktuellen Kanal)")

    def _add_favorite(self):
        name=self.channel_add.text().strip() or self.channel.text().strip()
        if not name: return
        self._channel_favorites.add(name)
        self.channel_add.clear()
        self._refresh_directories()
        self._save_directory()

    def _remove_favorite(self):
        item=self.channel_list.currentItem()
        if item is None: return
        self._channel_favorites.discard(item.text())
        self._refresh_directories()
        self._save_directory()

    def _choose_favorite(self, *_args):
        item=self.channel_list.currentItem()
        if item is None: return
        if self.connected or self._ws.state()!=QAbstractSocket.SocketState.UnconnectedState:
            self._set_status("Für Kanalwechsel zuerst die Verbindung trennen")
            return
        self.channel.setText(item.text())
        self._save_directory()

    def _switch_to_favorite(self, *_args):
        item=self.channel_list.currentItem()
        if item is None:
            return
        destination=item.text().strip()
        if not destination:
            return
        if self._tx_wanted or self._tx_pending or self._tx_stream_id is not None:
            self._set_status("Kanalwechsel erst nach Loslassen der PTT möglich")
            return
        if self.connected and self.channel.text().strip()==destination:
            self._set_status("Bereits mit "+destination+" verbunden")
            return
        if self._ws.state()!=QAbstractSocket.SocketState.UnconnectedState:
            self._pending_channel_switch=destination
            self._set_status("Wechsle zu "+destination+" …")
            self.disconnect_channel()
            return
        self.channel.setText(destination)
        self._save_directory()
        self.connect_channel()

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
        self._refresh_directories()
        window=self.window()
        if hasattr(window,"save_cfg"):
            window.save_cfg()

    def _set_speaker(self,name):
        if self.talker_name==name:
            return
        self.talker_name=name
        self._refresh_directories()
        if name and name not in ("Unbekannt","Sprecher nicht übermittelt") and name not in self._known_speakers:
            self._known_speakers.add(name)
            self.target_user.addItem(name)
            self._refresh_directories()
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
                self.rx_packets.setText(
                    f"RX-Audio: Stream-ID {stream_id} · Pakete: {count} · "
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
                        output.write(self._scale_pcm(pcm,self._rx_gain_factor))
        except Exception as exc:
            self.audioError.emit(str(exc))

    def _set_rx_gain(self,value):
        self._rx_gain_factor=value/100

    def _audio_error(self,message):
        self.audio_status.setText("Audioausgabe: "+message)

    def _start_audio(self):
        if self._audio_thread and self._audio_thread.is_alive():
            return
        self._audio_stop.clear()
        self._rx_gain_factor=self.rx_volume.value()/100
        self._audio_thread=threading.Thread(target=self._audio_worker,daemon=True)
        self._audio_thread.start()
        self._rx_timer.start()

    def _clear_audio(self):
        self._rx_timer.stop()
        self._audio_stop.set()
        self._streams.clear()
        self._rx_packet_counts.clear()
        self._rx_event_details.clear()
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        self._set_speaker("")
        self.rx_diagnostic.setText("RX-Diagnose: noch keine Übertragung")
        self.rx_detail.setText("RX-Details: Noch kein Stream empfangen")
        self.rx_packets.setText("RX-Audio: noch keine Pakete")

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
        destination=self._pending_channel_switch
        self._pending_channel_switch=""
        self._set_status("Getrennt")
        if destination:
            self.channel.setText(destination)
            self._save_directory()
            QTimer.singleShot(0,self.connect_channel)
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
        if self._capturing_hotkey:
            self._capturing_hotkey=False
            QApplication.instance().removeEventFilter(self)
        self.stop_ptt_hotkeys()
        self.disconnect_channel()
        super().closeEvent(event)
