import math
import array
import wave
import signal
import threading
import re
import subprocess
"""Main graphical user interface for FunkGateway.

The UI deliberately uses plain language.  Most radio operators should be able
to configure the gateway without knowing how PipeWire, serial devices or GPIO
work internally.
"""
import json, subprocess, time, shutil, webbrowser, html, hashlib, hmac, secrets, base64, struct
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QGroupBox,QApplication,QCheckBox,QComboBox,QFileDialog,
    QFormLayout,QHBoxLayout,QLabel,QLineEdit,QMainWindow,QMessageBox,QPushButton,
    QProgressBar,QScrollArea,QSpinBox,QTabWidget,QTextEdit,QVBoxLayout,QWidget,
    QDialog,QDialogButtonBox)
from PySide6.QtCore import QTimer, Qt, Qt, QMarginsF
from PySide6.QtGui import QTextDocument, QPageSize, QPageLayout, QPixmap
from PySide6.QtPrintSupport import QPrinter

try:
    import sounddevice as sd
    import soundfile as sf
except Exception:
    sd = sf = None

from .constants import (APP_NAME,VERSION,CFG_FILE, CFG_DIR,LOG_FILE,CW_FILE,DTMF_FILE,
                        ID_RECORDING_FILE,ROGER_FILE,ensure_cfg)
from .ports import discover_serial_ports, friendly_port_name
from .ptt import DryPTT, SerialPTT, CM108PTT, GPIOPTT
from .audio import AudioBridge, RxActivityDetector, list_sinks, make_virtual_sink, make_rx_sink, make_rx_source
from .tones import make_cw, make_dtmf, make_roger_tone
from .helptext import HELP_HTML
from .integrations.teamspeak import TeamSpeakClientQuery, read_default_api_key
from .integrations.mumble import MumbleLocalBackend, MumbleIceBackend, MumbleBridgeBackend
from .updates import fetch_latest_release, choose_asset, is_newer, download_and_prepare


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.resize(900, 680)
        self.ptt=None; self.bridge=None; self.rx_detector=None; self.tx=False; self.tx_since=None
        self.pending_id=False; self.last_id=time.monotonic(); self.last_route_check=0.0
        self.rx_was_active=False; self.rx_ignore_until=0.0
        self.roger_busy=False; self.roger_proc=None; self.roger_pending_token=0
        self.last_roger_time=0.0
        self.outgoing_audio_active=False
        # Sink-input IDs that FunkGateway itself muted while Papagei mode
        # was active. Only these streams are unmuted again when leaving Papagei.
        self.parrot_muted_voip_streams=set()

        # DTMF-Fernsteuerung (0.5.9.x)
        self.dtmf_session_active=False
        self.dtmf_session_muted=False
        self.dtmf_buffer=""
        self.dtmf_session_started=None
        self.dtmf_last_digit=None
        self.dtmf_release_token=0
        self.dtmf_parrot_wait_rx_free=False
        self.dtmf_control_rx_active=False
        self.dtmf_ack_waiting_labels=set()
        self.dtmf_mode_ack_generation=0
        self.dtmf_mode_ack_pending=False

        # Optional DTMF authentication. AUTH applies to the gateway globally
        # for a limited time because classic RF/DTMF has no sender identity.
        self.dtmf_auth_active_until=0.0
        self.dtmf_auth_fail_count=0
        self.dtmf_auth_locked_until=0.0
        self.dtmf_auth_pin_salt=""
        self.dtmf_auth_pin_hash=""
        self.dtmf_auth_expiry_logged=False
        self.dtmf_totp_secret=""
        self.dtmf_totp_last_counter=-1

        # Optional integrations never own the audio/PTT core. If TeamSpeak is
        # unavailable, FunkGateway must continue to work normally.
        self.ts_client=TeamSpeakClientQuery()
        self.ts_commander_wanted=False
        self.ts_commander_state=False
        self.ts_commander_needs_sync=True
        self.ts_last_status=None
        self.ts_last_speakers=None
        self.ts_last_channel=None

        # Mumble uses the local client API for everyday status/speakers. Ice is
        # optional and only used for administrator-controlled server functions.
        self.mumble_local=MumbleLocalBackend()
        self.mumble_ice=MumbleIceBackend()
        self.mumble_bridge=MumbleBridgeBackend()
        self.mumble_last_poll=0.0
        self.mumble_last_status=None
        self.mumble_channels=[]
        self.protection_previous_mumble_channel=None
        self.protection_mumble_auto_move_active=False
        self.mumble_disturbance_rooms={}

        # Protection / operating-state module.  It is independent from any
        # specific VoIP integration; TeamSpeak can optionally add room-based
        # protection and automatic moves.
        self.protection_muted=False
        self.protection_reason=""
        self.rx_active_since=None
        self.protection_unmute_due=None
        self.protection_waiting_for_rx_free=False
        self.protection_rx_free_since=None
        self.rx_last_db=-120.0
        self.protection_previous_ts_channel=None
        self.protection_auto_move_active=False
        self.protection_last_room_announcement=0.0
        self.protection_last_ts_check=0.0
        self.protection_ts_rooms={}
        self.protection_last_ts_server_key=None
        self.protection_announcement_busy=False
        self.protection_announcement_queue=[]
        self.protection_announcement_proc=None
        self.mumble_room_guard_until=0.0
        self.mumble_muted_sink_inputs=[]
        self.venv_repair_process=None
        self.venv_repair_log_handle=None
        self.venv_repair_log_path=None
        self.venv_repair_message=None
        self.voip_hf_last_block_log=0.0
        self.voip_hf_last_decision=""

        # Selbstrücklauf-Schutz.
        self.tx_source_hint=None
        self.active_tx_kind=None
        self.return_guard_until=0.0
        self.return_guard_candidate=False
        self.return_guard_rx_started=None
        self.return_guard_tx_ended=None
        self.return_events=[]
        self.return_guard_muted=False
        self.lost_passage_pending=False

        # Rufzeichenbake: Es kann immer nur genau eine fällige Bake geben.
        self.id_in_progress=False
        self.id_proc=None
        self.id_channel_free_since=None

        # Updatezustand.
        self.latest_release=None
        self.latest_release_asset=None

        # Papagei-/Echotest-Modus.
        self.parrot_recording=False
        self.parrot_playing=False
        self.parrot_rx_started=None
        self.parrot_proc=None
        self.parrot_pending_beacon=False
        self.parrot_beacon_in_progress=False
        self.parrot_beacon_proc=None
        self.parrot_beacon_free_since=None
        self.parrot_last_beacon=time.monotonic()
        self.parrot_temp_file=CFG_DIR / "papagei-temp.wav"
        self.parrot_raw_file=CFG_DIR / "papagei-temp.raw"
        self.parrot_raw_handle=None

        # Kontinuierliche RX-Aufnahme für den Papagei-Vorlaufpuffer.
        # 48 kHz, 16 Bit, Mono = 96.000 Byte/s.
        self.parrot_capture_proc=None
        self.parrot_capture_thread=None
        self.parrot_capture_stop=threading.Event()
        self.parrot_capture_lock=threading.Lock()
        self.parrot_prebuffer=bytearray()
        self.parrot_capture_source=None
        self.parrot_capture_max_bytes=480000  # maximal 5 s
        self.parrot_cycle_active=False
        self.parrot_capture_fault_logged=False

        # RX, das innerhalb des Selbstrücklauf-Schutzfensters beginnt, wird
        # zunächst gepuffert. Wird es lang genug für einen echten Durchgang,
        # kann es ohne Verlust des Anfangs zum Papagei-Durchgang hochgestuft werden.
        self.parrot_guard_buffering=False
        self.parrot_guard_prebuffer_bytes=0

        # Hauptsteuerung bleibt unabhängig vom gewählten Reiter immer sichtbar.
        # Dadurch sind Start/Stop/NOT-AUS/Rufzeichen auch bei kleinen Fenstern
        # oder sehr langen Einstellungsseiten sofort erreichbar.
        central=QWidget()
        central_layout=QVBoxLayout(central)
        central_layout.setContentsMargins(6,6,6,6)
        central_layout.setSpacing(6)

        controls=QWidget()
        controls_layout=QHBoxLayout(controls)
        controls_layout.setContentsMargins(0,0,0,0)
        controls_layout.setSpacing(6)

        self.start_main_btn=self.big("Gateway starten")
        self.start_main_btn.clicked.connect(self.start_gateway)
        self.stop_main_btn=self.big("Gateway stoppen")
        self.stop_main_btn.clicked.connect(self.stop_gateway)
        self.emergency_main_btn=self.big("NOT-AUS / PTT AUS")
        self.emergency_main_btn.clicked.connect(self.emergency)
        self.emergency_main_btn.setStyleSheet("font-weight: bold;")
        self.ident_main_btn=self.big("Rufzeichen jetzt senden")
        self.ident_main_btn.clicked.connect(self.send_id)

        for b in (self.start_main_btn,self.stop_main_btn,self.emergency_main_btn,self.ident_main_btn):
            b.setMinimumHeight(48)
            controls_layout.addWidget(b)

        self.start_main_btn.setToolTip("Gateway starten. Diese Hauptsteuerung bleibt in jedem Reiter sichtbar.")
        self.stop_main_btn.setToolTip("Gateway stoppen. Diese Hauptsteuerung bleibt in jedem Reiter sichtbar.")
        self.emergency_main_btn.setToolTip("Sofort PTT ausschalten. Der NOT-AUS bleibt in jedem Reiter sichtbar.")
        self.ident_main_btn.setToolTip("Rufzeichen/ID sofort senden. Diese Hauptsteuerung bleibt in jedem Reiter sichtbar.")

        central_layout.addWidget(controls,0)
        self.tabs=QTabWidget()
        central_layout.addWidget(self.tabs,1)
        self.setCentralWidget(central)

        self.build_start(); self.build_audio(); self.build_ptt(); self.build_cos(); self.build_roger()
        self.build_ids(); self.build_tools(); self.build_integrations(); self.build_dtmf(); self.build_protection(); self.build_updates(); self.build_log(); self.build_help()
        self._make_all_tab_pages_scrollable()

        self.load_cfg()
        if hasattr(self,"ts_api_key") and not self.ts_api_key.text().strip():
            key=read_default_api_key()
            if key:
                self.ts_api_key.setText(key)
        self.refresh_ports()
        self.refresh_audio_devices()
        self.ensure_gateway_sink()
        try:
            make_rx_source()
            self.log("FunkGateway_RX_Input ist als virtuelle Aufnahmequelle bereit.")
        except Exception as e:
            self.log(f"FunkGateway_RX_Input konnte nicht angelegt werden: {e}")
        self.refresh_audio_streams()
        self.log(f"FunkGateway {VERSION} gestartet.")

        self.tick_timer=QTimer(self); self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(250)
        self.integration_timer=QTimer(self); self.integration_timer.timeout.connect(self.poll_integrations)
        self.integration_timer.start(750)
        if hasattr(self,"update_check_start") and self.update_check_start.isChecked():
            QTimer.singleShot(2500,lambda:self.check_for_updates(quiet=True))

    def big(self,text):
        b=QPushButton(text); b.setMinimumHeight(56); return b

    def _make_all_tab_pages_scrollable(self):
        """Make every settings tab vertically scrollable without hiding main controls."""
        tabs=[self.tabs] + [t for t in self.findChildren(QTabWidget) if t is not self.tabs]
        # Deep/nested tabs first, then the main tab widget.
        for tab in reversed(tabs):
            current=tab.currentIndex()
            for i in range(tab.count()):
                page=tab.widget(i)
                if isinstance(page,QScrollArea):
                    continue
                title=tab.tabText(i)
                icon=tab.tabIcon(i)
                tip=tab.tabToolTip(i)
                enabled=tab.isTabEnabled(i)
                tab.removeTab(i)
                scroll=QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                scroll.setWidget(page)
                tab.insertTab(i,scroll,icon,title)
                tab.setTabEnabled(i,enabled)
                tab.setTabToolTip(i,tip)
            if current >= 0 and current < tab.count():
                tab.setCurrentIndex(current)

    def build_start(self):
        w=QWidget(); v=QVBoxLayout(w)
        title=QLabel(f"<h1>FunkGateway {VERSION}</h1><p>Linux Radio Gateway – Open Source</p>")
        v.addWidget(title)
        self.funk_rx_big=QLabel("FUNK KANAL FREI")
        self.funk_rx_big.setAlignment(Qt.AlignCenter)
        self.funk_rx_big.setMinimumHeight(74)
        self.funk_rx_big.setStyleSheet("font-size: 28px; font-weight: bold; padding: 12px; border: 2px solid #555; border-radius: 8px;")
        self.gateway_state_big=QLabel("GATEWAY AKTIV")
        self.gateway_state_big.setAlignment(Qt.AlignCenter)
        self.gateway_state_big.setMinimumHeight(54)
        self.gateway_state_big.setStyleSheet("font-size: 22px; font-weight: bold; padding: 8px; border: 2px solid #555; border-radius: 8px;")
        self.tx_lbl=QLabel("● PTT AUS"); self.cos_lbl=QLabel("● KANAL FREI")
        self.meter=QProgressBar(); self.meter.setRange(0,100); self.meter.setFormat("Audio %p %")
        v.addWidget(self.funk_rx_big); v.addWidget(self.gateway_state_big); v.addWidget(self.tx_lbl); v.addWidget(self.cos_lbl); v.addWidget(self.meter)
        controls_note=QLabel("Die Hauptsteuerung mit Start, Stop, NOT-AUS und Rufzeichen bleibt jetzt fest oben sichtbar – unabhängig vom gewählten Reiter.")
        controls_note.setWordWrap(True)
        controls_note.setStyleSheet("font-weight: bold; padding: 6px;")
        v.addWidget(controls_note)
        v.addStretch(1)
        self.tabs.addTab(w,"Start")

    def build_audio(self):
        """Build the audio/routing page.

        The important distinction for users is:
        - "Ausgang zum Funkgerät" = real sound output connected to the radio.
        - "FunkGateway_TX" = virtual input used by TeamSpeak/Mumble/FRN.
        """
        w=QWidget(); f=QFormLayout(w)

        self.target_sink=QComboBox()
        self.input_device=QComboBox()

        self.threshold=QSpinBox()
        self.threshold.setRange(-80,-5)
        self.threshold.setValue(-42)
        self.threshold.setSuffix(" dB")

        self.hang=QSpinBox()
        self.hang.setRange(0,5000)
        self.hang.setValue(550)
        self.hang.setSuffix(" ms")

        self.tx_gain=QSpinBox()
        self.tx_gain.setRange(-12,24)
        self.tx_gain.setValue(0)
        self.tx_gain.setSuffix(" dB")
        self.tx_gain.setToolTip(
            "Frei einstellbare Verstärkung nur für Computer/TeamSpeak → Funk. "
            "Die VOX/PTT-Schwelle bleibt unverändert."
        )
        self.tx_db_label=QLabel("TX Eingang: -- dBFS")
        self.tx_clip_label=QLabel("TX Clipping: 0 %")

        refresh=QPushButton("Audiogeräte neu suchen")
        refresh.clicked.connect(self.refresh_audio_devices)

        create=QPushButton("FunkGateway_TX erzeugen")
        create.clicked.connect(self.create_sink)

        self.stream_combo=QComboBox()
        self.stream_combo.currentIndexChanged.connect(self._update_stream_status)

        streams_refresh=QPushButton("Audioprogramme neu suchen")
        streams_refresh.clicked.connect(self.refresh_audio_streams)

        route_btn=QPushButton("Ausgewähltes Programm zu FunkGateway_TX routen")
        route_btn.clicked.connect(self.route_selected_stream)

        self.auto_route=QCheckBox(
            "TeamSpeak / Mumble / FRN automatisch auf FunkGateway_TX halten"
        )
        self.auto_route.setChecked(True)

        self.stream_status=QLabel(
            "Noch kein Audioprogramm geprüft."
        )
        self.stream_status.setWordWrap(True)

        f.addRow("Ausgang zum Funkgerät:",self.target_sink)
        f.addRow("Mikrofon für Rufzeichenaufnahme:",self.input_device)
        f.addRow("Audio-Schaltschwelle:",self.threshold)
        f.addRow("PTT-Nachhaltezeit:",self.hang)
        f.addRow("TX-Verstärkung Richtung Funk:",self.tx_gain)
        f.addRow("",self.tx_db_label)
        f.addRow("",self.tx_clip_label)
        f.addRow(refresh)
        f.addRow(create)

        f.addRow("Laufendes Audioprogramm:",self.stream_combo)
        f.addRow(streams_refresh)
        f.addRow(route_btn)
        f.addRow(self.auto_route)
        f.addRow("",self.stream_status)

        self.tabs.addTab(w,"Audio-Automatik")

    def build_ptt(self):
        w=QWidget(); f=QFormLayout(w)
        self.ptt_method=QComboBox(); self.ptt_method.addItems(["Testmodus","Serieller COM-Port","CM108/CM119 GPIO","Linux GPIO"])
        self.com_port=QComboBox(); self.com_port.setEditable(True)
        self.usb_serial_hint=QLabel("")
        self.usb_serial_hint.setWordWrap(True)
        self.usb_serial_hint.setStyleSheet("color: #666; font-size: 11px;")
        self.com_line=QComboBox(); self.com_line.addItems(["RTS","DTR"])
        ports=QPushButton("Ports neu suchen"); ports.clicked.connect(self.refresh_ports)
        self.cm_dev=QLineEdit("/dev/hidraw0"); self.gpio_chip=QLineEdit("/dev/gpiochip0")
        self.gpio_line=QSpinBox(); self.gpio_line.setRange(0,255); self.gpio_line.setValue(3)
        self.invert=QCheckBox("PTT invertieren")
        self.lead=QSpinBox(); self.lead.setRange(0,3000); self.lead.setValue(250); self.lead.setSuffix(" ms")
        self.tot=QSpinBox(); self.tot.setRange(10,3600); self.tot.setValue(180); self.tot.setSuffix(" s")
        test=QPushButton("PTT testen"); test.clicked.connect(self.test_ptt)
        f.addRow("PTT-Verfahren:",self.ptt_method); f.addRow("COM-/USB-Port:",self.com_port); f.addRow(ports)
        f.addRow("",self.usb_serial_hint)
        f.addRow("Steuerleitung:",self.com_line); f.addRow("CM108 Gerät:",self.cm_dev)
        f.addRow("GPIO-Chip:",self.gpio_chip); f.addRow("GPIO-Leitung:",self.gpio_line)
        f.addRow(self.invert); f.addRow("PTT Vorlauf:",self.lead); f.addRow("TOT / max. Sendezeit:",self.tot); f.addRow(test)
        self.tabs.addTab(w,"PTT / Modem")

    def build_cos(self):
        w=QWidget(); f=QFormLayout(w)
        self.cos_manual=QCheckBox("Kanal manuell als belegt markieren")
        self.cos_manual.toggled.connect(self.update_cos_label)
        note=QLabel("Hardware-COS ist für eine kommende Version vorgesehen.\nDiese Option dient bereits zum Testen der Rufzeichen-Wartelogik.")
        f.addRow(self.cos_manual); f.addRow(note); self.tabs.addTab(w,"COS / Kanal")

    def build_roger(self):
        w=QWidget(); f=QFormLayout(w)
        self.rx_source=QComboBox()
        self.rx_meter=QProgressBar(); self.rx_meter.setRange(0,100); self.rx_meter.setFormat("Funk RX %p %")
        self.rx_status=QLabel("● FUNK RX FREI")

        self.rx_threshold=QSpinBox(); self.rx_threshold.setRange(-80,-5); self.rx_threshold.setValue(-45); self.rx_threshold.setSuffix(" dB")
        self.rx_hang=QSpinBox(); self.rx_hang.setRange(100,5000); self.rx_hang.setValue(550); self.rx_hang.setSuffix(" ms")

        self.rx_gain=QSpinBox()
        self.rx_gain.setRange(-24,18)
        self.rx_gain.setValue(0)
        self.rx_gain.setSuffix(" dB")
        self.rx_gain.setToolTip(
            "Frei einstellbarer Pegel Funk → Computer. Die RX-Erkennung arbeitet "
            "weiterhin mit dem unverstärkten Eingangssignal."
        )
        self.rx_db_label=QLabel("RX Pegel: -- dBFS")
        self.rx_hysteresis=QSpinBox(); self.rx_hysteresis.setRange(0,20); self.rx_hysteresis.setValue(3); self.rx_hysteresis.setSuffix(" dB")
        self.rx_min_signal=QSpinBox(); self.rx_min_signal.setRange(0,3000); self.rx_min_signal.setValue(200); self.rx_min_signal.setSuffix(" ms")
        self.rx_ignore_after_roger=QSpinBox(); self.rx_ignore_after_roger.setRange(0,10000); self.rx_ignore_after_roger.setValue(3000); self.rx_ignore_after_roger.setSuffix(" ms")
        self.roger_min_free=QSpinBox(); self.roger_min_free.setRange(0,5000); self.roger_min_free.setValue(300); self.roger_min_free.setSuffix(" ms")
        self.roger_cooldown=QSpinBox(); self.roger_cooldown.setRange(0,30000); self.roger_cooldown.setValue(5000); self.roger_cooldown.setSuffix(" ms")
        self.diagnostic_mode=QCheckBox("Diagnoseprotokoll für RX/Rogerbeep")

        self.roger_type=QComboBox(); self.roger_type.addItems([
            "Aus", "CW K (-.-)", "Kurzer Einzelton", "Doppelton", "Eigene WAV-Datei"
        ])
        self.roger_delay=QSpinBox(); self.roger_delay.setRange(0,3000); self.roger_delay.setValue(250); self.roger_delay.setSuffix(" ms")
        self.roger_freq=QSpinBox(); self.roger_freq.setRange(300,2000); self.roger_freq.setValue(800); self.roger_freq.setSuffix(" Hz")
        self.roger_wpm=QSpinBox(); self.roger_wpm.setRange(5,40); self.roger_wpm.setValue(20); self.roger_wpm.setSuffix(" WPM")
        self.roger_volume=QSpinBox(); self.roger_volume.setRange(1,100); self.roger_volume.setValue(70); self.roger_volume.setSuffix(" %")
        self.roger_wav=QLineEdit(); choose=QPushButton("WAV auswählen"); choose.clicked.connect(self.choose_roger_wav)
        row=QHBoxLayout(); row.addWidget(self.roger_wav); row.addWidget(choose)
        test=QPushButton("Rogerbeep über Funk testen"); test.clicked.connect(self.test_roger_beep)

        note=QLabel(
            "Der Rogerbeep wird nach dem Ende eines empfangenen HF-Durchgangs direkt "
            "über den Funkgeräte-Ausgang gesendet. Er wird nicht in TeamSpeak/Computer eingespeist."
        ); note.setWordWrap(True)

        f.addRow("Funk-Empfangsquelle:",self.rx_source)
        f.addRow(self.rx_status); f.addRow(self.rx_meter)
        f.addRow("RX-Erkennungsschwelle (EIN):",self.rx_threshold)
        f.addRow("RX-Hysterese:",self.rx_hysteresis)
        f.addRow("Mindestdauer gültiges RX-Signal:",self.rx_min_signal)
        f.addRow("RX-Nachhaltezeit:",self.rx_hang)
        f.addRow("RX-Verstärkung Richtung Computer:",self.rx_gain)
        f.addRow("",self.rx_db_label)
        rx_note=QLabel(
            "FunkGateway erzeugt automatisch die normale Aufnahmequelle FunkGateway_RX_Input. "
            "Diese Quelle in TeamSpeak/Mumble/FRN als Mikrofon auswählen."
        )
        rx_note.setWordWrap(True)
        f.addRow("",rx_note)
        f.addRow("Rogerbeep:",self.roger_type)
        f.addRow("Mindest-Frei-Zeit vor Beep:",self.roger_min_free)
        f.addRow("Zusätzliche Verzögerung nach RX-Ende:",self.roger_delay)
        f.addRow("RX-Sperrzeit nach Rogerbeep:",self.rx_ignore_after_roger)
        f.addRow("Rogerbeep-Cooldown:",self.roger_cooldown)
        f.addRow(self.diagnostic_mode)
        f.addRow("Tonfrequenz:",self.roger_freq)
        f.addRow("CW-Geschwindigkeit:",self.roger_wpm)
        f.addRow("Rogerbeep-Lautstärke:",self.roger_volume)
        f.addRow("Eigene WAV:",row)
        f.addRow(test); f.addRow(note)
        self.tabs.addTab(w,"RX / Rogerbeep")

    def build_ids(self):
        w=QWidget(); f=QFormLayout(w)
        self.id_file=QLineEdit(); choose=QPushButton("WAV auswählen"); choose.clicked.connect(self.choose_id)
        row=QHBoxLayout(); row.addWidget(self.id_file); row.addWidget(choose)
        self.id_interval=QSpinBox(); self.id_interval.setRange(1,1440); self.id_interval.setValue(10); self.id_interval.setSuffix(" min")
        self.id_record_seconds=QSpinBox(); self.id_record_seconds.setRange(1,300); self.id_record_seconds.setValue(8); self.id_record_seconds.setSuffix(" s")
        rec=QPushButton("Rufzeichenansage aufnehmen"); rec.clicked.connect(self.record_id)
        prev=QPushButton("Rufzeichenansage anhören"); prev.clicked.connect(self.preview_id)
        self.id_auto=QCheckBox("Automatische Rufzeichenausgabe aktiv"); self.id_auto.setChecked(True)
        self.id_wait_free=QCheckBox("Bei belegtem Kanal warten"); self.id_wait_free.setChecked(True)
        self.id_free_wait_ms=QSpinBox(); self.id_free_wait_ms.setRange(0,30000); self.id_free_wait_ms.setValue(1500); self.id_free_wait_ms.setSuffix(" ms")
        self.id_free_wait_ms.setToolTip("So lange muss der Funk-/VoIP-Weg frei bleiben, bevor eine fällige Bake startet. Standard: 1500 ms.")
        safe_note=QLabel(
            "Eine fällige Bake wird nur einmal vorgemerkt. Sie wartet auf freien Funk-RX, "
            "freien VoIP/TX-Weg und das Ende interner Aussendungen. Erst nach dem tatsächlichen "
            "Ende der Bake beginnt das eingestellte Intervall erneut."
        ); safe_note.setWordWrap(True)
        f.addRow("Ansage:",row); f.addRow("Intervall:",self.id_interval); f.addRow("Aufnahmedauer:",self.id_record_seconds)
        f.addRow(rec); f.addRow(prev); f.addRow(self.id_auto); f.addRow(self.id_wait_free)
        f.addRow("Freiwartezeit vor Bake:",self.id_free_wait_ms)
        f.addRow("",safe_note)
        self.tabs.addTab(w,"Rufzeichen")

    def build_tools(self):
        w=QWidget(); f=QFormLayout(w)
        self.cw_text=QLineEdit(); self.cw_wpm=QSpinBox(); self.cw_wpm.setRange(5,40); self.cw_wpm.setValue(18)
        self.cw_freq=QSpinBox(); self.cw_freq.setRange(300,2000); self.cw_freq.setValue(700); self.cw_freq.setSuffix(" Hz")
        cwb=QPushButton("CW senden"); cwb.clicked.connect(self.send_cw)
        self.dtmf_text=QLineEdit(); dtb=QPushButton("DTMF senden"); dtb.clicked.connect(self.send_dtmf)
        f.addRow("CW Text:",self.cw_text); f.addRow("CW WPM:",self.cw_wpm); f.addRow("CW Ton:",self.cw_freq); f.addRow(cwb)
        f.addRow("DTMF:",self.dtmf_text); f.addRow(dtb); self.tabs.addTab(w,"CW / DTMF")

        # Papagei / Echotest
        parrot_box=QWidget()
        pf=QFormLayout(parrot_box)
        self.parrot_enabled=QCheckBox("Papagei aktiv")
        self.parrot_max_seconds=QSpinBox(); self.parrot_max_seconds.setRange(1,180); self.parrot_max_seconds.setValue(30); self.parrot_max_seconds.setSuffix(" s")
        self.parrot_rx_prebuffer_ms=QSpinBox(); self.parrot_rx_prebuffer_ms.setRange(0,5000); self.parrot_rx_prebuffer_ms.setValue(1500); self.parrot_rx_prebuffer_ms.setSuffix(" ms")
        self.parrot_delay_ms=QSpinBox(); self.parrot_delay_ms.setRange(0,10000); self.parrot_delay_ms.setValue(1000); self.parrot_delay_ms.setSuffix(" ms")
        self.parrot_lead_ms=QSpinBox(); self.parrot_lead_ms.setRange(0,10000); self.parrot_lead_ms.setValue(1200); self.parrot_lead_ms.setSuffix(" ms")
        self.parrot_mute_voip=QCheckBox("VoIP während Papageibetrieb stummschalten"); self.parrot_mute_voip.setChecked(True)
        self.parrot_enabled.toggled.connect(lambda _=False:self._refresh_rx_forward_mute())
        self.parrot_enabled.toggled.connect(self._parrot_mode_toggled)
        self.parrot_mute_voip.toggled.connect(lambda _=False:self._refresh_rx_forward_mute())
        self.parrot_mute_voip.toggled.connect(lambda _=False:self._sync_parrot_voip_playback_mute())
        self.parrot_mute_voip.toggled.connect(lambda _=False:self._set_tx_forward_muted(False))
        self.parrot_return_guard=QCheckBox("Rücklaufschutz nach Papagei-Wiedergabe verwenden"); self.parrot_return_guard.setChecked(True)
        self.parrot_roger=QCheckBox("Rogerbeep nach Papagei-Wiedergabe senden"); self.parrot_roger.setChecked(False)

        self.parrot_beacon_enabled=QCheckBox("Papageibake aktiv"); self.parrot_beacon_enabled.setChecked(True)
        self.parrot_beacon_file=QLineEdit()
        pbrowse=QPushButton("WAV auswählen")
        pbrowse.clicked.connect(lambda:self.choose_protection_wav(self.parrot_beacon_file))
        prow=QHBoxLayout(); prow.addWidget(self.parrot_beacon_file); prow.addWidget(pbrowse)
        self.parrot_beacon_interval=QSpinBox(); self.parrot_beacon_interval.setRange(1,120); self.parrot_beacon_interval.setValue(10); self.parrot_beacon_interval.setSuffix(" min")
        self.parrot_beacon_free_wait_ms=QSpinBox(); self.parrot_beacon_free_wait_ms.setRange(0,30000); self.parrot_beacon_free_wait_ms.setValue(1500); self.parrot_beacon_free_wait_ms.setSuffix(" ms")
        self.parrot_beacon_lead_ms=QSpinBox(); self.parrot_beacon_lead_ms.setRange(0,10000); self.parrot_beacon_lead_ms.setValue(1200); self.parrot_beacon_lead_ms.setSuffix(" ms")
        self.parrot_beacon_tail_ms=QSpinBox(); self.parrot_beacon_tail_ms.setRange(0,5000); self.parrot_beacon_tail_ms.setValue(800); self.parrot_beacon_tail_ms.setSuffix(" ms")

        for widget,tip in {
            self.parrot_max_seconds:"Maximale Dauer eines aufgenommenen Funkdurchgangs. Standard: 30 Sekunden.",
            self.parrot_rx_prebuffer_ms:"Audio vor der eigentlichen RX-Erkennung, das an den Anfang der Papagei-Aufnahme gesetzt wird. Standard: 1500 ms.",
            self.parrot_delay_ms:"Wartezeit nach erkanntem Funkende bis zur Rücksendung. Standard: 1000 ms.",
            self.parrot_lead_ms:"Zeit zwischen PTT EIN und Start der Papagei-Wiedergabe. Damit wird der Anfang nicht verschluckt. Standard: 1200 ms.",
            self.parrot_beacon_interval:"Intervall der Papageibake. Der Timer startet erst nach tatsächlichem Ende der Bake neu. Standard: 10 Minuten.",
            self.parrot_beacon_free_wait_ms:"So lange muss der Kanal frei sein, bevor die Papageibake gesendet wird. Standard: 1500 ms.",
            self.parrot_beacon_lead_ms:"Zeit zwischen PTT EIN und Start der Papageibaken-WAV. Standard: 1200 ms.",
            self.parrot_beacon_tail_ms:"Zusätzliche Zeit nach Ende der Papageibaken-WAV, bevor PTT ausgeschaltet wird. Verhindert abgeschnittene Audio-Enden. Standard: 800 ms."
        }.items():
            widget.setToolTip(tip)

        pnote=QLabel(
            "Im Papageibetrieb wird die normale Rufzeichenbake pausiert. Funk-RX wird aufgenommen "
            "und nach erkanntem Funkende automatisch zurückgesendet. Ist „VoIP während Papageibetrieb "
            "stummschalten“ aktiv, werden bekannte TeamSpeak-/Mumble-/FRN-/Zello-/Discord-Wiedergabestreams "
            "auf FunkGateway_TX tatsächlich stummgeschaltet. Zusätzlich wird im Papageibetrieb der "
            "gesamte gemischte FunkGateway_TX-Monitor zum Funkgerät gesperrt. Papagei-, Bake- und "
            "Vollzugsmeldungs-WAVs laufen dabei direkt zum Funkgeräte-Ausgang. Dadurch kann laufendes "
            "TeamSpeak-/Mumble-Audio nicht mehr in eine Papagei-Aussendung hineingemischt werden."
        ); pnote.setWordWrap(True)

        pf.addRow("",self.parrot_enabled)
        pf.addRow("Maximale Aufnahmedauer:",self.parrot_max_seconds)
        pf.addRow("RX-Vorlaufpuffer:",self.parrot_rx_prebuffer_ms)
        pf.addRow("Wartezeit nach Funkende:",self.parrot_delay_ms)
        pf.addRow("PTT-Vorlauf vor Wiedergabe:",self.parrot_lead_ms)
        pf.addRow("",self.parrot_mute_voip)
        pf.addRow("",self.parrot_return_guard)
        pf.addRow("",self.parrot_roger)
        pf.addRow(QLabel("<b>Papageibake</b>"))
        pf.addRow("",self.parrot_beacon_enabled)
        pf.addRow("Papageibake WAV:",prow)
        pf.addRow("Papageibake Intervall:",self.parrot_beacon_interval)
        pf.addRow("Freiwartezeit:",self.parrot_beacon_free_wait_ms)
        pf.addRow("PTT-Vorlauf Papageibake:",self.parrot_beacon_lead_ms)
        pf.addRow("PTT-Nachlauf Papageibake:",self.parrot_beacon_tail_ms)
        pf.addRow("",pnote)
        self.tabs.addTab(parrot_box,"Papagei")

    def build_integrations(self):
        """Build optional VoIP integrations in tidy sub-tabs.

        The main navigation stays compact even when more integrations are added.
        Each integration gets its own page, while the Overview page keeps only
        the important on/off switches and a short explanation.
        """
        w=QWidget(); v=QVBoxLayout(w)
        integration_tabs=QTabWidget()
        v.addWidget(integration_tabs)

        # --- Übersicht -----------------------------------------------------
        overview=QWidget(); of=QFormLayout(overview)
        self.ts_enabled=QCheckBox("TeamSpeak-Modul aktiv")
        self.ts_enabled.setToolTip(
            "Schaltet nur die zusätzlichen TeamSpeak-Funktionen ein. "
            "Der normale FunkGateway-Betrieb funktioniert auch ohne dieses Modul."
        )
        self.mumble_enabled=QCheckBox("Mumble-Modul aktiv")
        self.mumble_enabled.setToolTip(
            "Aktiviert die lokale Mumble-Erkennung und Sprecheranzeige. "
            "Ice ist dafür nicht erforderlich."
        )
        self.voip_hf_voice_filter=QCheckBox("Nur bestätigte VoIP-Sprache auf HF senden")
        self.voip_hf_voice_filter.setChecked(True)
        self.voip_hf_voice_filter.setToolTip(
            "Empfohlen: Wenn am FunkGateway_TX ausschließlich TeamSpeak/Mumble hängen, "
            "wird PTT nur bei einem tatsächlich gemeldeten Sprecher freigegeben. "
            "Lokale Hinweis-, Channel- und Systemtöne lösen dann keine HF-Aussendung aus."
        )
        mumble_hint=QLabel(
            "Mumble arbeitet lokal ohne Server-Adminrechte. Erweiterte Serversteuerung "
            "(Channel-Liste/Störungsraum) kann optional über Ice aktiviert werden."
        )
        mumble_hint.setWordWrap(True)
        general_hint=QLabel(
            "Integrationen sind Zusatzmodule. Sie dürfen Audio, PTT, RX/TX und die "
            "Schutzfunktionen des FunkGateways nicht blockieren. Mehrere Module "
            "können später gleichzeitig aktiv sein."
        )
        general_hint.setWordWrap(True)
        of.addRow(self.ts_enabled)
        of.addRow(self.mumble_enabled)
        of.addRow(self.voip_hf_voice_filter)
        filter_hint=QLabel(
            "Der HF-Sprachfilter prüft bei beginnendem TX-Audio live, ob TeamSpeak oder "
            "Mumble tatsächlich einen Sprecher meldet. Reine Client-/Hinweistöne werden "
            "nicht ausgesendet. Andere Programme bleiben unbeeinflusst, sobald am "
            "FunkGateway_TX ein Nicht-VoIP-Stream erkannt wird."
        )
        filter_hint.setWordWrap(True)
        of.addRow("",filter_hint)
        of.addRow("Mumble:",mumble_hint)
        of.addRow("",general_hint)
        integration_tabs.addTab(overview,"Übersicht")

        # --- TeamSpeak -----------------------------------------------------
        ts_page=QWidget(); f=QFormLayout(ts_page)
        self.ts_commander_enabled=QCheckBox("Channel Commander bei Funk-RX automatisch setzen")
        self.ts_commander_enabled.setChecked(True)
        self.ts_commander_enabled.setToolTip(
            "Setzt beim gültigen Funkempfang den Channel Commander und nimmt ihn "
            "nach Ende des Funkdurchgangs wieder zurück."
        )
        self.ts_host=QLineEdit("127.0.0.1")
        self.ts_port=QSpinBox(); self.ts_port.setRange(1,65535); self.ts_port.setValue(25639)
        self.ts_api_key=QLineEdit(); self.ts_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ts_api_key.setPlaceholderText("ClientQuery API-Key")
        self.ts_show_key=QCheckBox("API-Key anzeigen")
        self.ts_show_key.toggled.connect(self.toggle_ts_api_key_visibility)
        load_key=QPushButton("API-Key automatisch laden")
        load_key.setToolTip("Liest den ClientQuery API-Key aus der lokalen TeamSpeak-Konfiguration, wenn möglich.")
        load_key.clicked.connect(self.load_ts_api_key)
        test=QPushButton("TeamSpeak-Verbindung testen")
        test.setToolTip("Prüft ClientQuery, Anmeldung und den aktuellen TeamSpeak-Kontext.")
        test.clicked.connect(self.test_teamspeak)
        self.ts_status=QLabel("TeamSpeak: Modul ausgeschaltet")
        self.ts_status.setWordWrap(True)
        self.ts_status.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.ts_speaker=QLabel("Aktueller TeamSpeak-Sprecher: —")
        self.ts_speaker.setWordWrap(True)
        self.ts_speaker.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.ts_speaker.setStyleSheet("font-size: 20px; font-weight: bold; padding: 8px;")
        self.ts_channel=QLabel("Aktiver TeamSpeak-Channel: —")
        self.ts_channel.setWordWrap(True)
        self.ts_channel.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.ts_channel.setStyleSheet("font-size: 17px; font-weight: bold; padding: 6px;")
        self.ts_channel_combo=QComboBox()
        self.ts_channel_combo.addItem("Channel-Liste noch nicht geladen", None)
        refresh_channels=QPushButton("TeamSpeak-Channels neu laden")
        refresh_channels.setToolTip("Lädt die für den aktuellen TeamSpeak-Server sichtbaren Channels neu.")
        refresh_channels.clicked.connect(self.refresh_ts_channels)
        move_channel=QPushButton("Gateway in ausgewählten Channel verschieben")
        move_channel.setToolTip("Verschiebt nur den eigenen Gateway-Client in den ausgewählten TeamSpeak-Channel.")
        move_channel.clicked.connect(self.move_ts_gateway)
        copy_status=QPushButton("TeamSpeak-Status kopieren")
        copy_status.setToolTip("Kopiert Status, aktiven Channel und Sprecher für eine einfache Fehlersuche.")
        copy_status.clicked.connect(self.copy_teamspeak_status)

        # TeamSpeak-spezifischer Störungsraum gehört zur Integration, nicht zu
        # den allgemeinen Schutz-/Ansageeinstellungen.
        self.protect_room_enabled=QCheckBox("TeamSpeak-Störungsraum-Schutz aktiv")
        self.protect_room_combo=QComboBox()
        self.protect_room_combo.addItem("Channel-Liste noch nicht geladen",None)
        refresh_protect=QPushButton("TeamSpeak-Channels für Störungsraum neu laden")
        refresh_protect.clicked.connect(self.refresh_protection_channels)
        set_room=QPushButton("Ausgewählten Channel als TeamSpeak-Störungsraum setzen")
        set_room.clicked.connect(self.set_selected_disturbance_room)
        clear_room=QPushButton("TeamSpeak-Störungsraum für diesen Server löschen")
        clear_room.clicked.connect(self.clear_disturbance_room)
        self.protect_room_status=QLabel("TeamSpeak-Störungsraum: für diesen Server noch nicht geprüft")
        self.protect_room_status.setWordWrap(True)
        self.protect_room_status.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.protect_move_to_room=QCheckBox("Bei Dauer-RX automatisch in den TeamSpeak-Störungsraum verschieben")
        self.protect_return_channel=QCheckBox("Nach Wiederaktivierung in den vorherigen TeamSpeak-Channel zurückkehren")
        self.protect_return_channel.setChecked(True)
        self.protect_move_to_room.setToolTip("Verschiebt nur den eigenen TeamSpeak-Gateway-Client in den für diesen Server gespeicherten Störungsraum.")
        set_room.setToolTip("Speichert den ausgewählten TeamSpeak-Channel als Störungsraum für den aktuell verbundenen Server.")

        note=QLabel(
            "Das TeamSpeak-Modul ist optional. FunkGateway arbeitet auch bei ausgeschaltetem "
            "oder nicht erreichbarem TeamSpeak normal weiter. Benötigt wird beim klassischen "
            "TS3-Client das aktivierte ClientQuery-Plugin (Standard: 127.0.0.1:25639)."
        )
        note.setWordWrap(True)

        f.addRow(self.ts_commander_enabled)
        f.addRow("ClientQuery Host:",self.ts_host)
        f.addRow("ClientQuery Port:",self.ts_port)
        f.addRow("ClientQuery API-Key:",self.ts_api_key)
        f.addRow("",self.ts_show_key)
        f.addRow(load_key)
        f.addRow(test)
        f.addRow("",self.ts_status)
        f.addRow("",self.ts_channel)
        f.addRow("",self.ts_speaker)
        f.addRow("Ziel-Channel:",self.ts_channel_combo)
        f.addRow(refresh_channels)
        f.addRow(move_channel)
        f.addRow("",copy_status)
        f.addRow(QLabel("<b>TeamSpeak-Störungsraum</b>"))
        ts_room_note=QLabel(
            "Hier wird nur festgelegt, welcher TeamSpeak-Channel der Störungsraum ist "
            "und ob FunkGateway ihn bei Dauer-RX automatisch benutzt. WAV-Ansagen und "
            "Wiederholungsintervall liegen neutral unter Schutz → Ansagen und gelten "
            "gemeinsam für TeamSpeak und Mumble."
        )
        ts_room_note.setWordWrap(True)
        f.addRow("",ts_room_note)
        f.addRow("",self.protect_room_enabled)
        f.addRow("Channel auswählen:",self.protect_room_combo)
        f.addRow(refresh_protect)
        f.addRow(set_room)
        f.addRow(clear_room)
        f.addRow("",self.protect_room_status)
        f.addRow("",self.protect_move_to_room)
        f.addRow("",self.protect_return_channel)
        f.addRow("",note)
        integration_tabs.addTab(ts_page,"TeamSpeak")

        # --- Mumble --------------------------------------------------------
        # The Mumble page can become quite tall (local client, Bridge, Ice and
        # SSH administration).  Keep the entire page scrollable so credentials
        # and emergency/admin controls never disappear below the window edge.
        mumble_page=QWidget()
        mumble_outer=QVBoxLayout(mumble_page)
        mumble_scroll=QScrollArea()
        mumble_scroll.setWidgetResizable(True)
        mumble_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        mumble_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        mumble_content=QWidget()
        mf=QFormLayout(mumble_content)
        mumble_scroll.setWidget(mumble_content)
        mumble_outer.addWidget(mumble_scroll)
        mumble_title=QLabel("<b>Mumble-Integration</b>")
        mumble_note=QLabel(
            "Die Grundfunktionen arbeiten lokal mit dem Mumble-Client. Dafür sind keine "
            "Server-Adminrechte nötig. Ice ist optional und nur für erweiterte "
            "Serverfunktionen wie Channel-Liste und Störungsraum erforderlich."
        )
        mumble_note.setWordWrap(True)
        self.mumble_status=QLabel("Mumble: noch nicht geprüft")
        self.mumble_status.setWordWrap(True); self.mumble_status.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.mumble_channel=QLabel("Aktiver Mumble-Channel: —")
        self.mumble_channel.setWordWrap(True); self.mumble_channel.setStyleSheet("font-size: 17px; font-weight: bold; padding: 6px;")
        self.mumble_speaker=QLabel("Aktueller Mumble-Sprecher: —")
        self.mumble_speaker.setWordWrap(True); self.mumble_speaker.setStyleSheet("font-size: 20px; font-weight: bold; padding: 8px;")
        self.mumble_details=QLabel("Lokale Steuerung: —")
        self.mumble_details.setWordWrap(True); self.mumble_details.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        check_local=QPushButton("Mumble prüfen")
        check_local.clicked.connect(self.test_mumble_local)
        install_mumble=QPushButton("Mumble-Komponenten installieren / reparieren")
        install_mumble.setToolTip("Installiert fehlende Mumble/Ice-Komponenten oder repariert die FunkGateway-Python-Umgebung, wenn Ice im System bereits vorhanden ist.")
        install_mumble.clicked.connect(self.install_mumble_components)

        ice_head=QLabel("<b>Erweiterte Serversteuerung (optional / Admin)</b>")
        ice_hint=QLabel(
            "Normale Gatewaybetreiber verwenden die Bridge ihres Server-Admins und erhalten nur "
            "eine Bridge-Adresse plus persönliches Token. Das Ice-Secret darf ihnen NICHT gegeben "
            "werden. Direktes Ice/SSH ist ausschließlich für Server-Admins bzw. eigene Server gedacht."
        ); ice_hint.setWordWrap(True)
        self.mumble_ice_mode=QComboBox()
        self.mumble_ice_mode.addItem("Aus – nur lokale Mumble-Funktionen","off")
        self.mumble_ice_mode.addItem("Direktes Ice (Adminbetrieb)","direct")
        self.mumble_ice_mode.addItem("Ice über SSH-Tunnel (empfohlen für Admin)","ssh")
        self.mumble_ice_mode.addItem("Bridge des Server-Admins (Normalnutzer)","bridge")
        self.mumble_ice_host=QLineEdit("127.0.0.1")
        self.mumble_ice_port=QSpinBox(); self.mumble_ice_port.setRange(1,65535); self.mumble_ice_port.setValue(6502)
        self.mumble_ice_server_id=QSpinBox(); self.mumble_ice_server_id.setRange(1,9999); self.mumble_ice_server_id.setValue(1)
        self.mumble_slice=QLineEdit(); self.mumble_slice.setPlaceholderText("Pfad zur passenden Murmur.ice")
        choose_slice=QPushButton("Murmur.ice auswählen"); choose_slice.clicked.connect(self.choose_mumble_slice)
        slice_row=QHBoxLayout(); slice_row.addWidget(self.mumble_slice); slice_row.addWidget(choose_slice)
        self.mumble_read_secret=QLineEdit(); self.mumble_read_secret.setEchoMode(QLineEdit.EchoMode.Password); self.mumble_read_secret.setPlaceholderText("wird nicht gespeichert")
        self.mumble_write_secret=QLineEdit(); self.mumble_write_secret.setEchoMode(QLineEdit.EchoMode.Password); self.mumble_write_secret.setPlaceholderText("nur für Channel-Wechsel; wird nicht gespeichert")
        self.mumble_show_secrets=QCheckBox("Ice-Secrets anzeigen")
        self.mumble_show_secrets.setToolTip("Zeigt Read-/Write-Secret nur vorübergehend im Eingabefeld. Die Secrets werden weiterhin nicht gespeichert.")
        self.mumble_show_secrets.toggled.connect(self.toggle_mumble_secrets)
        self.mumble_ssh_host=QLineEdit(); self.mumble_ssh_host.setPlaceholderText("SSH-Server")
        self.mumble_ssh_port=QSpinBox(); self.mumble_ssh_port.setRange(1,65535); self.mumble_ssh_port.setValue(22)
        self.mumble_ssh_user=QLineEdit(); self.mumble_ssh_user.setPlaceholderText("SSH-Benutzer")
        self.mumble_gateway_name=QLineEdit(); self.mumble_gateway_name.setPlaceholderText("automatisch aus lokalem Mumble, sonst hier eintragen")
        self.mumble_bridge_url=QLineEdit(); self.mumble_bridge_url.setPlaceholderText("https://bridge.example.org")
        self.mumble_bridge_token=QLineEdit(); self.mumble_bridge_token.setEchoMode(QLineEdit.EchoMode.Password); self.mumble_bridge_token.setPlaceholderText("persönliches fgw_... Token; wird nicht gespeichert")
        test_bridge=QPushButton("Bridge-Verbindung / Token prüfen"); test_bridge.clicked.connect(self.test_mumble_bridge)
        export_admin=QPushButton("Admin-Paket speichern / weitergeben"); export_admin.clicked.connect(self.save_mumble_admin_package)
        export_admin.setToolTip("Speichert ein vollständiges Einrichtungs-, Bridge- und Hilfe-Paket zur Weitergabe an den Mumble-Server-Admin.")
        self.mumble_bridge_status=QLabel("Bridge: nicht geprüft")
        self.mumble_bridge_status.setWordWrap(True); self.mumble_bridge_status.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        start_tunnel=QPushButton("SSH-Tunnel starten / prüfen (Admin)"); start_tunnel.clicked.connect(self.start_mumble_ssh_tunnel)
        stop_tunnel=QPushButton("SSH-Tunnel stoppen")
        stop_tunnel.setToolTip("Stoppt nur den von FunkGateway selbst gestarteten Mumble-Ice-SSH-Tunnel.")
        stop_tunnel.clicked.connect(self.stop_mumble_ssh_tunnel)
        ssh_help=QPushButton("SSH sicher einrichten – Anleitung")
        ssh_help.setToolTip("Erklärt SSH-Key, ssh-copy-id, ssh-agent und warum FunkGateway kein SSH-Passwort speichert.")
        ssh_help.clicked.connect(self.show_mumble_ssh_help)
        detect_ice=QPushButton("Ice-Einstellungen automatisch erkennen")
        detect_ice.setToolTip("Sucht lokal oder per SSH nach der Murmur-Ice-Konfiguration und übernimmt einen eindeutig gefundenen Port.")
        detect_ice.clicked.connect(self.detect_mumble_ice_settings)
        test_ice=QPushButton("Ice-Verbindung testen"); test_ice.clicked.connect(self.test_mumble_ice)
        self.mumble_ice_status=QLabel("Erweiterte Serversteuerung: nicht eingerichtet")
        self.mumble_ice_status.setWordWrap(True); self.mumble_ice_status.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        self.mumble_channel_combo=QComboBox(); self.mumble_channel_combo.addItem("Ice-Channel-Liste noch nicht geladen",None)
        load_ice_channels=QPushButton("Mumble-Channels über Ice laden"); load_ice_channels.clicked.connect(self.refresh_mumble_ice_channels)
        move_mumble=QPushButton("Gateway in ausgewählten Mumble-Channel verschieben"); move_mumble.clicked.connect(self.move_mumble_gateway_manual)
        self.mumble_disturbance_combo=QComboBox(); self.mumble_disturbance_combo.addItem("Störungsraum noch nicht gewählt",None)
        set_mumble_room=QPushButton("Ausgewählten Channel als Mumble-Störungsraum setzen"); set_mumble_room.clicked.connect(self.set_mumble_disturbance_room)
        self.mumble_disturbance_status=QLabel("Mumble-Störungsraum: nicht eingerichtet")
        self.mumble_disturbance_status.setWordWrap(True)
        self.protect_move_to_mumble_room=QCheckBox("Bei Dauer-RX automatisch in den Mumble-Störungsraum verschieben")
        self.protect_return_mumble_channel=QCheckBox("Nach Wiederaktivierung in den vorherigen Mumble-Channel zurückkehren")
        self.protect_return_mumble_channel.setChecked(True)
        self.protect_move_to_mumble_room.setToolTip("Verschiebt nur den eigenen Mumble-Gateway-Client in den für diesen Server gespeicherten Störungsraum.")

        mf.addRow(mumble_title); mf.addRow(mumble_note)
        mf.addRow(check_local); mf.addRow(install_mumble)
        mf.addRow("",self.mumble_status); mf.addRow("",self.mumble_channel); mf.addRow("",self.mumble_speaker); mf.addRow("",self.mumble_details)
        mf.addRow(ice_head); mf.addRow(ice_hint)
        mf.addRow("Anbindung:",self.mumble_ice_mode)
        mf.addRow(QLabel("<b>Direktes Ice / SSH – nur Adminmodus</b>"))
        admin_quick=QLabel("Für direkten Ice-Betrieb müssen Host, Port, passende Murmur.ice und mindestens das Read-Secret eingetragen sein. Für Channel-Wechsel wird zusätzlich das Write-Secret benötigt. Bei SSH wird ein Schlüssel/ssh-agent empfohlen; FunkGateway speichert kein SSH-Passwort.")
        admin_quick.setWordWrap(True)
        mf.addRow(admin_quick)
        mf.addRow("Ice Host:",self.mumble_ice_host); mf.addRow("Ice Port:",self.mumble_ice_port); mf.addRow("Server-ID:",self.mumble_ice_server_id)
        mf.addRow("Murmur.ice:",slice_row); mf.addRow("Ice Read-Secret:",self.mumble_read_secret); mf.addRow("Ice Write-Secret:",self.mumble_write_secret); mf.addRow("",self.mumble_show_secrets)
        mf.addRow("SSH-Server:",self.mumble_ssh_host); mf.addRow("SSH-Port:",self.mumble_ssh_port); mf.addRow("SSH-Benutzer:",self.mumble_ssh_user); mf.addRow(ssh_help)
        mf.addRow("Gateway-Mumble-Name:",self.mumble_gateway_name)
        tunnel_buttons=QHBoxLayout(); tunnel_buttons.addWidget(start_tunnel); tunnel_buttons.addWidget(stop_tunnel)
        mf.addRow(tunnel_buttons); mf.addRow(detect_ice); mf.addRow(test_ice); mf.addRow("",self.mumble_ice_status)
        mf.addRow("Ziel-Channel:",self.mumble_channel_combo); mf.addRow(load_ice_channels); mf.addRow(move_mumble)
        mf.addRow(QLabel("<b>Mumble-Störungsraum</b>"))
        mumble_room_note=QLabel(
            "Hier wird nur der Mumble-Störungsraum und der automatische Wechsel festgelegt. "
            "Die gemeinsamen WAV-Ansagen liegen unter Schutz → Ansagen und gelten für "
            "TeamSpeak und Mumble."
        )
        mumble_room_note.setWordWrap(True)
        mf.addRow("",mumble_room_note)
        mf.addRow("Störungsraum:",self.mumble_disturbance_combo)
        mf.addRow(set_mumble_room)
        mf.addRow("",self.mumble_disturbance_status)
        mf.addRow("",self.protect_move_to_mumble_room)
        mf.addRow("",self.protect_return_mumble_channel)
        mf.addRow(QLabel("<b>Bridge für normale Gatewaybetreiber</b>"))
        bridge_help=QLabel("Vom Server-Admin erhältst du nur Bridge-Adresse und persönliches Token. Wenn dein Admin die Bridge noch nicht hat, speichere das Admin-Paket und gib es ihm weiter. Das globale Ice-Secret gehört niemals in diesen Bereich.")
        bridge_help.setWordWrap(True)
        mf.addRow(bridge_help); mf.addRow("Bridge-Adresse:",self.mumble_bridge_url); mf.addRow("Persönliches Token:",self.mumble_bridge_token); mf.addRow(test_bridge); mf.addRow(export_admin); mf.addRow("",self.mumble_bridge_status)
        integration_tabs.addTab(mumble_page,"Mumble")

        self.tabs.addTab(w,"Integrationen")

    def build_dtmf(self):
        page=QWidget()
        f=QFormLayout(page)

        self.dtmf_enabled=QCheckBox("DTMF-Steuerung aktiv")
        self.dtmf_suppress_voip=QCheckBox("DTMF-Töne nicht an VoIP übertragen")
        self.dtmf_suppress_voip.setChecked(True)
        self.dtmf_start_char=QLineEdit("*"); self.dtmf_start_char.setMaxLength(1)
        self.dtmf_end_char=QLineEdit("#"); self.dtmf_end_char.setMaxLength(1)
        self.dtmf_interdigit_ms=QSpinBox(); self.dtmf_interdigit_ms.setRange(500,10000); self.dtmf_interdigit_ms.setValue(2000); self.dtmf_interdigit_ms.setSuffix(" ms")
        self.dtmf_session_max_s=QSpinBox(); self.dtmf_session_max_s.setRange(2,60); self.dtmf_session_max_s.setValue(10); self.dtmf_session_max_s.setSuffix(" s")
        self.dtmf_release_ms=QSpinBox(); self.dtmf_release_ms.setRange(0,2000); self.dtmf_release_ms.setValue(250); self.dtmf_release_ms.setSuffix(" ms")
        self.dtmf_status=QLabel("DTMF: bereit")
        self.dtmf_status.setWordWrap(True)

        self.dtmf_enabled.toggled.connect(self._apply_dtmf_detector_settings)
        self.dtmf_suppress_voip.toggled.connect(self._apply_dtmf_detector_settings)

        f.addRow("",self.dtmf_enabled)
        f.addRow("",self.dtmf_suppress_voip)
        f.addRow("Startzeichen:",self.dtmf_start_char)
        f.addRow("Abschlusszeichen:",self.dtmf_end_char)
        f.addRow("Timeout zwischen Zeichen:",self.dtmf_interdigit_ms)
        f.addRow("Maximale DTMF-Session:",self.dtmf_session_max_s)
        f.addRow("VoIP-Freigabe nach Code:",self.dtmf_release_ms)
        f.addRow("",self.dtmf_status)

        note=QLabel(
            "Standard: * startet eine Steuersitzung und # beendet sie. "
            "Sobald die Sitzung begonnen hat, wird Funk→VoIP stummgeschaltet. "
            "Die einzelnen DTMF-Töne werden mit kurzem Audio-Lookahead ebenfalls unterdrückt, "
            "damit TeamSpeak/Mumble nicht mit Steuertönen zugespammt werden."
        )
        note.setWordWrap(True)
        f.addRow("",note)

        f.addRow(QLabel("<b>DTMF-AUTH (optional)</b>"))
        self.dtmf_auth_enabled=QCheckBox("DTMF-Befehle können per AUTH geschützt werden")
        self.dtmf_auth_method=QComboBox()
        self.dtmf_auth_method.addItem("PIN","pin")
        self.dtmf_auth_method.addItem("TOTP (Authenticator-App)","totp")
        self.dtmf_auth_prefix=QLineEdit("*00*")
        self.dtmf_auth_logout_code=QLineEdit("*00*0#")
        self.dtmf_auth_valid_s=QSpinBox(); self.dtmf_auth_valid_s.setRange(10,3600); self.dtmf_auth_valid_s.setValue(180); self.dtmf_auth_valid_s.setSuffix(" s")
        self.dtmf_auth_max_attempts=QSpinBox(); self.dtmf_auth_max_attempts.setRange(1,10); self.dtmf_auth_max_attempts.setValue(3)
        self.dtmf_auth_lockout_s=QSpinBox(); self.dtmf_auth_lockout_s.setRange(10,3600); self.dtmf_auth_lockout_s.setValue(60); self.dtmf_auth_lockout_s.setSuffix(" s")
        self.dtmf_auth_pin_edit=QLineEdit()
        self.dtmf_auth_pin_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.dtmf_auth_pin_edit.setPlaceholderText("neuen PIN eingeben – 3 bis 12 Ziffern")
        self.dtmf_auth_status=QLabel("AUTH: nicht aktiv")
        self.dtmf_auth_status.setWordWrap(True)
        pin_btn=QPushButton("PIN übernehmen")
        pin_btn.clicked.connect(self._set_dtmf_auth_pin_from_ui)
        pinrow=QHBoxLayout(); pinrow.addWidget(self.dtmf_auth_pin_edit,1); pinrow.addWidget(pin_btn)
        f.addRow("",self.dtmf_auth_enabled)
        f.addRow("AUTH-Verfahren:",self.dtmf_auth_method)
        f.addRow("AUTH-Präfix:",self.dtmf_auth_prefix)
        f.addRow("AUTH beenden:",self.dtmf_auth_logout_code)
        f.addRow("AUTH-Gültigkeit:",self.dtmf_auth_valid_s)
        f.addRow("Fehlversuche max.:",self.dtmf_auth_max_attempts)
        f.addRow("Sperrzeit:",self.dtmf_auth_lockout_s)
        f.addRow("PIN:",pinrow)

        self.dtmf_totp_digits=QSpinBox(); self.dtmf_totp_digits.setRange(6,8); self.dtmf_totp_digits.setValue(6)
        self.dtmf_totp_period=QSpinBox(); self.dtmf_totp_period.setRange(15,120); self.dtmf_totp_period.setValue(30); self.dtmf_totp_period.setSuffix(" s")
        self.dtmf_totp_window=QSpinBox(); self.dtmf_totp_window.setRange(0,2); self.dtmf_totp_window.setValue(1)
        self.dtmf_totp_label=QLineEdit("FunkGateway")
        self.dtmf_totp_account=QLineEdit("DTMF")
        self.dtmf_totp_secret_view=QLineEdit(); self.dtmf_totp_secret_view.setReadOnly(True)
        self.dtmf_totp_uri_view=QLineEdit(); self.dtmf_totp_uri_view.setReadOnly(True)
        gen_totp_btn=QPushButton("TOTP-Geheimnis erzeugen")
        gen_totp_btn.clicked.connect(self._generate_dtmf_totp_secret)
        copy_uri_btn=QPushButton("otpauth-URI kopieren")
        copy_uri_btn.clicked.connect(self._copy_dtmf_totp_uri)
        qr_btn=QPushButton("QR-Code anzeigen")
        qr_btn.clicked.connect(self._show_dtmf_totp_qr)
        totp_btns=QHBoxLayout()
        totp_btns.addWidget(gen_totp_btn)
        totp_btns.addWidget(copy_uri_btn)
        totp_btns.addWidget(qr_btn)
        f.addRow("TOTP-Ziffern:",self.dtmf_totp_digits)
        f.addRow("TOTP-Zeitraum:",self.dtmf_totp_period)
        f.addRow("TOTP-Toleranz ± Schritte:",self.dtmf_totp_window)
        f.addRow("TOTP-Anzeigename:",self.dtmf_totp_label)
        f.addRow("TOTP-Konto:",self.dtmf_totp_account)
        f.addRow("TOTP-Geheimnis:",self.dtmf_totp_secret_view)
        f.addRow("Authenticator-URI:",self.dtmf_totp_uri_view)
        f.addRow("",totp_btns)

        f.addRow("",self.dtmf_auth_status)

        auth_note=QLabel(
            "PIN: Beispiel Präfix *00*, PIN 4711 → *00*4711#. "
            "TOTP: denselben Präfix mit dem aktuellen Authenticator-Code senden. "
            "TOTP funktioniert offline, benötigt aber eine korrekte Systemzeit. "
            "Bereits erfolgreich verwendete TOTP-Zeitschritte werden gegen Wiederholung gesperrt."
        )
        auth_note.setWordWrap(True)
        f.addRow("",auth_note)

        self.dtmf_auth_success_wav=QLineEdit()
        self.dtmf_auth_required_wav=QLineEdit()
        self.dtmf_auth_failed_wav=QLineEdit()
        for label_text,field in (
            ("Ansage „AUTH erfolgreich“:",self.dtmf_auth_success_wav),
            ("Ansage „AUTH erforderlich“:",self.dtmf_auth_required_wav),
            ("Ansage „AUTH fehlgeschlagen“:",self.dtmf_auth_failed_wav),
        ):
            b=QPushButton("…")
            b.clicked.connect(lambda _checked=False, fld=field:self.choose_protection_wav(fld))
            rr=QHBoxLayout(); rr.addWidget(field,1); rr.addWidget(b)
            f.addRow(label_text,rr)

        f.addRow(QLabel("<b>AUTH-Pflicht pro Funktion</b>"))
        self.dtmf_auth_req_parrot=QCheckBox("Papagei EIN")
        self.dtmf_auth_req_voip=QCheckBox("Normaler VoIP-/Gateway-Betrieb")
        self.dtmf_auth_req_ts_mute=QCheckBox("TeamSpeak MUTE")
        self.dtmf_auth_req_ts_unmute=QCheckBox("TeamSpeak UNMUTE")
        self.dtmf_auth_req_ts_deaf=QCheckBox("TeamSpeak DEAF")
        self.dtmf_auth_req_ts_undeaf=QCheckBox("TeamSpeak UNDEAF")
        self.dtmf_auth_req_mumble_mute=QCheckBox("Mumble MUTE")
        self.dtmf_auth_req_mumble_unmute=QCheckBox("Mumble UNMUTE")
        self.dtmf_auth_req_mumble_deaf=QCheckBox("Mumble DEAF")
        self.dtmf_auth_req_mumble_undeaf=QCheckBox("Mumble UNDEAF")
        for cb in (
            self.dtmf_auth_req_parrot,self.dtmf_auth_req_voip,
            self.dtmf_auth_req_ts_mute,self.dtmf_auth_req_ts_unmute,
            self.dtmf_auth_req_ts_deaf,self.dtmf_auth_req_ts_undeaf,
            self.dtmf_auth_req_mumble_mute,self.dtmf_auth_req_mumble_unmute,
            self.dtmf_auth_req_mumble_deaf,self.dtmf_auth_req_mumble_undeaf,
        ):
            cb.setChecked(True)
            f.addRow("",cb)

        f.addRow(QLabel("<b>Betriebsart</b>"))
        self.dtmf_code_parrot_on=QLineEdit("*91#")
        self.dtmf_code_voip_on=QLineEdit("*90#")
        f.addRow("Papagei EIN:",self.dtmf_code_parrot_on)
        f.addRow("Normaler VoIP-Betrieb:",self.dtmf_code_voip_on)

        f.addRow(QLabel("<b>TeamSpeak – lokaler Gateway-Client</b>"))
        self.dtmf_code_ts_mute=QLineEdit("*51#")
        self.dtmf_code_ts_unmute=QLineEdit("*52#")
        self.dtmf_code_ts_deaf=QLineEdit("*53#")
        self.dtmf_code_ts_undeaf=QLineEdit("*54#")
        f.addRow("TS Mikrofon MUTE:",self.dtmf_code_ts_mute)
        f.addRow("TS Mikrofon UNMUTE:",self.dtmf_code_ts_unmute)
        f.addRow("TS DEAF / Ausgabe stumm:",self.dtmf_code_ts_deaf)
        f.addRow("TS UNDEAF:",self.dtmf_code_ts_undeaf)

        f.addRow(QLabel("<b>Mumble – lokaler Gateway-Client</b>"))
        self.dtmf_code_mumble_mute=QLineEdit("*61#")
        self.dtmf_code_mumble_unmute=QLineEdit("*62#")
        self.dtmf_code_mumble_deaf=QLineEdit("*63#")
        self.dtmf_code_mumble_undeaf=QLineEdit("*64#")
        f.addRow("Mumble MUTE:",self.dtmf_code_mumble_mute)
        f.addRow("Mumble UNMUTE:",self.dtmf_code_mumble_unmute)
        f.addRow("Mumble DEAF:",self.dtmf_code_mumble_deaf)
        f.addRow("Mumble UNDEAF:",self.dtmf_code_mumble_undeaf)

        f.addRow(QLabel("<b>Vollzugsmeldung über Funk</b>"))
        self.dtmf_ack_enabled=QCheckBox("Nach ausgeführtem DTMF-Befehl Bestätigung über Funk senden")
        self.dtmf_ack_enabled.setChecked(True)
        self.dtmf_ack_tail_ms=QSpinBox()
        self.dtmf_ack_tail_ms.setRange(0,5000)
        self.dtmf_ack_tail_ms.setValue(2500)
        self.dtmf_ack_tail_ms.setSuffix(" ms")
        self.dtmf_ack_tail_ms.setToolTip(
            "PTT-Nachlauf nach dem Ende der Vollzugsmeldungs-WAV. "
            "Bei virtuellen PulseAudio/PipeWire-Sinks kann noch Audio gepuffert sein. "
            "Standard: 2500 ms."
        )
        self.dtmf_ack_parrot_wav=QLineEdit()
        self.dtmf_ack_voip_wav=QLineEdit()
        self.dtmf_ack_default_wav=QLineEdit()
        ack_parrot_btn=QPushButton("…")
        ack_voip_btn=QPushButton("…")
        ack_default_btn=QPushButton("…")
        ack_parrot_btn.clicked.connect(lambda:self.choose_protection_wav(self.dtmf_ack_parrot_wav))
        ack_voip_btn.clicked.connect(lambda:self.choose_protection_wav(self.dtmf_ack_voip_wav))
        ack_default_btn.clicked.connect(lambda:self.choose_protection_wav(self.dtmf_ack_default_wav))
        f.addRow("PTT-Nachlauf Vollzugsmeldung:",self.dtmf_ack_tail_ms)
        rr=QHBoxLayout(); rr.addWidget(self.dtmf_ack_parrot_wav,1); rr.addWidget(ack_parrot_btn)
        f.addRow("Ansage „Papagei aktiv“:",rr)
        rr=QHBoxLayout(); rr.addWidget(self.dtmf_ack_voip_wav,1); rr.addWidget(ack_voip_btn)
        f.addRow("Ansage „Gateway aktiv“:",rr)
        rr=QHBoxLayout(); rr.addWidget(self.dtmf_ack_default_wav,1); rr.addWidget(ack_default_btn)
        f.addRow("Optionale Standard-Bestätigung:",rr)

        ack_note=QLabel(
            "Für Papagei EIN und normalen VoIP-/Gateway-Betrieb ist eine Funk-Bestätigung "
            "besonders sinnvoll. Die Ansage wird erst nach erfolgreicher Ausführung des "
            "DTMF-Befehls gesendet. Ist keine WAV hinterlegt, wird nur geloggt. "
            "Der PTT-Nachlauf hält den Sender nach dem WAV-Ende noch kurz offen, damit "
            "gepuffertes Audio im virtuellen Audiosystem vollständig über Funk herausläuft."
        )
        ack_note.setWordWrap(True)
        f.addRow("",ack_note)

        f.addRow(QLabel("<b>Raumwechsel per DTMF</b>"))
        rooms_note=QLabel(
            "TeamSpeak-Räume werden über ClientQuery geladen. "
            "Mumble-Räume werden bei direktem Ice/SSH aus der Serverliste geladen. "
            "Der eingeschränkte Mumble-Bridge-Modus erlaubt absichtlich keine beliebigen Raumwechsel."
        )
        rooms_note.setWordWrap(True)
        f.addRow("",rooms_note)

        load_rooms=QPushButton("TeamSpeak-/Mumble-Raumlisten für DTMF laden")
        load_rooms.clicked.connect(self.refresh_dtmf_room_lists)
        f.addRow(load_rooms)

        self.dtmf_ts_room_rows=[]
        self.dtmf_mumble_room_rows=[]
        self.dtmf_ts_room_auth=[]
        self.dtmf_mumble_room_auth=[]
        for i in range(1,6):
            code=QLineEdit()
            code.setPlaceholderText(f"z. B. *1{i}#")
            combo=QComboBox(); combo.addItem("TeamSpeak-Raumliste laden",None)
            auth_cb=QCheckBox("AUTH"); auth_cb.setChecked(True)
            row=QHBoxLayout(); row.addWidget(code); row.addWidget(combo,1); row.addWidget(auth_cb)
            f.addRow(f"TS Raum {i} – Code / Ziel:",row)
            self.dtmf_ts_room_rows.append((code,combo))
            self.dtmf_ts_room_auth.append(auth_cb)

        for i in range(1,6):
            code=QLineEdit()
            code.setPlaceholderText(f"z. B. *2{i}#")
            combo=QComboBox(); combo.addItem("Mumble-Raumliste laden",None)
            auth_cb=QCheckBox("AUTH"); auth_cb.setChecked(True)
            row=QHBoxLayout(); row.addWidget(code); row.addWidget(combo,1); row.addWidget(auth_cb)
            f.addRow(f"Mumble Raum {i} – Code / Ziel:",row)
            self.dtmf_mumble_room_rows.append((code,combo))
            self.dtmf_mumble_room_auth.append(auth_cb)

        self.dtmf_test_code=QLineEdit()
        self.dtmf_test_code.setPlaceholderText("*91#")
        test_btn=QPushButton("DTMF-Code intern testen")
        test_btn.clicked.connect(lambda:self._execute_dtmf_code(self._clean_dtmf_code(self.dtmf_test_code.text()),test_only=True))
        tr=QHBoxLayout(); tr.addWidget(self.dtmf_test_code); tr.addWidget(test_btn)
        f.addRow("Test ohne Funk:",tr)

        pdf_btn=QPushButton("DTMF-Code-Liste als PDF speichern …")
        pdf_btn.setToolTip(
            "Erstellt eine druckfertige A4-PDF mit allen aktuell eingestellten "
            "DTMF-Codes einschließlich TeamSpeak-/Mumble-Raumwechseln."
        )
        pdf_btn.clicked.connect(self.export_dtmf_codes_pdf)
        f.addRow("",pdf_btn)

        self.tabs.addTab(page,"DTMF")

    def build_protection(self):
        w=QWidget()
        outer=QVBoxLayout(w)
        protection_tabs=QTabWidget()
        outer.addWidget(protection_tabs)

        # --- Allgemein -----------------------------------------------------
        general=QWidget(); f=QFormLayout(general)
        self.protect_rx_enabled=QCheckBox("Dauer-RX-Schutz aktiv")
        self.protect_rx_seconds=QSpinBox(); self.protect_rx_seconds.setRange(10,3600); self.protect_rx_seconds.setValue(180); self.protect_rx_seconds.setSuffix(" s")
        self.protect_auto_unmute=QCheckBox("Nach einer Zeit automatisch wieder aktivieren")
        self.protect_unmute_seconds=QSpinBox(); self.protect_unmute_seconds.setRange(5,3600); self.protect_unmute_seconds.setValue(60); self.protect_unmute_seconds.setSuffix(" s")
        self.protect_require_rx_free=QCheckBox("Nur wieder aktivieren, wenn Funk-RX stabil frei war")
        self.protect_require_rx_free.setChecked(True)
        self.protect_free_seconds=QSpinBox(); self.protect_free_seconds.setRange(1,60); self.protect_free_seconds.setValue(3); self.protect_free_seconds.setSuffix(" s")
        self.protect_free_threshold=QSpinBox(); self.protect_free_threshold.setRange(-80,-5); self.protect_free_threshold.setValue(-30); self.protect_free_threshold.setSuffix(" dBFS")
        reactivate=QPushButton("Gateway jetzt wieder aktivieren")
        reactivate.clicked.connect(lambda:self.unmute_gateway("manuell"))

        self.protect_rx_enabled.setToolTip("Schaltet das Gateway stumm, wenn Funk-RX länger als die eingestellte Zeit dauerhaft aktiv bleibt.")
        self.protect_rx_seconds.setToolTip("Nach dieser Dauer eines ununterbrochenen Funkempfangs wird der Schutz ausgelöst.")
        self.protect_auto_unmute.setToolTip("FunkGateway kann sich nach einer Schutzabschaltung selbst wieder aktivieren.")
        self.protect_require_rx_free.setToolTip("Automatische Wiederaktivierung erst, wenn Funk-RX für die eingestellte Zeit durchgehend frei und leise genug war.")
        self.protect_free_seconds.setToolTip("So lange muss Funk-RX ohne Unterbrechung frei bleiben. Ein kurzer Frei-Impuls reicht nicht.")
        self.protect_free_threshold.setToolTip("Für die Schutzfreigabe muss der RX-Pegel während der ganzen Frei-Zeit unter diesem Wert bleiben.")
        reactivate.setToolTip("Hebt eine Schutzabschaltung auf und gibt das Gateway wieder frei.")

        f.addRow("Dauer-RX:",self.protect_rx_enabled)
        f.addRow("Dauer-RX erkannt nach:",self.protect_rx_seconds)
        f.addRow("Wiederanlauf:",self.protect_auto_unmute)
        f.addRow("Wieder aktivieren nach:",self.protect_unmute_seconds)
        f.addRow("",self.protect_require_rx_free)
        f.addRow("Stabil frei für:",self.protect_free_seconds)
        f.addRow("Schutz-Frei-Schwelle:",self.protect_free_threshold)
        f.addRow(reactivate)
        general_note=QLabel(
            "Die Auswahl der jeweiligen Störungsräume liegt bei der passenden Integration: "
            "Integrationen → TeamSpeak bzw. Integrationen → Mumble."
        )
        general_note.setWordWrap(True)
        f.addRow("",general_note)
        protection_tabs.addTab(general,"Allgemein")

        # --- Gemeinsame Ansagen -------------------------------------------
        announcements=QWidget(); af=QFormLayout(announcements)
        self.protect_room_repeat=QCheckBox("Störungsraum-Ansage regelmäßig wiederholen")
        self.protect_room_repeat.setChecked(True)
        self.protect_room_repeat_min=QSpinBox(); self.protect_room_repeat_min.setRange(1,1440); self.protect_room_repeat_min.setValue(10); self.protect_room_repeat_min.setSuffix(" min")

        self.protect_mute_wav=QLineEdit()
        b1=QPushButton("WAV auswählen"); b1.clicked.connect(lambda:self.choose_protection_wav(self.protect_mute_wav))
        r1=QHBoxLayout(); r1.addWidget(self.protect_mute_wav); r1.addWidget(b1)

        self.protect_room_wav=QLineEdit()
        b2=QPushButton("WAV auswählen"); b2.clicked.connect(lambda:self.choose_protection_wav(self.protect_room_wav))
        r2=QHBoxLayout(); r2.addWidget(self.protect_room_wav); r2.addWidget(b2)

        self.protect_restore_wav=QLineEdit()
        b3=QPushButton("WAV auswählen"); b3.clicked.connect(lambda:self.choose_protection_wav(self.protect_restore_wav))
        r3=QHBoxLayout(); r3.addWidget(self.protect_restore_wav); r3.addWidget(b3)

        shared_note=QLabel(
            "<b>Diese Ansagen sind integrationsneutral.</b> Sie werden für TeamSpeak und "
            "Mumble gleichermaßen benutzt. Spätere Integrationen können denselben "
            "Schutz-Audiopfad ebenfalls verwenden."
        )
        shared_note.setWordWrap(True)
        self.protect_room_repeat.setToolTip("Wiederholt die gemeinsame Störungsraum-Ansage nach dem eingestellten Zeitraum – unabhängig davon, ob TeamSpeak oder Mumble verwendet wird.")

        af.addRow("",shared_note)
        af.addRow("Ansage bei Stummschaltung:",r1)
        af.addRow("Ansage im Störungsraum:",r2)
        af.addRow("",self.protect_room_repeat)
        af.addRow("Wiederholintervall:",self.protect_room_repeat_min)
        af.addRow("Ansage bei Wiederaktivierung:",r3)
        protection_tabs.addTab(announcements,"Ansagen")

        # --- Selbstrücklauf ------------------------------------------------
        return_page=QWidget(); rf=QFormLayout(return_page)
        self.return_guard_enabled=QCheckBox("Selbstrücklauf-Schutz aktiv")
        self.return_guard_enabled.setChecked(True)

        self.return_after_voip=QCheckBox("Nach VoIP-Durchgang (TeamSpeak / Mumble / andere Internetquellen)")
        self.return_after_voip.setChecked(True)
        self.return_after_beacon=QCheckBox("Nach Rufzeichenbake")
        self.return_after_beacon.setChecked(True)
        self.return_after_roger=QCheckBox("Nach Rogerbeep / CW-K")
        self.return_after_roger.setChecked(True)
        self.return_after_protection=QCheckBox("Nach Schutzansagen / WAV-Ausgaben")
        self.return_after_protection.setChecked(True)
        self.return_after_manual=QCheckBox("Nach manuellen lokalen Aussendungen")
        self.return_after_manual.setChecked(False)

        self.return_guard_ms=QSpinBox(); self.return_guard_ms.setRange(0,15000); self.return_guard_ms.setValue(3500); self.return_guard_ms.setSuffix(" ms")
        self.return_max_tail_ms=QSpinBox(); self.return_max_tail_ms.setRange(100,15000); self.return_max_tail_ms.setValue(2500); self.return_max_tail_ms.setSuffix(" ms")
        self.return_real_passage_ms=QSpinBox(); self.return_real_passage_ms.setRange(500,60000); self.return_real_passage_ms.setValue(5000); self.return_real_passage_ms.setSuffix(" ms")
        self.return_repeat_wait_ms=QSpinBox(); self.return_repeat_wait_ms.setRange(0,30000); self.return_repeat_wait_ms.setValue(3000); self.return_repeat_wait_ms.setSuffix(" ms")
        self.return_window_s=QSpinBox(); self.return_window_s.setRange(5,300); self.return_window_s.setValue(30); self.return_window_s.setSuffix(" s")
        self.return_count_limit=QSpinBox(); self.return_count_limit.setRange(1,20); self.return_count_limit.setValue(3)

        self.return_escalate=QCheckBox("Bei wiederholtem Selbstrücklauf Gateway-Schutz aktivieren")
        self.return_escalate.setChecked(True)
        self.return_move_rooms=QCheckBox("Bei Schutzaktivierung konfigurierte TeamSpeak-/Mumble-Störungsräume verwenden")
        self.return_move_rooms.setChecked(True)

        self.return_lost_wav=QLineEdit()
        rb=QPushButton("WAV auswählen")
        rb.clicked.connect(lambda:self.choose_protection_wav(self.return_lost_wav))
        rr=QHBoxLayout(); rr.addWidget(self.return_lost_wav); rr.addWidget(rb)

        defaults = {
            self.return_guard_ms:"Schutzfenster nach Sendeende. RX, das in diesem Fenster beginnt, wird zunächst nicht zu VoIP übertragen. Standard: 3500 ms.",
            self.return_max_tail_ms:"Bis zu dieser RX-Dauer wird ein blockierter Impuls als kurzer Rücklauf gezählt. Standard: 2500 ms.",
            self.return_real_passage_ms:"Ab dieser Dauer gilt ein blockierter RX als wahrscheinlich echter Funkdurchgang. Danach kann eine Wiederholungsansage gesendet werden. Standard: 5000 ms.",
            self.return_repeat_wait_ms:"Wartezeit nach Ende des verlorenen Durchgangs bis zur Hinweisansage. Standard: 3000 ms.",
            self.return_window_s:"Zeitraum, in dem Rücklaufereignisse für die Eskalation gezählt werden. Standard: 30 Sekunden.",
            self.return_count_limit:"Anzahl kurzer Rückläufe im Beobachtungszeitraum bis zur Schutzaktivierung. Standard: 3 Ereignisse.",
        }
        for widget,tip in defaults.items():
            widget.setToolTip(tip)

        intro=QLabel(
            "Der Selbstrücklauf-Schutz startet nach den unten ausgewählten eigenen HF-Aussendungen. "
            "Beginnt RX innerhalb des Schutzfensters, wird der komplette RX-Durchgang vermessen und "
            "bis zu seinem Ende nicht an TeamSpeak/Mumble weitergegeben. Beginnt ein Funker erst nach "
            "dem Schutzfenster, läuft sein Durchgang normal; lange normale RX-Durchgänge bleiben Aufgabe "
            "des bestehenden Dauer-RX-Schutzes."
        ); intro.setWordWrap(True)

        lost_note=QLabel(
            "Ist ein innerhalb des Schutzfensters begonnener RX länger als die Schwelle „echter Durchgang“, "
            "wird er nicht als kurzer Rücklauf gezählt. Optional wird nach seinem Ende die gewählte WAV über HF "
            "gesendet, damit der Funker seinen nicht übertragenen Durchgang nach der eingestellten Wartezeit wiederholen kann."
        ); lost_note.setWordWrap(True)

        rf.addRow("",intro)
        rf.addRow("",self.return_guard_enabled)
        rf.addRow(QLabel("<b>Schutz starten nach:</b>"))
        rf.addRow("",self.return_after_voip)
        rf.addRow("",self.return_after_beacon)
        rf.addRow("",self.return_after_roger)
        rf.addRow("",self.return_after_protection)
        rf.addRow("",self.return_after_manual)
        rf.addRow("Schutzzeit nach Sendeende:",self.return_guard_ms)
        rf.addRow("Maximale Rücklauflänge:",self.return_max_tail_ms)
        rf.addRow("Echter Durchgang ab:",self.return_real_passage_ms)
        rf.addRow("Wartezeit vor Wiederholungsansage:",self.return_repeat_wait_ms)
        rf.addRow("Hinweisansage verlorener Durchgang:",rr)
        rf.addRow("",lost_note)
        rf.addRow(QLabel("<b>Eskalation:</b>"))
        rf.addRow("Beobachtungszeitraum:",self.return_window_s)
        rf.addRow("Rückläufe bis Schutz:",self.return_count_limit)
        rf.addRow("",self.return_escalate)
        rf.addRow("",self.return_move_rooms)
        protection_tabs.addTab(return_page,"Selbstrücklauf")

        note=QLabel(
            "Alle Schutzfunktionen sind optional. TeamSpeak- und Mumble-spezifische "
            "Störungsräume werden in der jeweiligen Integration eingerichtet; "
            "Schutzlogik und WAV-Ansagen bleiben gemeinsam."
        )
        note.setWordWrap(True)
        outer.addWidget(note)
        self.tabs.addTab(w,"Schutz")

    def build_updates(self):
        w=QWidget(); f=QFormLayout(w)
        self.update_current=QLabel(f"Installierte Version: {VERSION}")
        self.update_latest=QLabel("Aktuelle GitHub-Version: noch nicht geprüft")
        self.update_asset=QLabel("Passendes Paket: —")
        self.update_status=QLabel(
            "FunkGateway prüft ausschließlich veröffentlichte Releases im öffentlichen "
            "GitHub-Repository MysticFire01/Funkgateway."
        )
        self.update_status.setWordWrap(True)

        self.update_check_start=QCheckBox("Beim Programmstart nach Updates suchen")
        self.update_check_start.setChecked(False)

        check=QPushButton("Nach Updates suchen")
        check.clicked.connect(self.check_for_updates)
        prepare=QPushButton("Update herunterladen und vorbereiten")
        prepare.clicked.connect(self.prepare_update)
        self.update_prepare_btn=prepare
        self.update_prepare_btn.setEnabled(False)

        release=QPushButton("GitHub-Releases öffnen")
        release.clicked.connect(lambda:webbrowser.open("https://github.com/MysticFire01/Funkgateway/releases"))

        note=QLabel(
            "Sicherheit: Ein Update wird nur vorbereitet, wenn Gateway/PTT nicht aktiv sind. "
            "Das ZIP wird per SHA256 geprüft und in einen neuen Versionsordner entpackt; die "
            "laufende Installation wird nicht überschrieben. ~/.config/funkgateway-ui bleibt erhalten."
        ); note.setWordWrap(True)

        f.addRow("",self.update_current)
        f.addRow("",self.update_latest)
        f.addRow("",self.update_asset)
        f.addRow("",self.update_status)
        f.addRow("",self.update_check_start)
        f.addRow(check)
        f.addRow(prepare)
        f.addRow(release)
        f.addRow("",note)
        self.tabs.addTab(w,"Updates")

    def check_for_updates(self, quiet=False):
        try:
            release=fetch_latest_release()
            tag=str(release.get("tag_name") or "").lstrip("v")
            asset=choose_asset(release)
            self.latest_release=release
            self.latest_release_asset=asset
            self.update_latest.setText(f"Aktuelle GitHub-Version: {tag or 'unbekannt'}")
            self.update_asset.setText("Passendes Paket: " + (asset.get("name","—") if asset else "nicht gefunden"))
            if tag and is_newer(tag,VERSION):
                self.update_status.setText(f"Update verfügbar: {VERSION} → {tag}")
                self.update_prepare_btn.setEnabled(bool(asset))
                if not quiet:
                    QMessageBox.information(self,"FunkGateway Update",f"Eine neue Version ist verfügbar: {tag}")
            else:
                self.update_status.setText("Kein neueres veröffentlichtes Release gefunden.")
                self.update_prepare_btn.setEnabled(False)
                if not quiet:
                    QMessageBox.information(self,"FunkGateway Update","Du verwendest bereits diese oder eine neuere Version.")
        except Exception as e:
            self.latest_release=None; self.latest_release_asset=None
            self.update_prepare_btn.setEnabled(False)
            self.update_status.setText(f"Updateprüfung fehlgeschlagen: {e}")
            if not quiet:
                self.show_copyable_error("Updateprüfung",str(e))

    def prepare_update(self):
        if self.tx or self.outgoing_audio_active or self.roger_busy or self.protection_announcement_busy:
            QMessageBox.warning(
                self,"Update",
                "Update nicht möglich, solange FunkGateway sendet oder eine interne Aussendung läuft. "
                "Bitte Gateway/Sendung zuerst beenden."
            )
            return
        if self.bridge or self.rx_detector:
            QMessageBox.warning(
                self,"Update",
                "Bitte zuerst „Gateway stoppen“. Ein Update wird niemals in einen laufenden Gatewaybetrieb eingespielt."
            )
            return
        if not self.latest_release or not self.latest_release_asset:
            self.check_for_updates()
            if not self.latest_release or not self.latest_release_asset:
                return
        try:
            install_root=Path(__file__).resolve().parents[1]
            result=download_and_prepare(self.latest_release,self.latest_release_asset,install_root.parent)
            self.update_status.setText(
                "Update geprüft und vorbereitet. Neue Version liegt in:\n" + result["target"]
            )
            self.log(f"Update vorbereitet: {result['asset']} -> {result['target']} (SHA256 {result['sha256']})")
            QMessageBox.information(
                self,"Update vorbereitet",
                "Das Update wurde heruntergeladen, per SHA256 geprüft und in einen neuen "
                "Versionsordner entpackt.\n\n"
                f"Neue Installation:\n{result['target']}\n\n"
                "Die aktuelle Installation wurde nicht überschrieben."
            )
        except Exception as e:
            self.show_copyable_error("Update vorbereiten",str(e))

    def choose_protection_wav(self, field):
        p,_=QFileDialog.getOpenFileName(self,"Ansage-WAV wählen","","WAV (*.wav)")
        if p:
            field.setText(p); self.save_cfg()

    def _set_gateway_protection_display(self):
        if self.protection_muted:
            reason=self.protection_reason or "Schutz"
            self.gateway_state_big.setText(f"GATEWAY GEMUTET – {reason}")
            self.gateway_state_big.setStyleSheet("font-size: 22px; font-weight: bold; padding: 8px; border: 3px solid #9b1c1c; border-radius: 8px;")
        else:
            self.gateway_state_big.setText("GATEWAY AKTIV")
            self.gateway_state_big.setStyleSheet("font-size: 22px; font-weight: bold; padding: 8px; border: 2px solid #555; border-radius: 8px;")

    def _refresh_rx_forward_mute(self):
        parrot_muted=bool(
            hasattr(self,"parrot_enabled") and self.parrot_enabled.isChecked()
            and hasattr(self,"parrot_mute_voip") and self.parrot_mute_voip.isChecked()
        )
        dtmf_muted=bool(getattr(self,"dtmf_session_muted",False))
        muted=bool(self.protection_muted or self.return_guard_muted or parrot_muted or dtmf_muted)
        if self.rx_detector and hasattr(self.rx_detector,"set_output_muted"):
            self.rx_detector.set_output_muted(muted)

    def _set_rx_forward_muted(self, muted):
        # Compatibility helper used by the existing protection logic.
        if muted:
            self.return_guard_muted = self.return_guard_muted
        self._refresh_rx_forward_mute()

    def _set_tx_forward_muted(self, muted=False):
        """Mute the mixed FunkGateway_TX.monitor -> radio bridge when required.

        In Papagei mode we must mute the *whole* monitor bridge, not merely the
        TeamSpeak sink-input.  Otherwise any VoIP audio already mixed into the
        null-sink can ride along whenever PTT is keyed by Papagei/ACK/beacon.
        Internal Papagei/ACK/beacon WAVs bypass this bridge and are played
        directly to the selected radio output.
        """
        parrot_isolation=bool(
            hasattr(self,"parrot_enabled")
            and self.parrot_enabled.isChecked()
            and hasattr(self,"parrot_mute_voip")
            and self.parrot_mute_voip.isChecked()
        )
        effective=bool(muted or self.protection_muted or parrot_isolation)
        if self.bridge and hasattr(self.bridge,"set_output_muted"):
            self.bridge.set_output_muted(effective)

    def play_protection_announcement(self, path, label):
        p=Path(str(path).strip()) if str(path).strip() else None
        if not p or not p.exists():
            self.log(f"Schutzansage '{label}' nicht gesendet: keine gültige WAV gewählt.")
            return
        sink=self.target_sink.currentData()
        if not sink:
            self.log(f"Schutzansage '{label}' nicht gesendet: kein Funkgeräte-Ausgang gewählt.")
            return
        if self.protection_announcement_busy:
            self.protection_announcement_queue.append((str(p),str(label)))
            self.log(f"Schutzansage vorgemerkt: {label}")
            return
        try:
            if not self.ptt: self.create_ptt()
            self.protection_announcement_busy=True
            self.active_tx_kind="protection"
            self.set_ptt(True)
            proc=subprocess.Popen(
                ["paplay",f"--device={sink}",str(p)],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL
            )
            self.protection_announcement_proc=proc
            self.log(f"Schutzansage über Funk gestartet: {label}")
            def poll():
                if proc.poll() is None:
                    QTimer.singleShot(100,poll); return
                self.protection_announcement_busy=False
                self.protection_announcement_proc=None
                if not self.outgoing_audio_active or self.protection_muted:
                    self.set_ptt(False)
                self.log(f"Schutzansage beendet: {label}")
                if self.protection_announcement_queue:
                    next_path,next_label=self.protection_announcement_queue.pop(0)
                    QTimer.singleShot(
                        350,
                        lambda p=next_path,l=next_label:self.play_protection_announcement(p,l)
                    )
            QTimer.singleShot(100,poll)
        except Exception as e:
            self.protection_announcement_busy=False
            self.protection_announcement_proc=None
            self.log(f"Schutzansage fehlgeschlagen ({label}): {e}")

    @staticmethod
    def _clean_dtmf_code(value):
        allowed=set("0123456789*#ABCD")
        return "".join(ch for ch in str(value).upper().replace(" ","") if ch in allowed)

    def _apply_dtmf_detector_settings(self,*_args):
        if self.rx_detector and hasattr(self.rx_detector,"configure_dtmf"):
            self.rx_detector.configure_dtmf(
                self.dtmf_enabled.isChecked(),
                self.dtmf_suppress_voip.isChecked(),
                200
            )

    def _on_dtmf_digit(self,digit):
        if not hasattr(self,"dtmf_enabled") or not self.dtmf_enabled.isChecked():
            return
        digit=str(digit).upper()
        now=time.monotonic()
        start=(self.dtmf_start_char.text().strip() or "*")[0].upper()
        end=(self.dtmf_end_char.text().strip() or "#")[0].upper()

        auth_prefix=self._clean_dtmf_code(self.dtmf_auth_prefix.text()) if hasattr(self,"dtmf_auth_prefix") else "*00*"
        auth_sensitive=bool(self.dtmf_session_active and self.dtmf_buffer.startswith(auth_prefix))
        if auth_sensitive:
            self.log("DTMF erkannt: [AUTH-Zeichen]")
        else:
            self.log(f"DTMF erkannt: {digit}")

        if not self.dtmf_session_active:
            if digit != start:
                self.dtmf_status.setText(f"DTMF: einzelnes Zeichen {digit} unterdrückt / geloggt")
                return
            self.dtmf_release_token += 1
            self.dtmf_session_active=True
            self.dtmf_control_rx_active=True
            self.dtmf_session_muted=True
            self.dtmf_buffer=digit
            self.dtmf_session_started=now
            self.dtmf_last_digit=now
            self._refresh_rx_forward_mute()
            self.dtmf_status.setText(f"DTMF: Steuersitzung aktiv – {self.dtmf_buffer}")
            self.log(f"DTMF-Steuersitzung gestartet: {digit} – Funk→VoIP stumm.")
            return

        self.dtmf_buffer += digit
        self.dtmf_last_digit=now
        self.dtmf_status.setText(f"DTMF: {self.dtmf_buffer}")

        if len(self.dtmf_buffer) > 32:
            self._finish_dtmf_session("zu viele Zeichen – verworfen")
            return

        if digit == end:
            code=self._clean_dtmf_code(self.dtmf_buffer)
            if self._is_dtmf_auth_sequence(code):
                self.log("DTMF-AUTH-Sequenz vollständig: ****")
            else:
                self.log(f"DTMF-Code vollständig: {code}")
            try:
                self._execute_dtmf_code(code)
            except Exception as e:
                # A command handler must never leave the DTMF session hanging.
                self.log(f"DTMF-Code {code}: interner Fehler bei der Ausführung: {e}")
            finally:
                self._finish_dtmf_session("Code abgeschlossen")

    def _finish_dtmf_session(self,reason):
        code=self.dtmf_buffer
        self.dtmf_session_active=False
        self.dtmf_buffer=""
        self.dtmf_session_started=None
        self.dtmf_last_digit=None
        self.dtmf_release_token += 1
        token=self.dtmf_release_token
        delay=self.dtmf_release_ms.value() if hasattr(self,"dtmf_release_ms") else 250
        self.dtmf_status.setText(f"DTMF: {reason}; VoIP-Freigabe in {delay} ms")
        self.log(f"DTMF: {reason} ({code or 'leer'}); VoIP-Freigabe nach {delay} ms.")

        def release():
            if token != self.dtmf_release_token:
                return
            if self.dtmf_session_active:
                return
            self.dtmf_session_muted=False
            self._refresh_rx_forward_mute()
            self.dtmf_status.setText("DTMF: bereit")
        QTimer.singleShot(delay,release)

    def _dtmf_tick(self,now):
        if hasattr(self,"dtmf_auth_enabled") and self.dtmf_auth_enabled.isChecked():
            if self.dtmf_auth_active_until and now >= self.dtmf_auth_active_until:
                self.dtmf_auth_active_until=0.0
                if not self.dtmf_auth_expiry_logged:
                    self.log("DTMF-AUTH: Freigabe abgelaufen.")
                    self.dtmf_auth_status.setText("AUTH: abgelaufen")
                    self.dtmf_auth_expiry_logged=True
            if self.dtmf_auth_locked_until and now >= self.dtmf_auth_locked_until:
                self.dtmf_auth_locked_until=0.0
                self.dtmf_auth_fail_count=0
                self.log("DTMF-AUTH: Sperrzeit beendet.")
                self.dtmf_auth_status.setText("AUTH: wieder bereit")

        if not getattr(self,"dtmf_session_active",False):
            return
        if self.dtmf_last_digit is not None:
            if (now-self.dtmf_last_digit)*1000 >= self.dtmf_interdigit_ms.value():
                self._finish_dtmf_session("Timeout zwischen DTMF-Zeichen – unvollständiger Code verworfen")
                return
        if self.dtmf_session_started is not None:
            if now-self.dtmf_session_started >= self.dtmf_session_max_s.value():
                self._finish_dtmf_session("maximale DTMF-Session erreicht – Code verworfen")

    @staticmethod
    def _totp_secret_bytes(secret_b32):
        text="".join(ch for ch in str(secret_b32).upper().strip() if ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        if not text:
            return b""
        pad="="*((8-(len(text)%8))%8)
        return base64.b32decode(text+pad,casefold=True)

    def _generate_dtmf_totp_secret(self):
        if self.dtmf_totp_secret:
            answer=QMessageBox.warning(
                self,
                "DTMF-TOTP",
                "Es existiert bereits ein TOTP-Geheimnis.\n\n"
                "Wenn ein neues Geheimnis erzeugt wird, funktionieren die bisher "
                "in Google Authenticator, Aegis, 2FAS usw. gespeicherten Codes nicht mehr.\n\n"
                "Wirklich ein neues TOTP-Geheimnis erzeugen?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                self.log("DTMF-TOTP: Neuerzeugung abgebrochen – vorhandenes Geheimnis bleibt erhalten.")
                return

        self.dtmf_totp_secret=base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
        self.dtmf_totp_last_counter=-1
        self._refresh_dtmf_totp_uri()
        self.save_cfg()
        self.log("DTMF-TOTP: neues Geheimnis erzeugt.")
        QMessageBox.information(
            self,
            "DTMF-TOTP",
            "Neues TOTP-Geheimnis erzeugt.\n"
            "Die bisherige Authenticator-Einrichtung ist damit ungültig.\n"
            "Bitte die neue otpauth-URI in der Authenticator-App einrichten."
        )

    def _dtmf_totp_uri(self):
        from urllib.parse import quote
        if not self.dtmf_totp_secret:
            return ""
        issuer=self.dtmf_totp_label.text().strip() or "FunkGateway"
        account=self.dtmf_totp_account.text().strip() or "DTMF"
        label=f"{issuer}:{account}"
        return (
            "otpauth://totp/"+quote(label,safe="")+
            "?secret="+quote(self.dtmf_totp_secret,safe="")+
            "&issuer="+quote(issuer,safe="")+
            f"&digits={self.dtmf_totp_digits.value()}&period={self.dtmf_totp_period.value()}&algorithm=SHA1"
        )

    def _refresh_dtmf_totp_uri(self):
        self.dtmf_totp_secret_view.setText(self.dtmf_totp_secret)
        self.dtmf_totp_uri_view.setText(self._dtmf_totp_uri())

    def _copy_dtmf_totp_uri(self):
        uri=self._dtmf_totp_uri()
        if not uri:
            QMessageBox.warning(self,"DTMF-TOTP","Bitte zuerst ein TOTP-Geheimnis erzeugen.")
            return
        QApplication.clipboard().setText(uri)
        self.log("DTMF-TOTP: otpauth-URI in die Zwischenablage kopiert.")

    def _show_dtmf_totp_qr(self):
        uri=self._dtmf_totp_uri()
        if not uri:
            QMessageBox.warning(self,"DTMF-TOTP","Bitte zuerst ein TOTP-Geheimnis erzeugen.")
            return

        qrencode=shutil.which("qrencode")
        if not qrencode:
            QMessageBox.critical(
                self,
                "DTMF-TOTP",
                "Der QR-Code kann nicht erzeugt werden, weil 'qrencode' fehlt.\n\n"
                "Unter Ubuntu/Debian installieren mit:\n"
                "sudo apt install qrencode"
            )
            self.log("DTMF-TOTP: QR-Code nicht erzeugt – qrencode fehlt.")
            return

        try:
            qr_dir=CFG_DIR / "totp"
            qr_dir.mkdir(parents=True,exist_ok=True)
            qr_path=qr_dir / "funkgateway-totp-qr.png"
            subprocess.run(
                [qrencode,"-o",str(qr_path),"-s","8","-m","2",uri],
                check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                text=True,timeout=10
            )

            pix=QPixmap(str(qr_path))
            if pix.isNull():
                raise RuntimeError("QR-PNG konnte nicht geladen werden")

            dlg=QDialog(self)
            dlg.setWindowTitle("FunkGateway – TOTP QR-Code")
            layout=QVBoxLayout(dlg)
            info=QLabel(
                "Diesen QR-Code mit Google Authenticator, Aegis, 2FAS, "
                "Microsoft Authenticator oder einer anderen TOTP-App scannen."
            )
            info.setWordWrap(True)
            layout.addWidget(info)
            image_label=QLabel()
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setPixmap(pix)
            layout.addWidget(image_label)
            warn=QLabel(
                "Wichtig: Der QR-Code enthält das geheime TOTP-Schlüsselmaterial. "
                "Nicht weitergeben oder öffentlich speichern."
            )
            warn.setWordWrap(True)
            layout.addWidget(warn)
            buttons=QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dlg.reject)
            layout.addWidget(buttons)
            dlg.adjustSize()
            self.log("DTMF-TOTP: QR-Code angezeigt.")
            dlg.exec()
        except subprocess.CalledProcessError as e:
            err=(e.stderr or "").strip()
            self.log(f"DTMF-TOTP: QR-Code-Erzeugung fehlgeschlagen: {err or e}")
            QMessageBox.critical(self,"DTMF-TOTP",f"QR-Code konnte nicht erzeugt werden:\n{err or e}")
        except Exception as e:
            self.log(f"DTMF-TOTP: QR-Code-Anzeige fehlgeschlagen: {e}")
            QMessageBox.critical(self,"DTMF-TOTP",f"QR-Code konnte nicht angezeigt werden:\n{e}")

    def _totp_code_for_counter(self,counter):
        secret=self._totp_secret_bytes(self.dtmf_totp_secret)
        if not secret:
            return None
        digest=hmac.new(secret,struct.pack(">Q",int(counter)),hashlib.sha1).digest()
        off=digest[-1]&0x0F
        binary=((digest[off]&0x7F)<<24)|((digest[off+1]&0xFF)<<16)|((digest[off+2]&0xFF)<<8)|(digest[off+3]&0xFF)
        digits=self.dtmf_totp_digits.value()
        return str(binary%(10**digits)).zfill(digits)

    def _verify_dtmf_totp(self,code):
        code=str(code)
        if not self.dtmf_totp_secret or not code.isdigit() or len(code)!=self.dtmf_totp_digits.value():
            return False,None
        period=max(1,self.dtmf_totp_period.value())
        current=int(time.time()//period)
        offsets=[0]
        for i in range(1,self.dtmf_totp_window.value()+1):
            offsets.extend([-i,i])
        for off in offsets:
            counter=current+off
            expected=self._totp_code_for_counter(counter)
            if expected and hmac.compare_digest(expected,code):
                if counter<=self.dtmf_totp_last_counter:
                    return False,"replay"
                return True,counter
        return False,None

    def _set_dtmf_auth_pin_from_ui(self):
        pin=self.dtmf_auth_pin_edit.text().strip()
        if not pin.isdigit() or not (3 <= len(pin) <= 12):
            QMessageBox.warning(self,"DTMF-AUTH","Der PIN muss aus 3 bis 12 Ziffern bestehen.")
            return
        salt=secrets.token_hex(16)
        digest=hashlib.pbkdf2_hmac("sha256",pin.encode("utf-8"),bytes.fromhex(salt),120000)
        self.dtmf_auth_pin_salt=salt
        self.dtmf_auth_pin_hash=digest.hex()
        self.dtmf_auth_pin_edit.clear()
        self.dtmf_auth_fail_count=0
        self.dtmf_auth_locked_until=0.0
        self.dtmf_auth_active_until=0.0
        self.dtmf_auth_status.setText("AUTH: PIN gesetzt; noch nicht angemeldet")
        self.save_cfg()
        self.log("DTMF-AUTH: neuer PIN gespeichert (nicht im Klartext).")

    def _dtmf_auth_pin_ok(self,pin):
        if not self.dtmf_auth_pin_salt or not self.dtmf_auth_pin_hash:
            return False
        try:
            got=hashlib.pbkdf2_hmac(
                "sha256",str(pin).encode("utf-8"),
                bytes.fromhex(self.dtmf_auth_pin_salt),120000
            ).hex()
            return hmac.compare_digest(got,self.dtmf_auth_pin_hash)
        except Exception:
            return False

    def _dtmf_auth_is_active(self):
        if not self.dtmf_auth_enabled.isChecked():
            return True
        return bool(self.dtmf_auth_active_until and time.monotonic() < self.dtmf_auth_active_until)

    def _is_dtmf_auth_sequence(self,code):
        code=self._clean_dtmf_code(code)
        prefix=self._clean_dtmf_code(self.dtmf_auth_prefix.text())
        logout=self._clean_dtmf_code(self.dtmf_auth_logout_code.text())
        return bool((prefix and code.startswith(prefix)) or (logout and code==logout))

    def _dtmf_auth_radio_message(self,path,label):
        path=str(path or "").strip()
        if not path:
            return
        if not Path(path).is_file():
            self.log(f"DTMF-AUTH-Ansage '{label}' nicht gesendet: Datei fehlt: {path}")
            return
        delay=max(300,self.dtmf_release_ms.value()+100)
        QTimer.singleShot(delay,lambda p=path,l=label:self._send_dtmf_ack(p,l))

    def _handle_dtmf_auth_code(self,code,test_only=False):
        code=self._clean_dtmf_code(code)
        prefix=self._clean_dtmf_code(self.dtmf_auth_prefix.text())
        logout=self._clean_dtmf_code(self.dtmf_auth_logout_code.text())
        end=(self.dtmf_end_char.text().strip() or "#")[0].upper()

        if logout and code==logout:
            if test_only:
                self.log("DTMF-Test: AUTH würde beendet.")
                return True
            self.dtmf_auth_active_until=0.0
            self.dtmf_auth_expiry_logged=False
            self.dtmf_auth_status.setText("AUTH: beendet")
            self.log("DTMF-AUTH: manuell beendet.")
            return True

        if not prefix or not code.startswith(prefix) or not code.endswith(end):
            return False

        if test_only:
            self.log("DTMF-Test: AUTH-Sequenz erkannt; PIN wird im Test nicht geprüft.")
            return True

        now=time.monotonic()
        if self.dtmf_auth_locked_until and now < self.dtmf_auth_locked_until:
            rest=max(1,int(self.dtmf_auth_locked_until-now))
            self.log(f"DTMF-AUTH: Anmeldung während Sperrzeit abgewiesen ({rest} s Rest).")
            self.dtmf_auth_status.setText(f"AUTH: gesperrt – noch {rest} s")
            self._dtmf_auth_radio_message(self.dtmf_auth_failed_wav.text(),"AUTH fehlgeschlagen")
            return True

        method=self.dtmf_auth_method.currentData() or "pin"
        if method=="totp" and not self.dtmf_totp_secret:
            self.log("DTMF-AUTH: kein TOTP-Geheimnis konfiguriert – Anmeldung abgewiesen.")
            self.dtmf_auth_status.setText("AUTH: kein TOTP-Geheimnis")
            self._dtmf_auth_radio_message(self.dtmf_auth_failed_wav.text(),"AUTH fehlgeschlagen")
            return True
        if method=="pin" and not self.dtmf_auth_pin_hash:
            self.log("DTMF-AUTH: kein PIN konfiguriert – Anmeldung abgewiesen.")
            self.dtmf_auth_status.setText("AUTH: kein PIN konfiguriert")
            self._dtmf_auth_radio_message(self.dtmf_auth_failed_wav.text(),"AUTH fehlgeschlagen")
            return True

        auth_value=code[len(prefix):-1]
        verified=False
        replay=False
        accepted_counter=None
        if method=="totp":
            ok,info=self._verify_dtmf_totp(auth_value)
            verified=bool(ok)
            replay=(info=="replay")
            if verified:
                accepted_counter=int(info)
        else:
            verified=self._dtmf_auth_pin_ok(auth_value)

        if verified:
            if accepted_counter is not None:
                self.dtmf_totp_last_counter=accepted_counter
            self.dtmf_auth_fail_count=0
            self.dtmf_auth_locked_until=0.0
            self.dtmf_auth_active_until=now+self.dtmf_auth_valid_s.value()
            self.dtmf_auth_expiry_logged=False
            method_label="TOTP" if method=="totp" else "PIN"
            self.dtmf_auth_status.setText(f"AUTH: {method_label} erfolgreich – {self.dtmf_auth_valid_s.value()} s")
            self.log(f"DTMF-AUTH ({method_label}): erfolgreich – Freigabe für {self.dtmf_auth_valid_s.value()} s.")
            self._dtmf_auth_radio_message(self.dtmf_auth_success_wav.text(),"AUTH erfolgreich")
            self.save_cfg()
            return True

        self.dtmf_auth_fail_count += 1
        if replay:
            self.log("DTMF-AUTH (TOTP): bereits benutzter Zeitschritt – Replay abgewiesen.")
            self.dtmf_auth_status.setText("AUTH: TOTP bereits benutzt")
        else:
            self.log(f"DTMF-AUTH ({'TOTP' if method=='totp' else 'PIN'}): Anmeldung fehlgeschlagen.")
        if self.dtmf_auth_fail_count >= self.dtmf_auth_max_attempts.value():
            self.dtmf_auth_locked_until=now+self.dtmf_auth_lockout_s.value()
            self.dtmf_auth_fail_count=0
            self.dtmf_auth_status.setText(f"AUTH: {self.dtmf_auth_lockout_s.value()} s gesperrt")
            self.log(f"DTMF-AUTH: zu viele Fehlversuche – {self.dtmf_auth_lockout_s.value()} s gesperrt.")
        else:
            self.dtmf_auth_status.setText("AUTH: Anmeldung fehlgeschlagen")
        self._dtmf_auth_radio_message(self.dtmf_auth_failed_wav.text(),"AUTH fehlgeschlagen")
        return True

    def _dtmf_auth_required_for_fixed(self,label):
        mapping={
            "Papagei EIN":self.dtmf_auth_req_parrot,
            "VoIP-Betrieb":self.dtmf_auth_req_voip,
            "TeamSpeak MUTE":self.dtmf_auth_req_ts_mute,
            "TeamSpeak UNMUTE":self.dtmf_auth_req_ts_unmute,
            "TeamSpeak DEAF":self.dtmf_auth_req_ts_deaf,
            "TeamSpeak UNDEAF":self.dtmf_auth_req_ts_undeaf,
            "Mumble MUTE":self.dtmf_auth_req_mumble_mute,
            "Mumble UNMUTE":self.dtmf_auth_req_mumble_unmute,
            "Mumble DEAF":self.dtmf_auth_req_mumble_deaf,
            "Mumble UNDEAF":self.dtmf_auth_req_mumble_undeaf,
        }
        cb=mapping.get(label)
        return bool(cb and cb.isChecked())

    def _deny_dtmf_for_auth(self,code,label):
        self.log(f"DTMF-Code {code} → {label}: AUTH erforderlich – keine Aktion.")
        self.dtmf_status.setText(f"DTMF: AUTH erforderlich für {label}")
        self.dtmf_auth_status.setText("AUTH: erforderlich")
        self._dtmf_auth_radio_message(self.dtmf_auth_required_wav.text(),"AUTH erforderlich")
        return False

    def _dtmf_fixed_actions(self):
        return [
            (self._clean_dtmf_code(self.dtmf_code_parrot_on.text()),"Papagei EIN",lambda:self.parrot_enabled.setChecked(True),"parrot"),
            (self._clean_dtmf_code(self.dtmf_code_voip_on.text()),"VoIP-Betrieb",lambda:self.parrot_enabled.setChecked(False),"voip"),
            (self._clean_dtmf_code(self.dtmf_code_ts_mute.text()),"TeamSpeak MUTE",lambda:self._dtmf_ts_mute(True),"default"),
            (self._clean_dtmf_code(self.dtmf_code_ts_unmute.text()),"TeamSpeak UNMUTE",lambda:self._dtmf_ts_mute(False),"default"),
            (self._clean_dtmf_code(self.dtmf_code_ts_deaf.text()),"TeamSpeak DEAF",lambda:self._dtmf_ts_deaf(True),"default"),
            (self._clean_dtmf_code(self.dtmf_code_ts_undeaf.text()),"TeamSpeak UNDEAF",lambda:self._dtmf_ts_deaf(False),"default"),
            (self._clean_dtmf_code(self.dtmf_code_mumble_mute.text()),"Mumble MUTE",lambda:self._dtmf_mumble_mute(True),"default"),
            (self._clean_dtmf_code(self.dtmf_code_mumble_unmute.text()),"Mumble UNMUTE",lambda:self._dtmf_mumble_mute(False),"default"),
            (self._clean_dtmf_code(self.dtmf_code_mumble_deaf.text()),"Mumble DEAF",lambda:self._dtmf_mumble_deaf(True),"default"),
            (self._clean_dtmf_code(self.dtmf_code_mumble_undeaf.text()),"Mumble UNDEAF",lambda:self._dtmf_mumble_deaf(False),"default"),
        ]

    def _execute_dtmf_code(self,code,test_only=False):
        code=self._clean_dtmf_code(code)
        if not code:
            self.log("DTMF: leerer Code – keine Aktion.")
            return False

        if self.dtmf_auth_enabled.isChecked() and self._is_dtmf_auth_sequence(code):
            return self._handle_dtmf_auth_code(code,test_only=test_only)

        matches=[]
        for configured,label,func,ack_kind in self._dtmf_fixed_actions():
            if configured and configured == code:
                matches.append((label,func,ack_kind,self._dtmf_auth_required_for_fixed(label)))

        for i,(edit,combo) in enumerate(self.dtmf_ts_room_rows,1):
            configured=self._clean_dtmf_code(edit.text())
            cid=combo.currentData()
            if configured and configured == code and cid is not None:
                name=combo.currentText().split("  (CID",1)[0]
                matches.append((f"TeamSpeak Raum {name}",lambda cid=int(cid),name=name:self._dtmf_move_ts_room(cid,name),"default",self.dtmf_ts_room_auth[i-1].isChecked()))

        for i,(edit,combo) in enumerate(self.dtmf_mumble_room_rows,1):
            configured=self._clean_dtmf_code(edit.text())
            cid=combo.currentData()
            if configured and configured == code and cid is not None:
                name=combo.currentText().split("  (CID",1)[0]
                matches.append((f"Mumble Raum {name}",lambda cid=int(cid),name=name:self._dtmf_move_mumble_room(cid,name),"default",self.dtmf_mumble_room_auth[i-1].isChecked()))

        if not matches:
            self.log(f"DTMF-Code {code}: unbekannt – keine Aktion.")
            self.dtmf_status.setText(f"DTMF: unbekannter Code {code}")
            return False
        if len(matches) > 1:
            labels=", ".join(x[0] for x in matches)
            self.log(f"DTMF-Code {code}: mehrdeutig ({labels}) – aus Sicherheitsgründen keine Aktion.")
            self.dtmf_status.setText(f"DTMF: Code {code} ist mehrfach vergeben")
            return False

        label,func,ack_kind,requires_auth=matches[0]
        if test_only:
            auth_txt=" / AUTH erforderlich" if requires_auth and self.dtmf_auth_enabled.isChecked() else ""
            self.log(f"DTMF-Test {code}: würde ausführen → {label}{auth_txt}")
            self.dtmf_status.setText(f"DTMF-Test: {code} → {label}{auth_txt}")
            return True
        if self.dtmf_auth_enabled.isChecked() and requires_auth and not self._dtmf_auth_is_active():
            return self._deny_dtmf_for_auth(code,label)
        try:
            func()
            self.log(f"DTMF-Code {code} → {label}")
            self.dtmf_status.setText(f"DTMF: {code} → {label}")
            self.save_cfg()
            self._schedule_dtmf_ack(label,ack_kind)
            return True
        except Exception as e:
            self.log(f"DTMF-Code {code}: Aktion '{label}' fehlgeschlagen: {e}")
            self.dtmf_status.setText(f"DTMF-Fehler: {label}: {e}")
            return False

    def _dtmf_ack_path(self,kind):
        if kind=="parrot":
            return self.dtmf_ack_parrot_wav.text().strip()
        if kind=="voip":
            return self.dtmf_ack_voip_wav.text().strip()
        return self.dtmf_ack_default_wav.text().strip()

    def _schedule_dtmf_ack(self,label,kind):
        if not self.dtmf_ack_enabled.isChecked():
            return
        path=self._dtmf_ack_path(kind)
        if not path:
            self.log(f"DTMF-Vollzugsmeldung für '{label}' nicht gesendet: keine WAV hinterlegt.")
            return
        if not Path(path).is_file():
            self.log(f"DTMF-Vollzugsmeldung für '{label}' nicht gesendet: Datei fehlt: {path}")
            return

        generation=None
        if kind in ("parrot","voip"):
            # Mode changes supersede older pending mode confirmations.
            self.dtmf_mode_ack_generation += 1
            generation=self.dtmf_mode_ack_generation
            self.dtmf_mode_ack_pending=True
            if kind=="parrot":
                self._abort_parrot_recording_for_dtmf_ack()

        delay=max(300,self.dtmf_release_ms.value()+100)
        self.log(f"DTMF-Vollzugsmeldung vorgemerkt: {label} in {delay} ms.")
        QTimer.singleShot(
            delay,
            lambda p=path,l=label,k=kind,g=generation:self._send_dtmf_ack(p,l,k,g)
        )

    def _send_dtmf_ack(self,path,label,kind=None,generation=None):
        if kind in ("parrot","voip") and generation != self.dtmf_mode_ack_generation:
            self.dtmf_ack_waiting_labels.discard(label)
            self.log(f"DTMF-Vollzugsmeldung '{label}' verworfen: neuerer Betriebsart-Befehl liegt vor.")
            return
        if self.protection_muted:
            if kind in ("parrot","voip") and generation == self.dtmf_mode_ack_generation:
                self.dtmf_mode_ack_pending=False
            self.log(f"DTMF-Vollzugsmeldung '{label}' entfällt: Gateway-Schutz ist aktiv.")
            return
        # Wait only on real live activity.  rx_was_active is intentionally not
        # used here because it can remain sticky after a control transmission.
        if kind in ("parrot","voip") and generation == self.dtmf_mode_ack_generation:
            # A mode confirmation has priority over a Papagei cycle.  A stale
            # recording must never postpone "Papagei aktiv"/"Gateway aktiv".
            if getattr(self,"parrot_recording",False) or getattr(self,"parrot_guard_buffering",False):
                self._abort_parrot_recording_for_dtmf_ack()

        busy=bool(
            self.tx
            or self.outgoing_audio_active
            or self.rx_active_since is not None
            or getattr(self,"dtmf_control_rx_active",False)
            or getattr(self,"dtmf_session_active",False)
            or getattr(self,"return_guard_candidate",False)
            or (
                kind not in ("parrot","voip")
                and (
                    getattr(self,"parrot_recording",False)
                    or getattr(self,"parrot_cycle_active",False)
                )
            )
        )
        if busy:
            if label not in self.dtmf_ack_waiting_labels:
                self.dtmf_ack_waiting_labels.add(label)
                self.log(f"DTMF-Vollzugsmeldung '{label}' wartet auf Funkende/freie Aussendung.")
            QTimer.singleShot(
                250,
                lambda p=path,l=label,k=kind,g=generation:self._send_dtmf_ack(p,l,k,g)
            )
            return

        if label in self.dtmf_ack_waiting_labels:
            self.dtmf_ack_waiting_labels.discard(label)
            self.log(f"DTMF-Vollzugsmeldung '{label}': Kanal frei – sende Bestätigung.")
        try:
            self.outgoing_audio_active=True
            if hasattr(self,"parrot_enabled") and self.parrot_enabled.isChecked():
                with self.parrot_capture_lock:
                    self.parrot_prebuffer.clear()
                self.active_tx_kind="parrot"
            else:
                self.active_tx_kind="protection"
            self.set_ptt(True)
            self.log(f"DTMF-Vollzugsmeldung: PTT EIN → {label}")
            lead=max(0,self.parrot_lead_ms.value() if hasattr(self,"parrot_lead_ms") else 500)
            ack_proc={"proc":None,"finished":False}

            def finish():
                if ack_proc["finished"]:
                    return
                ack_proc["finished"]=True
                try:
                    if self.tx:
                        self.set_ptt(False)
                finally:
                    self.outgoing_audio_active=False
                    if hasattr(self,"parrot_enabled") and self.parrot_enabled.isChecked():
                        with self.parrot_capture_lock:
                            self.parrot_prebuffer.clear()
                    if kind in ("parrot","voip") and generation == self.dtmf_mode_ack_generation:
                        self.dtmf_mode_ack_pending=False
                    self.log(f"DTMF-Vollzugsmeldung beendet: {label}")

            def wait_for_audio_end():
                proc=ack_proc["proc"]
                if proc is None:
                    QTimer.singleShot(100,wait_for_audio_end)
                    return

                rc=proc.poll()
                if rc is None:
                    QTimer.singleShot(100,wait_for_audio_end)
                    return

                if rc == 0:
                    self.log(f"DTMF-Vollzugsmeldung WAV beendet: {label}")
                else:
                    self.log(f"DTMF-Vollzugsmeldung WAV-Player beendet mit Exit-Code {rc}: {label}")

                # paplay may finish before all audio buffered in the virtual
                # PipeWire/PulseAudio path has physically left the RF output.
                # Keep PTT keyed for a configurable drain tail.
                tail=max(0,self.dtmf_ack_tail_ms.value() if hasattr(self,"dtmf_ack_tail_ms") else 2500)
                self.log(f"DTMF-Vollzugsmeldung: WAV-Player fertig – PTT-Nachlauf {tail} ms.")
                QTimer.singleShot(tail,finish)

            def play():
                try:
                    ack_proc["proc"]=self.play_to_virtual(path,kind="dtmf_ack")
                    self.log(f"DTMF-Vollzugsmeldung Wiedergabe gestartet: {label}")
                    QTimer.singleShot(100,wait_for_audio_end)
                except Exception as e:
                    self.log(f"DTMF-Vollzugsmeldung '{label}' fehlgeschlagen: {e}")
                    QTimer.singleShot(500,finish)

            QTimer.singleShot(lead,play)
        except Exception as e:
            self.outgoing_audio_active=False
            if self.tx:
                self.set_ptt(False)
            if kind in ("parrot","voip") and generation == self.dtmf_mode_ack_generation:
                self.dtmf_mode_ack_pending=False
            self.log(f"DTMF-Vollzugsmeldung '{label}' konnte nicht gestartet werden: {e}")

    def _dtmf_ts_mute(self,enabled):
        if not self.ts_enabled.isChecked():
            raise RuntimeError("TeamSpeak-Modul ist ausgeschaltet")
        self._configure_teamspeak()
        self.ts_client.set_input_muted(bool(enabled))

    def _dtmf_ts_deaf(self,enabled):
        if not self.ts_enabled.isChecked():
            raise RuntimeError("TeamSpeak-Modul ist ausgeschaltet")
        self._configure_teamspeak()
        self.ts_client.set_output_muted(bool(enabled))

    def _dtmf_mumble_mute(self,enabled):
        if not self.mumble_enabled.isChecked():
            raise RuntimeError("Mumble-Modul ist ausgeschaltet")
        if not self.mumble_local.running():
            raise RuntimeError("Mumble-Client ist nicht gestartet")
        self.mumble_local.set_muted(bool(enabled))

    def _dtmf_mumble_deaf(self,enabled):
        if not self.mumble_enabled.isChecked():
            raise RuntimeError("Mumble-Modul ist ausgeschaltet")
        if not self.mumble_local.running():
            raise RuntimeError("Mumble-Client ist nicht gestartet")
        self.mumble_local.set_deaf(bool(enabled))

    def _dtmf_move_ts_room(self,cid,name):
        if not self.ts_enabled.isChecked():
            raise RuntimeError("TeamSpeak-Modul ist ausgeschaltet")
        self._configure_teamspeak()
        self.ts_client.move_self(int(cid))
        self.log(f"DTMF: TeamSpeak Gateway in '{name}' (CID {cid}) verschoben.")

    def _dtmf_move_mumble_room(self,cid,name):
        if not self.mumble_enabled.isChecked():
            raise RuntimeError("Mumble-Modul ist ausgeschaltet")
        mode=self.mumble_ice_mode.currentData()
        if mode == "bridge":
            raise RuntimeError("Mumble-Bridge erlaubt absichtlich keine beliebigen DTMF-Raumwechsel")
        if mode not in ("direct","ssh"):
            raise RuntimeError("Für freie Mumble-Raumwechsel muss direktes Ice oder Ice über SSH eingerichtet sein")
        read=self.mumble_read_secret.text()
        write=self.mumble_write_secret.text()
        if not read or not write:
            raise RuntimeError("Mumble Ice Read- und Write-Secret werden für den Raumwechsel benötigt")
        host,port=self._mumble_ice_endpoint()
        gateway=self._mumble_gateway_name_value()
        self._begin_mumble_room_change_guard(8.0)
        old=self.mumble_ice.move_gateway(
            host,port,self.mumble_slice.text(),read,write,gateway,int(cid),
            self.mumble_ice_server_id.value()
        )
        self.log(f"DTMF: Mumble Gateway verschoben: CID {old} → {cid} ({name}).")

    @staticmethod
    def _fill_dtmf_room_combos(rows,channels,system):
        for edit,combo in rows:
            old=combo.currentData()
            old_text=combo.currentText()
            combo.clear()
            found=-1
            for item in channels:
                if system=="ts":
                    cid,name=item
                    text=f"{name}  (CID {cid})"
                else:
                    cid,name,parent=item
                    text=f"{name}  (CID {cid}, Parent {parent})"
                combo.addItem(text,int(cid))
                if old is not None and int(old)==int(cid):
                    found=combo.count()-1
            if found >= 0:
                combo.setCurrentIndex(found)
            elif old is not None:
                combo.addItem(old_text or f"Gespeicherter Raum CID {old}",int(old))
                combo.setCurrentIndex(combo.count()-1)
            elif not channels:
                combo.addItem(f"Keine {system.upper()}-Räume geladen",None)

    def refresh_dtmf_room_lists(self):
        # TeamSpeak
        try:
            self._configure_teamspeak()
            ts_channels=self.ts_client.channels()
            self._fill_dtmf_room_combos(self.dtmf_ts_room_rows,ts_channels,"ts")
            self.log(f"DTMF: TeamSpeak-Raumliste geladen ({len(ts_channels)} Räume).")
        except Exception as e:
            self.log(f"DTMF: TeamSpeak-Raumliste nicht verfügbar: {e}")

        # Mumble
        try:
            mode=self.mumble_ice_mode.currentData()
            if mode == "bridge":
                self.log("DTMF: Mumble-Bridge – freie Raumliste absichtlich nicht verfügbar.")
                self._fill_dtmf_room_combos(self.dtmf_mumble_room_rows,[],"mumble")
                return
            if mode not in ("direct","ssh"):
                raise RuntimeError("direktes Ice/SSH ist nicht eingerichtet")
            read=self.mumble_read_secret.text()
            if not read:
                raise RuntimeError("Ice Read-Secret fehlt")
            host,port=self._mumble_ice_endpoint()
            channels=self.mumble_ice.channels(
                host,port,self.mumble_slice.text(),read,self.mumble_ice_server_id.value()
            )
            self.mumble_channels=channels
            self._fill_dtmf_room_combos(self.dtmf_mumble_room_rows,channels,"mumble")
            self.log(f"DTMF: Mumble-Raumliste geladen ({len(channels)} Räume).")
        except Exception as e:
            self.log(f"DTMF: Mumble-Raumliste nicht verfügbar: {e}")

    def _dtmf_print_rows(self):
        """Return all configured DTMF entries in a stable printable order."""
        rows=[
            ("Betriebsart","Papagei EIN",self.dtmf_code_parrot_on.text(),""),
            ("Betriebsart","Normaler VoIP-Betrieb",self.dtmf_code_voip_on.text(),""),
            ("TeamSpeak","Mikrofon MUTE",self.dtmf_code_ts_mute.text(),"lokaler Gateway-Client"),
            ("TeamSpeak","Mikrofon UNMUTE",self.dtmf_code_ts_unmute.text(),"lokaler Gateway-Client"),
            ("TeamSpeak","DEAF / Ausgabe stumm",self.dtmf_code_ts_deaf.text(),"lokaler Gateway-Client"),
            ("TeamSpeak","UNDEAF",self.dtmf_code_ts_undeaf.text(),"lokaler Gateway-Client"),
            ("Mumble","MUTE",self.dtmf_code_mumble_mute.text(),"lokaler Gateway-Client"),
            ("Mumble","UNMUTE",self.dtmf_code_mumble_unmute.text(),"lokaler Gateway-Client"),
            ("Mumble","DEAF",self.dtmf_code_mumble_deaf.text(),"lokaler Gateway-Client"),
            ("Mumble","UNDEAF",self.dtmf_code_mumble_undeaf.text(),"lokaler Gateway-Client"),
        ]

        for i,(edit,combo) in enumerate(self.dtmf_ts_room_rows,1):
            target=combo.currentText().strip()
            if combo.currentData() is not None:
                target=f"{target}"
            elif not target or "laden" in target.lower() or "keine " in target.lower():
                target="kein Ziel gewählt"
            rows.append(("TeamSpeak Raumwechsel",f"Raumplatz {i}",edit.text(),target))

        for i,(edit,combo) in enumerate(self.dtmf_mumble_room_rows,1):
            target=combo.currentText().strip()
            if combo.currentData() is not None:
                target=f"{target}"
            elif not target or "laden" in target.lower() or "keine " in target.lower():
                target="kein Ziel gewählt"
            rows.append(("Mumble Raumwechsel",f"Raumplatz {i}",edit.text(),target))

        return rows

    def export_dtmf_codes_pdf(self):
        """Create a compact A4 sheet with every currently configured DTMF code."""
        default_name=f"FunkGateway-DTMF-Codes-{VERSION}.pdf"
        path,_=QFileDialog.getSaveFileName(
            self,
            "DTMF-Code-Liste als PDF speichern",
            str(Path.home()/default_name),
            "PDF-Datei (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        start=html.escape((self.dtmf_start_char.text().strip() or "*")[:1])
        end=html.escape((self.dtmf_end_char.text().strip() or "#")[:1])
        generated=datetime.now().strftime("%d.%m.%Y %H:%M")

        rows_html=[]
        for group,action,code,target in self._dtmf_print_rows():
            cleaned=self._clean_dtmf_code(code)
            shown=html.escape(cleaned) if cleaned else "<i>nicht belegt</i>"
            target_html=html.escape(str(target)) if target else ""
            rows_html.append(
                "<tr>"
                f"<td>{html.escape(group)}</td>"
                f"<td>{html.escape(action)}</td>"
                f"<td class='code'>{shown}</td>"
                f"<td>{target_html}</td>"
                "</tr>"
            )

        doc_html=f"""
        <html>
        <head>
        <meta charset="utf-8">
        <style>
          body {{ font-family: sans-serif; font-size: 9.5pt; color: #111; }}
          h1 {{ font-size: 18pt; margin-bottom: 2px; }}
          h2 {{ font-size: 11pt; margin-top: 0; color: #444; }}
          .meta {{ margin: 8px 0 12px 0; padding: 7px; background: #f1f1f1; }}
          table {{ width: 100%; border-collapse: collapse; }}
          th {{ background: #dedede; font-weight: bold; padding: 5px; border: 1px solid #777; }}
          td {{ padding: 5px; border: 1px solid #999; vertical-align: top; }}
          td.code {{ font-family: monospace; font-size: 11pt; font-weight: bold; text-align: center; white-space: nowrap; }}
          .small {{ font-size: 8pt; color: #555; margin-top: 10px; }}
        </style>
        </head>
        <body>
          <h1>FunkGateway - DTMF-Codeliste</h1>
          <h2>Version {html.escape(VERSION)}</h2>
          <div class="meta">
            <b>Startzeichen:</b> {start}
            &nbsp;&nbsp;&nbsp;
            <b>Abschlusszeichen:</b> {end}
            &nbsp;&nbsp;&nbsp;
            <b>Zeichen-Timeout:</b> {self.dtmf_interdigit_ms.value()} ms
            <br>
            <b>DTMF-Steuerung:</b> {"aktiv" if self.dtmf_enabled.isChecked() else "deaktiviert"}
            &nbsp;&nbsp;&nbsp;
            <b>DTMF zu VoIP unterdrücken:</b> {"ja" if self.dtmf_suppress_voip.isChecked() else "nein"}
          </div>

          <table>
            <tr>
              <th>Bereich</th>
              <th>Funktion</th>
              <th>DTMF-Code</th>
              <th>Ziel / Hinweis</th>
            </tr>
            {''.join(rows_html)}
          </table>

          <p class="small">
            Erstellt am {generated}. Die Liste entspricht den aktuell in FunkGateway
            eingestellten Codes. Nicht belegte Raumplätze werden ausdrücklich angezeigt.
          </p>
        </body>
        </html>
        """

        try:
            printer=QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(path)
            printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            printer.setPageMargins(QMarginsF(10,10,10,10),QPageLayout.Unit.Millimeter)

            doc=QTextDocument()
            doc.setDocumentMargin(8)
            doc.setHtml(doc_html)
            doc.print_(printer)

            if not Path(path).exists() or Path(path).stat().st_size < 500:
                raise RuntimeError("PDF-Datei wurde nicht korrekt erzeugt")

            self.log(f"DTMF-Codeliste als PDF gespeichert: {path}")
            QMessageBox.information(
                self,
                "DTMF-Codeliste",
                f"Druckfertige DTMF-Code-Liste gespeichert:\n{path}"
            )
        except Exception as e:
            self.log(f"DTMF-PDF konnte nicht erstellt werden: {e}")
            QMessageBox.critical(
                self,
                "DTMF-Codeliste",
                f"Die PDF konnte nicht erstellt werden:\n{e}"
            )

    def _save_dtmf_room_rows(self,rows):
        result=[]
        for edit,combo in rows:
            result.append({
                "code":self._clean_dtmf_code(edit.text()),
                "cid":combo.currentData(),
                "name":combo.currentText(),
            })
        return result

    @staticmethod
    def _load_dtmf_room_rows(saved,rows,label):
        if not isinstance(saved,list):
            return
        for item,(edit,combo) in zip(saved,rows):
            if not isinstance(item,dict):
                continue
            edit.setText(str(item.get("code","")))
            cid=item.get("cid")
            name=str(item.get("name","")).strip()
            if cid is not None:
                combo.clear()
                combo.addItem(name or f"Gespeicherter {label}-Raum CID {cid}",int(cid))

    def mute_gateway(self, reason, announce_path=""):
        if self.protection_muted and self.protection_reason == reason:
            return
        self.protection_muted=True; self.protection_reason=reason; self.protection_rx_free_since=None
        self.ts_commander_wanted=False
        self._refresh_rx_forward_mute()
        self._set_tx_forward_muted(True)
        if self.ptt and not self.protection_announcement_busy:
            self.set_ptt(False)
        self._set_gateway_protection_display()
        self._set_big_rx_status(bool(self.rx_was_active))
        self.log(f"Gateway-Schutz aktiv: {reason}. Funk->Computer und normale PTT-Weitergabe gemutet.")
        if announce_path:
            QTimer.singleShot(150,lambda p=announce_path,r=reason:self.play_protection_announcement(p,r))

    def unmute_gateway(self, source="automatisch"):
        if not self.protection_muted:
            return
        old=self.protection_reason
        self.protection_muted=False; self.protection_reason=""; self.protection_unmute_due=None; self.protection_waiting_for_rx_free=False; self.protection_rx_free_since=None
        self._refresh_rx_forward_mute()
        self._set_tx_forward_muted(False)
        self.ts_commander_wanted=bool(self.rx_was_active)
        self._set_gateway_protection_display()
        self._set_big_rx_status(bool(self.rx_was_active))
        self.log(f"Gateway wieder aktiviert ({source}); vorheriger Grund: {old}.")
        if self.protection_auto_move_active and self.protect_return_channel.isChecked() and self.protection_previous_ts_channel:
            try:
                self._configure_teamspeak(); self.ts_client.move_self(self.protection_previous_ts_channel[0])
                self.log(f"TeamSpeak: zurück in vorherigen Channel '{self.protection_previous_ts_channel[1]}' verschoben.")
            except Exception as e:
                self.log(f"TeamSpeak Rückkehr in vorherigen Channel fehlgeschlagen: {e}")
        self.protection_auto_move_active=False; self.protection_previous_ts_channel=None
        self._return_mumble_after_protection()
        if self.protect_restore_wav.text().strip():
            QTimer.singleShot(150,lambda:self.play_protection_announcement(self.protect_restore_wav.text(),"Gateway wieder aktiviert"))

    def refresh_protection_channels(self):
        try:
            self._configure_teamspeak(); channels=self.ts_client.channels(); current_cid,current_name=self.ts_client.current_channel()
            self.protect_room_combo.clear(); idx=-1
            for cid,name in channels:
                self.protect_room_combo.addItem(f"{name}  (CID {cid})",cid)
                if cid == current_cid: idx=self.protect_room_combo.count()-1
            if idx >= 0: self.protect_room_combo.setCurrentIndex(idx)
            if not channels: self.protect_room_combo.addItem("Keine sichtbaren Channels gefunden",None)
            self.update_disturbance_room_status()
        except Exception as e:
            self.show_copyable_error("Störungsraum / TeamSpeak",str(e))

    def update_disturbance_room_status(self):
        try:
            self._configure_teamspeak(); key,name=self.ts_client.server_identity(); self.protection_last_ts_server_key=key
            room=self.protection_ts_rooms.get(key)
            if room:
                self.protect_room_status.setText(f"Server: {name} – Störungsraum: {room.get('name','?')} (CID {room.get('cid','?')})")
            else:
                self.protect_room_status.setText(f"Server: {name} – kein Störungsraum definiert")
        except Exception as e:
            self.protect_room_status.setText(f"Störungsraum: TeamSpeak nicht verfügbar ({e})")

    def set_selected_disturbance_room(self):
        cid=self.protect_room_combo.currentData()
        if cid is None:
            QMessageBox.information(self,"Störungsraum","Bitte zuerst einen TeamSpeak-Channel auswählen."); return
        try:
            self._configure_teamspeak(); key,server_name=self.ts_client.server_identity()
            name=self.protect_room_combo.currentText().rsplit("  (CID",1)[0]
            self.protection_ts_rooms[key]={"cid":int(cid),"name":name,"server_name":server_name}
            self.save_cfg(); self.update_disturbance_room_status()
            self.log(f"Störungsraum gespeichert: {server_name} -> {name} (CID {cid}).")
        except Exception as e: self.show_copyable_error("Störungsraum",str(e))

    def clear_disturbance_room(self):
        try:
            self._configure_teamspeak(); key,server_name=self.ts_client.server_identity()
            self.protection_ts_rooms.pop(key,None); self.save_cfg(); self.update_disturbance_room_status()
            self.log(f"Störungsraum-Zuordnung für {server_name} gelöscht.")
        except Exception as e: self.show_copyable_error("Störungsraum",str(e))

    def _auto_move_to_disturbance_room(self):
        if not self.protect_move_to_room.isChecked() or not self.ts_enabled.isChecked(): return False
        try:
            self._configure_teamspeak(); key,server_name=self.ts_client.server_identity(); room=self.protection_ts_rooms.get(key)
            if not room:
                self.log(f"Dauer-RX: kein Störungsraum für {server_name} definiert; Gateway bleibt im aktuellen Channel."); return False
            cid,name=self.ts_client.current_channel(); self.protection_previous_ts_channel=(cid,name)
            if cid != int(room["cid"]):
                self.ts_client.move_self(int(room["cid"])); self.log(f"Dauer-RX: Gateway automatisch in Störungsraum '{room['name']}' verschoben.")
            self.protection_auto_move_active=True
            return True
        except Exception as e:
            self.log(f"Dauer-RX: automatisches Verschieben in Störungsraum fehlgeschlagen: {e}")
            return False

    def _protection_tick(self, now):
        # Dauer-RX
        if self.protect_rx_enabled.isChecked() and self.rx_active_since and not self.protection_muted:
            if now-self.rx_active_since >= self.protect_rx_seconds.value():
                self.mute_gateway("Dauer-RX",self.protect_mute_wav.text())
                ts_moved=self._auto_move_to_disturbance_room()
                mumble_moved=self._auto_move_to_mumble_disturbance_room()
                if ts_moved or mumble_moved:
                    self.protection_last_room_announcement=now
                    if self.protect_room_wav.text().strip():
                        self.play_protection_announcement(
                            self.protect_room_wav.text(),
                            "Gateway im Störungsraum"
                        )
                if self.protect_auto_unmute.isChecked():
                    self.protection_unmute_due=now+self.protect_unmute_seconds.value()
                    self.protection_waiting_for_rx_free=self.protect_require_rx_free.isChecked()
        # Auto-Unmute.  A single short RX-free pulse is not sufficient.
        # In safe mode RX must stay continuously free for the configured time
        # and the measured level must remain below the dedicated protection
        # free threshold. Any new RX activity or excessive level resets the timer.
        if self.protection_muted and self.protection_reason in ("Dauer-RX","Selbstrücklauf") and self.protection_unmute_due and now >= self.protection_unmute_due:
            if not self.protection_waiting_for_rx_free:
                self.unmute_gateway("Dauer-RX-Automatik")
            else:
                free_ok=(not self.rx_was_active and self.rx_last_db <= self.protect_free_threshold.value())
                if free_ok:
                    if self.protection_rx_free_since is None:
                        self.protection_rx_free_since=now
                        self._set_big_rx_status(False)
                        if self.diagnostic_mode.isChecked():
                            self.log(f"Schutzfreigabe: RX-Frei-Timer gestartet ({self.rx_last_db:.1f} dBFS).")
                    if now-self.protection_rx_free_since >= self.protect_free_seconds.value():
                        self.log(f"Schutzfreigabe: Funk-RX {self.protect_free_seconds.value()} s stabil frei; Gateway wird wieder aktiviert.")
                        self.unmute_gateway("Dauer-RX-Automatik")
                else:
                    if self.protection_rx_free_since is not None and self.diagnostic_mode.isChecked():
                        self.log("Schutzfreigabe: Frei-Timer zurückgesetzt – RX wieder aktiv oder Pegel zu hoch.")
                    self.protection_rx_free_since=None
                    self._set_big_rx_status(bool(self.rx_was_active))
        # Repeat room announcement for automatically entered TeamSpeak/Mumble rooms.
        if (self.protection_muted and self.protection_reason == "Dauer-RX"
                and (self.protection_auto_move_active or self.protection_mumble_auto_move_active)
                and self.protect_room_repeat.isChecked()
                and self.protection_last_room_announcement
                and now-self.protection_last_room_announcement >= self.protect_room_repeat_min.value()*60):
            self.play_protection_announcement(self.protect_room_wav.text(),"Gateway im Störungsraum")
            self.protection_last_room_announcement=now

        # TeamSpeak-Störungsraum.  Poll slowly so ClientQuery is not flooded.
        if self.protect_room_enabled.isChecked() and self.ts_enabled.isChecked() and now-self.protection_last_ts_check >= 2.0:
            self.protection_last_ts_check=now
            try:
                self._configure_teamspeak(); key,server_name=self.ts_client.server_identity(); room=self.protection_ts_rooms.get(key)
                cid,cname=self.ts_client.current_channel()
                in_room=bool(room and cid == int(room.get("cid",-1)))
                if in_room and not self.protection_auto_move_active:
                    if not self.protection_muted or self.protection_reason != "Störungsraum":
                        self.mute_gateway("Störungsraum",self.protect_room_wav.text())
                        self.protection_last_room_announcement=now
                    elif self.protect_room_repeat.isChecked() and now-self.protection_last_room_announcement >= self.protect_room_repeat_min.value()*60:
                        self.play_protection_announcement(self.protect_room_wav.text(),"Gateway im Störungsraum")
                        self.protection_last_room_announcement=now
                elif self.protection_muted and self.protection_reason == "Störungsraum":
                    self.unmute_gateway("Störungsraum verlassen")
            except Exception as e:
                if self.diagnostic_mode.isChecked(): self.log(f"Störungsraum-Prüfung nicht möglich: {e}")

    def show_copyable_error(self,title,text):
        """Show an error dialog whose complete text can be copied easily."""
        msg=QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle(title)
        msg.setText(str(text))
        msg.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        copy_btn=msg.addButton("Fehler kopieren", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Ok)
        msg.exec()
        if msg.clickedButton() is copy_btn:
            QApplication.clipboard().setText(str(text))

    def copy_teamspeak_status(self):
        text=self.ts_status.text()
        channel=self.ts_channel.text() if hasattr(self,"ts_channel") else ""
        speaker=self.ts_speaker.text()
        QApplication.clipboard().setText(f"{text}\n{channel}\n{speaker}")
        self.log("TeamSpeak-Status in die Zwischenablage kopiert.")

    def toggle_ts_api_key_visibility(self,visible):
        self.ts_api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def _configure_teamspeak(self):
        self.ts_client.configure(
            self.ts_host.text().strip() or "127.0.0.1",
            self.ts_port.value(),
            self.ts_api_key.text().strip(),
        )

    def load_ts_api_key(self):
        key=read_default_api_key()
        if key:
            self.ts_api_key.setText(key)
            self.save_cfg()
            self.ts_status.setText("TeamSpeak: API-Key aus clientquery.ini geladen")
        else:
            QMessageBox.warning(
                self,"TeamSpeak ClientQuery",
                "Kein ClientQuery API-Key in ~/.ts3client/clientquery.ini gefunden.\n"
                "Bitte ClientQuery im TeamSpeak-3-Client aktivieren oder den API-Key manuell eintragen."
            )

    def refresh_ts_channels(self):
        try:
            self._configure_teamspeak()
            current_cid, current_name=self.ts_client.current_channel()
            channels=self.ts_client.channels()
            self.ts_channel.setText(f"Aktiver TeamSpeak-Channel: {current_name} (CID {current_cid})")
            self.ts_channel_combo.clear()
            current_index=-1
            for cid,name in channels:
                self.ts_channel_combo.addItem(f"{name}  (CID {cid})", cid)
                if cid == current_cid:
                    current_index=self.ts_channel_combo.count()-1
            if current_index >= 0:
                self.ts_channel_combo.setCurrentIndex(current_index)
            if not channels:
                self.ts_channel_combo.addItem("Keine sichtbaren Channels gefunden", None)
            self.log(f"TeamSpeak Channel-Liste geladen: {len(channels)} Channel(s).")
        except Exception as e:
            self.log(f"TeamSpeak Channel-Liste konnte nicht geladen werden: {e}")
            self.show_copyable_error("TeamSpeak Channels", str(e))

    def move_ts_gateway(self):
        cid=self.ts_channel_combo.currentData()
        if cid is None:
            QMessageBox.information(self,"TeamSpeak Channel","Bitte zuerst die Channel-Liste laden und einen Ziel-Channel auswählen.")
            return
        try:
            self._configure_teamspeak()
            before_cid,before_name=self.ts_client.current_channel()
            if int(cid) == int(before_cid or 0):
                self.ts_channel.setText(f"Aktiver TeamSpeak-Channel: {before_name} (CID {before_cid})")
                QMessageBox.information(self,"TeamSpeak Channel","Das Gateway befindet sich bereits in diesem Channel.")
                return
            self.ts_client.move_self(int(cid))
            after_cid,after_name=self.ts_client.current_channel()
            self.ts_channel.setText(f"Aktiver TeamSpeak-Channel: {after_name} (CID {after_cid})")
            self.log(f"TeamSpeak Gateway verschoben: {before_name} (CID {before_cid}) -> {after_name} (CID {after_cid}).")
            QMessageBox.information(self,"TeamSpeak Channel",f"Gateway wurde nach '{after_name}' verschoben.")
            self.refresh_ts_channels()
        except Exception as e:
            self.log(f"TeamSpeak Gateway konnte nicht verschoben werden: {e}")
            self.show_copyable_error("TeamSpeak Channel verschieben", str(e))

    def test_teamspeak(self):
        try:
            self._configure_teamspeak()
            info=self.ts_client.test()
            cid,cname=self.ts_client.current_channel()
            self.ts_status.setText(f"TeamSpeak: ClientQuery verbunden ({info})")
            self.ts_channel.setText(f"Aktiver TeamSpeak-Channel: {cname} (CID {cid})")
            self.log(f"TeamSpeak ClientQuery: Verbindungstest erfolgreich ({info}, Channel={cname}).")
            self.refresh_ts_channels()
        except Exception as e:
            self.ts_status.setText(f"TeamSpeak: nicht verbunden ({e})")
            self.log(f"TeamSpeak ClientQuery: Verbindungstest fehlgeschlagen: {e}")
            self.show_copyable_error("TeamSpeak ClientQuery", str(e))

    def poll_integrations(self):
        if hasattr(self,"mumble_enabled"):
            now=time.monotonic()
            if now-self.mumble_last_poll >= 1.5:
                self.mumble_last_poll=now
                if self.mumble_enabled.isChecked():
                    try:
                        status=self.mumble_local.status(); self._apply_mumble_status(status)
                        marker=self._mumble_local_status_text(status)
                        if marker != self.mumble_last_status:
                            self.log("Mumble: " + marker); self.mumble_last_status=marker
                    except Exception as e:
                        self.mumble_status.setText(f"Mumble läuft – lokale Steuerung konnte nicht gelesen werden ({e})")
                else:
                    self.mumble_status.setText("Mumble-Modul ausgeschaltet")
                    self.mumble_channel.setText("Aktiver Mumble-Channel: —")
                    self.mumble_speaker.setText("Aktueller Mumble-Sprecher: —")
                    self.mumble_details.setText("Lokale Steuerung: —")
                    self.mumble_last_status=None

        if not hasattr(self,"ts_enabled"):
            return

        if not self.ts_enabled.isChecked():
            if self.ts_commander_state:
                try:
                    self._configure_teamspeak()
                    self.ts_client.set_channel_commander(False)
                except Exception:
                    pass
            self.ts_commander_state=False
            self.ts_commander_needs_sync=True
            self.ts_commander_wanted=False
            self.ts_client.close()
            self.ts_status.setText("TeamSpeak: Modul ausgeschaltet")
            self.ts_channel.setText("Aktiver TeamSpeak-Channel: —")
            self.ts_speaker.setText("Aktueller TeamSpeak-Sprecher: —")
            self.ts_last_status=None
            self.ts_last_speakers=None
            self.ts_last_channel=None
            return

        try:
            self._configure_teamspeak()
            speakers=self.ts_client.speakers()
            current_cid,current_name=self.ts_client.current_channel()
            self.ts_status.setText("TeamSpeak: ClientQuery verbunden")
            self.ts_channel.setText(f"Aktiver TeamSpeak-Channel: {current_name} (CID {current_cid})")
            speaker_text=", ".join(speakers) if speakers else "—"
            self.ts_speaker.setText(f"Aktueller TeamSpeak-Sprecher: {speaker_text}")

            if self.ts_commander_enabled.isChecked():
                if self.ts_commander_needs_sync or self.ts_commander_state != self.ts_commander_wanted:
                    self.ts_client.set_channel_commander(self.ts_commander_wanted)
                    self.ts_commander_state=self.ts_commander_wanted
                    self.ts_commander_needs_sync=False
                    self.log(
                        "TeamSpeak Channel Commander: " +
                        ("EIN (Funk-RX)" if self.ts_commander_state else "AUS")
                    )
            elif self.ts_commander_state:
                self.ts_client.set_channel_commander(False)
                self.ts_commander_state=False
                self.ts_commander_needs_sync=False

            status="connected"
            speakers_tuple=tuple(speakers)
            if self.ts_last_status != status:
                self.log("TeamSpeak-Modul verbunden.")
            channel_state=(current_cid,current_name)
            if self.ts_last_channel != channel_state:
                self.log(f"TeamSpeak aktiver Channel: {current_name} (CID {current_cid}).")
            if self.ts_last_speakers != speakers_tuple and speakers:
                self.log("TeamSpeak spricht: " + ", ".join(speakers))
            self.ts_last_status=status
            self.ts_last_speakers=speakers_tuple
            self.ts_last_channel=channel_state
        except Exception as e:
            msg=str(e)
            self.ts_status.setText(f"TeamSpeak: nicht verbunden ({msg})")
            self.ts_channel.setText("Aktiver TeamSpeak-Channel: —")
            self.ts_speaker.setText("Aktueller TeamSpeak-Sprecher: —")
            if self.ts_last_status != msg:
                self.log(f"TeamSpeak-Modul nicht verfügbar: {msg}")
            self.ts_last_status=msg
            self.ts_last_speakers=None
            self.ts_last_channel=None
            self.ts_commander_state=False
            self.ts_commander_needs_sync=True

    def _mumble_local_status_text(self, status):
        if not status.get("installed"):
            return "Mumble nicht installiert"
        if not status.get("running"):
            return "Mumble installiert – Client nicht gestartet"
        if not status.get("connected"):
            return "Mumble läuft – nicht mit Server verbunden"
        return "Mumble verbunden"

    def test_mumble_local(self):
        try:
            status=self.mumble_local.status()
            self._apply_mumble_status(status)
            self.log("Mumble lokale Prüfung: " + self._mumble_local_status_text(status))
        except Exception as e:
            self.mumble_status.setText(f"Mumble läuft – lokale Steuerung konnte nicht gelesen werden ({e})")
            self.show_copyable_error("Mumble prüfen",str(e))

    def _apply_mumble_status(self,status):
        self.mumble_status.setText(self._mumble_local_status_text(status))
        if not status.get("connected"):
            self.mumble_channel.setText("Aktiver Mumble-Channel: —")
            self.mumble_speaker.setText("Aktueller Mumble-Sprecher: —")
            self.mumble_details.setText("Lokale Steuerung: " + ("verfügbar" if status.get("running") else "—"))
            return
        channel=status.get("channel") or "—"
        server=status.get("server") or "—"
        port=status.get("port") or 64738
        user=status.get("user") or "—"
        speakers=status.get("speakers") or []
        self.mumble_channel.setText(f"Aktiver Mumble-Channel: {channel}")
        self.mumble_speaker.setText("Aktueller Mumble-Sprecher: " + (", ".join(speakers) if speakers else "—"))
        self.mumble_details.setText(
            f"Server: {server}:{port} | Benutzer: {user} | "
            f"Mute: {'ja' if status.get('muted') else 'nein'} | "
            f"Deaf: {'ja' if status.get('deaf') else 'nein'} | "
            f"Transmit-Mode: {status.get('transmit_mode','—')}"
        )
        if not self.mumble_gateway_name.text().strip() and status.get("user"):
            self.mumble_gateway_name.setText(status["user"])

    def install_mumble_components(self):
        packages=[]
        if not shutil.which("mumble"):
            packages.append("mumble")

        # Check Ice both in the FunkGateway interpreter and in Ubuntu's system
        # interpreter. Older FunkGateway venvs may not expose distro packages.
        ice_here=self.mumble_ice.ice_python_available()
        ice_system=False
        ice_system_version=""
        if not ice_here:
            try:
                r=subprocess.run(
                    ["/usr/bin/python3","-c","import Ice; print(Ice.stringVersion())"],
                    text=True,capture_output=True,timeout=5
                )
                ice_system=(r.returncode==0)
                ice_system_version=(r.stdout or "").strip()
            except Exception:
                pass
        if not ice_here and not ice_system:
            packages.append("python3-zeroc-ice")

        if not Path("/usr/share/ice/slice").exists():
            packages.append("zeroc-ice-slice")
        if not shutil.which("ssh"):
            packages.append("openssh-client")

        if not packages:
            if ice_here:
                ver=self.mumble_ice.ice_version() or "unbekannt"
                QMessageBox.information(
                    self,"Mumble",
                    f"Alle benötigten Mumble-/Ice-Komponenten sind installiert.\n"
                    f"Python-Ice: OK ({ver})"
                )
            elif ice_system:
                answer=QMessageBox.question(
                    self,"Mumble / Python-Ice",
                    "System-Python: Ice vorhanden"
                    + (f" ({ice_system_version})" if ice_system_version else "")
                    + "\nFunkGateway-venv: Ice nicht nutzbar\n\n"
                      "Soll FunkGateway die virtuelle Python-Umgebung jetzt automatisch "
                      "sichern und mit --system-site-packages neu erstellen?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                if answer == QMessageBox.StandardButton.Yes:
                    try:
                        self.repair_funkgateway_venv_for_ice()
                    except Exception as e:
                        self.show_copyable_error("FunkGateway-venv reparieren",str(e))
            return

        cmd=["pkexec","apt-get","install","-y",*packages]
        try:
            self.log("Mumble-Komponenten werden installiert: " + ", ".join(packages))
            result=subprocess.run(cmd,text=True,capture_output=True)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "Installation fehlgeschlagen").strip())
            QMessageBox.information(
                self,"Mumble",
                "Installation abgeschlossen: " + ", ".join(packages)
                + "\n\nBitte FunkGateway jetzt einmal vollständig beenden und neu starten, "
                  "damit neu installierte Python-Systemmodule sicher erkannt werden."
            )
            self.log("Mumble-Komponenten installiert. Neustart von FunkGateway empfohlen.")
        except Exception as e:
            manual="sudo apt install " + " ".join(packages)
            self.show_copyable_error(
                "Mumble-Komponenten installieren",
                f"{e}\n\nAlternativ im Terminal:\n{manual}"
            )

    def test_mumble_bridge(self):
        try:
            url=self.mumble_bridge_url.text().strip()
            token=self.mumble_bridge_token.text().strip()
            st=self.mumble_bridge.status(url)
            gw=self.mumble_bridge.gateway(url,token)
            g=gw.get("gateway",{})
            txt=(f"Bridge verbunden – Version {st.get('bridge_version','?')}; "
                 f"Token gültig; Gateway {g.get('name','?')}; "
                 f"Channel {g.get('channel_name') or g.get('channel','?')}")
            self.mumble_bridge_status.setText(txt)
            self.log("Mumble Bridge: Verbindung und Token erfolgreich geprüft.")
        except Exception as e:
            self.mumble_bridge_status.setText(f"Bridge: nicht bereit ({e})")
            self.show_copyable_error("Mumble Bridge",str(e))

    def save_mumble_admin_package(self):
        try:
            root=Path(__file__).resolve().parents[1]
            src=root / "admin" / "FunkGateway-Mumble-Admin-Paket-0.1.1.zip"
            if not src.exists():
                raise RuntimeError("Das mitgelieferte Admin-Paket wurde nicht gefunden.")
            target,_=QFileDialog.getSaveFileName(self,"Admin-Paket speichern",str(Path.home()/src.name),"ZIP-Datei (*.zip)")
            if not target: return
            shutil.copy2(src,target)
            self.log(f"Mumble Admin-Paket gespeichert: {target}")
            QMessageBox.information(self,"Mumble Admin-Paket","Admin-Paket gespeichert. Gib diese ZIP-Datei an deinen Mumble-Server-Admin weiter. Er richtet Ice/Bridge ein und gibt dir anschließend nur Bridge-Adresse + persönliches Token.")
        except Exception as e:
            self.show_copyable_error("Admin-Paket speichern",str(e))

    def toggle_mumble_secrets(self, shown):
        mode=QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self.mumble_read_secret.setEchoMode(mode)
        self.mumble_write_secret.setEchoMode(mode)

    def show_mumble_ssh_help(self):
        text=(
            "SSH sicher für FunkGateway einrichten\n\n"
            "Empfohlen: SSH-Key statt gespeichertem Passwort. FunkGateway startet den Tunnel im "
            "Batch-Modus und speichert absichtlich kein SSH-Passwort.\n\n"
            "1. Auf dem Funkrechner einen Schlüssel erzeugen:\n"
            "   ssh-keygen -t ed25519\n\n"
            "2. Öffentlichen Schlüssel auf den Server kopieren:\n"
            "   ssh-copy-id -p <PORT> <BENUTZER>@<SERVER>\n\n"
            "3. Verbindung testen:\n"
            "   ssh -p <PORT> <BENUTZER>@<SERVER>\n\n"
            "4. Bei einem Schlüssel mit Passphrase: ssh-agent verwenden und den Schlüssel einmal "
            "entsperren (z. B. ssh-add ~/.ssh/id_ed25519).\n\n"
            "Danach in FunkGateway nur SSH-Server, Port und Benutzer eintragen.\n\n"
            "Nicht empfohlen: Root-Login, Passwort im Skript oder Passwort in Konfigurationsdateien."
        )
        QMessageBox.information(self,"SSH sicher einrichten",text)

    def choose_mumble_slice(self):
        p,_=QFileDialog.getOpenFileName(self,"Passende Murmur.ice auswählen","","Murmur.ice (*.ice);;Alle Dateien (*)")
        if p:
            self.mumble_slice.setText(p); self.save_cfg()

    def _mumble_ice_endpoint(self):
        mode=self.mumble_ice_mode.currentData()
        if mode == "bridge":
            raise RuntimeError("Bridge-Modus verwendet kein direktes Ice. Bitte 'Bridge-Verbindung / Token prüfen' verwenden.")
        if mode == "off":
            raise RuntimeError("Erweiterte Serversteuerung ist ausgeschaltet.")
        if mode == "ssh":
            return "127.0.0.1", self.mumble_ice_port.value()
        return self.mumble_ice_host.text().strip() or "127.0.0.1", self.mumble_ice_port.value()

    def start_mumble_ssh_tunnel(self):
        if self.mumble_ice_mode.currentData() != "ssh":
            QMessageBox.information(self,"Mumble Ice","Bitte als Anbindung zuerst 'Ice über SSH-Tunnel' auswählen.")
            return
        try:
            msg=self.mumble_ice.start_ssh_tunnel(
                self.mumble_ssh_host.text().strip(),self.mumble_ssh_port.value(),
                self.mumble_ssh_user.text().strip(),self.mumble_ice_port.value())
            self.mumble_ice_status.setText("Erweiterte Serversteuerung: " + msg)
            self.log("Mumble Ice: " + msg)
        except Exception as e:
            self.mumble_ice_status.setText(f"Erweiterte Serversteuerung: SSH-Tunnel fehlgeschlagen ({e})")
            self.show_copyable_error("Mumble SSH-Tunnel",str(e))

    def stop_mumble_ssh_tunnel(self):
        try:
            had_proc=bool(self.mumble_ice.tunnel_proc)
            self.mumble_ice.stop_tunnel()
            if had_proc:
                msg="Von FunkGateway gestarteter SSH-Tunnel wurde gestoppt."
            else:
                msg=(
                    "FunkGateway hatte keinen eigenen SSH-Tunnel-Prozess zum Stoppen. "
                    "Ein extern gestarteter SSH-Tunnel wird aus Sicherheitsgründen nicht beendet."
                )
            self.mumble_ice_status.setText("Erweiterte Serversteuerung: " + msg)
            self.log("Mumble Ice: " + msg)
        except Exception as e:
            self.show_copyable_error("Mumble SSH-Tunnel stoppen",str(e))

    def _parse_ice_endpoints(self, text):
        found=[]
        seen=set()
        for line in str(text).splitlines():
            low=line.lower()
            if "ice=" in low or "murmurice" in low:
                pm=re.search(r"(?:^|\\s)-p\\s+(\\d{1,5})(?:\\s|$|\\\")",line)
                ph=re.search(r"(?:^|\\s)-h\\s+([^\\s\\\"]+)",line)
                if pm:
                    port=int(pm.group(1))
                    if 1 <= port <= 65535:
                        host=ph.group(1) if ph else "127.0.0.1"
                        key=(host,port)
                        if key not in seen:
                            seen.add(key); found.append((host,port,line.strip()))
        return found

    def detect_mumble_ice_settings(self):
        mode=self.mumble_ice_mode.currentData()
        try:
            outputs=[]
            if mode == "ssh":
                host=self.mumble_ssh_host.text().strip()
                user=self.mumble_ssh_user.text().strip()
                port=self.mumble_ssh_port.value()
                if not host:
                    raise RuntimeError("Bitte zuerst den SSH-Server eintragen.")
                target=f"{user}@{host}" if user else host
                remote_cmd="""for f in \
\"$HOME/MumbleFunk/murmur.ini\" \
\"$HOME/murmur.ini\" \
\"/etc/mumble-server.ini\" \
\"/etc/mumble-server/mumble-server.ini\" \
\"/etc/murmur.ini\"; do
  if [ -r \"$f\" ]; then
    echo \"### $f\"
    grep -Ei '^[[:space:]]*ice[[:space:]]*=' \"$f\" 2>/dev/null || true
  fi
done"""
                cmd=["ssh","-p",str(port),"-o","BatchMode=yes","-o","ConnectTimeout=7",target,remote_cmd]
                r=subprocess.run(cmd,text=True,capture_output=True,timeout=12)
                if r.returncode != 0:
                    raise RuntimeError((r.stderr or r.stdout or "SSH-Erkennung fehlgeschlagen. SSH-Key/Agent prüfen.").strip())
                outputs.append(r.stdout)
            else:
                candidates=[
                    Path.home()/"MumbleFunk/murmur.ini",
                    Path.home()/"murmur.ini",
                    Path("/etc/mumble-server.ini"),
                    Path("/etc/mumble-server/mumble-server.ini"),
                    Path("/etc/murmur.ini"),
                ]
                for p in candidates:
                    if p.exists() and os.access(p,os.R_OK):
                        outputs.append(f"### {p}\\n"+p.read_text(errors="ignore"))
            found=self._parse_ice_endpoints("\\n".join(outputs))
            ports=sorted(set(int(x[1]) for x in found))
            if not ports:
                raise RuntimeError("Kein Ice-Port automatisch gefunden. Bitte Port manuell eintragen oder dem SSH-Benutzer Leserechte auf die Murmur-Konfiguration geben.")
            if len(ports) > 1:
                raise RuntimeError("Mehrere mögliche Ice-Ports gefunden: "+", ".join(map(str,ports))+". Bitte den passenden Port manuell auswählen.")
            ice_port=ports[0]
            self.mumble_ice_port.setValue(ice_port)
            if mode == "ssh":
                self.mumble_ice_host.setText("127.0.0.1")
                msg=f"Ice automatisch erkannt: Server-Port {ice_port}. Für den SSH-Tunnel wird lokal ebenfalls Port {ice_port} verwendet."
            else:
                msg=f"Ice automatisch erkannt: Port {ice_port}."
            self.mumble_ice_status.setText("Erweiterte Serversteuerung: "+msg)
            self.log("Mumble Ice: "+msg)
            self.save_cfg()
        except Exception as e:
            self.show_copyable_error("Ice-Einstellungen automatisch erkennen",str(e))

    def _funkgateway_venv_ice_state(self):
        root=Path(__file__).resolve().parent.parent
        vpy=root/".venv/bin/python"
        result={"venv":vpy.exists(),"system_ok":False,"system_version":"","venv_ok":False,"venv_error":""}
        try:
            r=subprocess.run(["/usr/bin/python3","-c","import Ice; print(Ice.stringVersion())"],text=True,capture_output=True,timeout=5)
            result["system_ok"]=(r.returncode==0)
            result["system_version"]=(r.stdout or "").strip()
        except Exception as e:
            result["system_error"]=str(e)
        if vpy.exists():
            try:
                r=subprocess.run([str(vpy),"-c","import Ice; print(Ice.stringVersion())"],text=True,capture_output=True,timeout=8)
                result["venv_ok"]=(r.returncode==0)
                if not result["venv_ok"]:
                    result["venv_error"]=(r.stderr or r.stdout or "").strip()
            except Exception as e:
                result["venv_error"]=str(e)
        return result

    def repair_funkgateway_venv_for_ice(self):
        """Start venv repair without blocking the Qt event loop."""
        root=Path(__file__).resolve().parent.parent
        script=root/"repair-venv.sh"
        if not script.exists():
            raise RuntimeError("repair-venv.sh fehlt im FunkGateway-Paket.")
        state=self._funkgateway_venv_ice_state()
        if not state.get("system_ok"):
            raise RuntimeError(
                "System-Python kann Ice ebenfalls nicht laden. "
                "Bitte zuerst auf 'Mumble-Komponenten installieren / reparieren' klicken."
            )
        if state.get("venv_ok"):
            QMessageBox.information(
                self,"Mumble / Python-Ice",
                "FunkGateway kann Python-Ice bereits laden. Eine Reparatur ist nicht nötig."
            )
            return
        if self.venv_repair_process and self.venv_repair_process.poll() is None:
            QMessageBox.information(
                self,"Mumble / Python-Ice",
                "Die Reparatur läuft bereits. Bitte warten, bis FunkGateway den Abschluss meldet."
            )
            return

        ensure_cfg()
        self.venv_repair_log_path=Path.home()/".config/funkgateway-ui/venv-repair.log"
        self.venv_repair_log_handle=open(self.venv_repair_log_path,"w",encoding="utf-8")
        self.venv_repair_process=subprocess.Popen(
            [str(script)],
            cwd=str(root),
            stdout=self.venv_repair_log_handle,
            stderr=subprocess.STDOUT,
            text=True
        )
        self.venv_repair_message=QMessageBox(self)
        self.venv_repair_message.setWindowTitle("Mumble / Python-Ice")
        self.venv_repair_message.setIcon(QMessageBox.Icon.Information)
        self.venv_repair_message.setText(
            "FunkGateway repariert die Python-Umgebung im Hintergrund.\n\n"
            "Die Oberfläche bleibt dabei benutzbar. Bitte FunkGateway während "
            "der Reparatur nicht beenden."
        )
        self.venv_repair_message.setInformativeText(
            "Alte Umgebung wird gesichert, neue Umgebung wird erstellt und Python-Ice geprüft."
        )
        self.venv_repair_message.setStandardButtons(QMessageBox.StandardButton.NoButton)
        self.venv_repair_message.setModal(False)
        self.venv_repair_message.show()
        self.log("Python-Ice/venv-Reparatur im Hintergrund gestartet.")
        QTimer.singleShot(300,self._poll_venv_repair)

    def _poll_venv_repair(self):
        proc=self.venv_repair_process
        if not proc:
            return
        rc=proc.poll()
        if rc is None:
            QTimer.singleShot(300,self._poll_venv_repair)
            return

        try:
            if self.venv_repair_log_handle:
                self.venv_repair_log_handle.flush()
                self.venv_repair_log_handle.close()
        except Exception:
            pass
        self.venv_repair_log_handle=None

        try:
            log_text=self.venv_repair_log_path.read_text(encoding="utf-8",errors="replace")
        except Exception:
            log_text=""
        self.venv_repair_process=None

        if self.venv_repair_message:
            self.venv_repair_message.close()
            self.venv_repair_message=None

        if rc == 0:
            self.log("Python-Ice/venv-Reparatur erfolgreich abgeschlossen.")
            QMessageBox.information(
                self,"Mumble / Python-Ice",
                "Reparatur erfolgreich.\n\n"
                "Bitte FunkGateway jetzt vollständig beenden und neu starten. "
                "Danach sollte Python-Ice ohne weitere Schritte funktionieren."
            )
        else:
            tail="\n".join(log_text.splitlines()[-25:])
            self.log(f"Python-Ice/venv-Reparatur fehlgeschlagen (Exit {rc}).")
            self.show_copyable_error(
                "FunkGateway-venv reparieren",
                f"Die Reparatur ist mit Exit-Code {rc} fehlgeschlagen.\n\n"
                f"Protokoll: {self.venv_repair_log_path}\n\n{tail}"
            )

    def test_mumble_ice(self):
        try:
            if self.mumble_ice_mode.currentData()=="ssh":
                self.start_mumble_ssh_tunnel()
            host,port=self._mumble_ice_endpoint()
            read=self.mumble_read_secret.text()
            if not read: raise RuntimeError("Bitte das Ice Read-Secret eingeben. Es wird nicht gespeichert.")
            info=self.mumble_ice.test(host,port,self.mumble_slice.text(),read,self.mumble_ice_server_id.value())
            self.mumble_ice_status.setText(
                f"Ice verbunden – Server-ID {info['server_id']}, läuft: {info['running']}, "
                f"Channels: {info['channels']}, Benutzer: {info['users']}"
            )
            self.log("Mumble Ice: Verbindungstest erfolgreich.")
        except Exception as e:
            self.mumble_ice_status.setText(f"Erweiterte Serversteuerung: nicht verbunden ({e})")
            self.show_copyable_error("Mumble Ice",str(e))

    def refresh_mumble_ice_channels(self):
        if self.mumble_ice_mode.currentData() == "bridge":
            QMessageBox.information(self,"Mumble Bridge","Im Bridge-Modus legt der Server-Admin Normal- und Störungsraum fest. Der normale Gatewaybetreiber kann keine beliebigen Channels auswählen.")
            return
        try:
            host,port=self._mumble_ice_endpoint(); read=self.mumble_read_secret.text()
            if not read: raise RuntimeError("Bitte das Ice Read-Secret eingeben.")
            channels=self.mumble_ice.channels(host,port,self.mumble_slice.text(),read,self.mumble_ice_server_id.value())
            self.mumble_channels=channels
            for combo in (self.mumble_channel_combo,self.mumble_disturbance_combo):
                old=combo.currentData(); combo.clear(); idx=-1
                for cid,name,parent in channels:
                    combo.addItem(f"{name}  (CID {cid}, Parent {parent})",cid)
                    if old is not None and int(old)==cid: idx=combo.count()-1
                if idx>=0: combo.setCurrentIndex(idx)
                if not channels: combo.addItem("Keine Channels gefunden",None)
            room=self.mumble_disturbance_rooms.get(self._mumble_server_key())
            if room:
                i=self.mumble_disturbance_combo.findData(room.get("cid"))
                if i>=0: self.mumble_disturbance_combo.setCurrentIndex(i)
                self.mumble_disturbance_status.setText(f"Mumble-Störungsraum: {room.get('name','?')} (CID {room.get('cid','?')})")
            else:
                self.mumble_disturbance_status.setText("Mumble-Störungsraum: für diesen Server noch nicht eingerichtet")
            self.log(f"Mumble Ice: {len(channels)} Channels geladen.")
        except Exception as e:
            self.show_copyable_error("Mumble Channels",str(e))

    def _mumble_gateway_name_value(self):
        name=self.mumble_gateway_name.text().strip()
        if not name:
            try: name=self.mumble_local.current_context().get("user","")
            except Exception: pass
        if not name: raise RuntimeError("Gateway-Mumble-Name konnte nicht bestimmt werden.")
        return name

    def _mumble_sink_inputs(self):
        """Find active Mumble playback sink-input IDs via PulseAudio/PipeWire."""
        ids=[]
        try:
            r=subprocess.run(["pactl","list","sink-inputs"],text=True,capture_output=True,timeout=5)
            current=None
            is_mumble=False
            for raw in r.stdout.splitlines():
                line=raw.strip()
                m=re.match(r"Sink Input #(\\d+)",line)
                if m:
                    if current is not None and is_mumble:
                        ids.append(current)
                    current=int(m.group(1))
                    is_mumble=False
                    continue
                if current is not None and (
                    'application.name = "Mumble"' in line
                    or 'application.process.binary = "mumble"' in line
                    or 'application.id = "net.sourceforge.mumble.mumble"' in line
                ):
                    is_mumble=True
            if current is not None and is_mumble:
                ids.append(current)
        except Exception as e:
            self.log(f"Mumble-Audio: Wiedergabestream konnte nicht ermittelt werden: {e}")
        return sorted(set(ids))

    def _set_mumble_playback_muted(self, muted):
        """Mute only Mumble playback, never the entire radio/virtual sink."""
        if muted:
            ids=self._mumble_sink_inputs()
            self.mumble_muted_sink_inputs=ids
            for sid in ids:
                try:
                    subprocess.run(
                        ["pactl","set-sink-input-mute",str(sid),"1"],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3
                    )
                except Exception as e:
                    self.log(f"Mumble-Audio: Stream {sid} konnte nicht stummgeschaltet werden: {e}")
            if ids:
                self.log("Mumble-Audio für Raumwechsel vorübergehend stumm: "
                         + ", ".join(map(str,ids)))
            else:
                self.log("Mumble-Audio: kein aktiver Wiedergabestream zum Stummschalten gefunden.")
            return

        ids=list(self.mumble_muted_sink_inputs)
        self.mumble_muted_sink_inputs=[]
        for sid in ids:
            try:
                subprocess.run(
                    ["pactl","set-sink-input-mute",str(sid),"0"],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3
                )
            except Exception as e:
                self.log(f"Mumble-Audio: Stream {sid} konnte nicht wieder freigegeben werden: {e}")
        if ids:
            self.log("Mumble-Audio nach Raumwechsel wieder freigegeben.")

    def _begin_mumble_room_change_guard(self, seconds=8.0):
        """Break local Mumble notification/feedback loops around a room change."""
        # If a previous guard is still active, first restore its remembered IDs.
        if self.mumble_muted_sink_inputs:
            self._set_mumble_playback_muted(False)
        self._set_mumble_playback_muted(True)
        self.mumble_room_guard_until=time.monotonic()+float(seconds)
        QTimer.singleShot(
            int(float(seconds)*1000),
            self._finish_mumble_room_change_guard
        )
        self.log(f"Mumble-Raumwechsel-Schutz für {float(seconds):.1f} s aktiv.")

    def _finish_mumble_room_change_guard(self):
        # Ignore an old timer when a newer guard is still active.
        if time.monotonic() < self.mumble_room_guard_until-0.15:
            return
        self._set_mumble_playback_muted(False)
        self.mumble_room_guard_until=0.0
        self.log("Mumble-Raumwechsel-Schutz beendet.")

    def move_mumble_gateway_manual(self):
        if self.mumble_ice_mode.currentData() == "bridge":
            QMessageBox.information(self,"Mumble Bridge","Im Bridge-Modus sind freie Channel-Wechsel absichtlich gesperrt. Die Bridge erlaubt nur die vom Admin freigegebenen Übergänge Normalraum ↔ Störungsraum.")
            return
        cid=self.mumble_channel_combo.currentData()
        if cid is None:
            QMessageBox.information(self,"Mumble Channel","Bitte zuerst die Channel-Liste laden und einen Ziel-Channel auswählen."); return
        try:
            write=self.mumble_write_secret.text(); read=self.mumble_read_secret.text()
            if not write: raise RuntimeError("Bitte das Ice Write-Secret eingeben. Es wird nicht gespeichert.")
            host,port=self._mumble_ice_endpoint(); name=self._mumble_gateway_name_value()
            self._begin_mumble_room_change_guard(8.0)
            old=self.mumble_ice.move_gateway(host,port,self.mumble_slice.text(),read,write,name,int(cid),self.mumble_ice_server_id.value())
            self.log(f"Mumble Gateway verschoben: CID {old} -> CID {cid} ({name}).")
            QMessageBox.information(self,"Mumble Channel",f"Gateway wurde von CID {old} nach CID {cid} verschoben.")
        except Exception as e:
            self.show_copyable_error("Mumble Channel verschieben",str(e))

    def _mumble_server_key(self):
        mode=self.mumble_ice_mode.currentData() or "off"
        endpoint=(self.mumble_ssh_host.text().strip() if mode == "ssh" else self.mumble_ice_host.text().strip()) or "127.0.0.1"
        return f"{mode}|{endpoint}|{self.mumble_ice_port.value()}|{self.mumble_ice_server_id.value()}"

    def set_mumble_disturbance_room(self):
        if self.mumble_ice_mode.currentData() == "bridge":
            QMessageBox.information(self,"Mumble Bridge","Im Bridge-Modus wird der Störungsraum vom Server-Admin beim Erzeugen deines Tokens festgelegt.")
            return
        cid=self.mumble_disturbance_combo.currentData()
        if cid is None:
            QMessageBox.information(self,"Mumble-Störungsraum","Bitte zuerst die Ice-Channel-Liste laden und einen Channel auswählen."); return
        name=self.mumble_disturbance_combo.currentText().split("  (CID",1)[0]
        key=self._mumble_server_key()
        self.mumble_disturbance_rooms[key]={"cid":int(cid),"name":name}
        self.mumble_disturbance_status.setText(f"Mumble-Störungsraum: {name} (CID {cid})")
        self.save_cfg(); self.log(f"Mumble-Störungsraum gespeichert: {name} (CID {cid}) für {key}.")

    def _auto_move_to_mumble_disturbance_room(self):
        if not self.protect_move_to_mumble_room.isChecked():
            return False
        mode=self.mumble_ice_mode.currentData()
        if mode == "off":
            self.log("Dauer-RX: Mumble-Störungsraum ist aktiviert, aber keine Mumble-Serveranbindung ausgewählt.")
            return False
        if mode == "bridge":
            try:
                token=self.mumble_bridge_token.text().strip()
                url=self.mumble_bridge_url.text().strip()
                self._begin_mumble_room_change_guard(8.0)
                result=self.mumble_bridge.disturbance(url,token)
                self.protection_mumble_auto_move_active=True
                self.log(
                    f"Dauer-RX: Mumble-Bridge hat Gateway sofort in den freigegebenen "
                    f"Störungsraum geschaltet (Channel {result.get('channel','?')}); "
                    f"RX-Frei ist dafür nicht erforderlich."
                )
                return True
            except Exception as e:
                self.log(f"Dauer-RX: Mumble-Bridge-Störungsraum konnte nicht aktiviert werden: {e}")
                return False
        room=self.mumble_disturbance_rooms.get(self._mumble_server_key())
        cid=room.get("cid") if room else None
        if cid is None:
            self.log("Dauer-RX: kein Mumble-Störungsraum für diesen Server definiert.")
            return False
        try:
            host,port=self._mumble_ice_endpoint()
            read=self.mumble_read_secret.text()
            write=self.mumble_write_secret.text()
            name=self._mumble_gateway_name_value()
            if not read or not write:
                raise RuntimeError("Ice Read-/Write-Secret ist für den automatischen Mumble-Störungsraum nicht in dieser Sitzung eingegeben.")
            state=self.mumble_ice.gateway_state(host,port,self.mumble_slice.text(),read,name,self.mumble_ice_server_id.value())
            self.protection_previous_mumble_channel=state["channel"]
            if int(state["channel"]) != int(cid):
                self._begin_mumble_room_change_guard(8.0)
                self.mumble_ice.move_gateway(host,port,self.mumble_slice.text(),read,write,name,int(cid),self.mumble_ice_server_id.value())
                self.log(f"Dauer-RX: Mumble-Gateway sofort in Störungsraum CID {cid} verschoben; offene Rauschsperre blockiert den Wechsel nicht.")
            else:
                self.log(f"Dauer-RX: Mumble-Gateway befindet sich bereits im Störungsraum CID {cid}.")
            self.protection_mumble_auto_move_active=True
            return True
        except Exception as e:
            self.log(f"Dauer-RX: Mumble-Störungsraum konnte nicht aktiviert werden: {e}")
            return False

    def _return_mumble_after_protection(self):
        if not self.protection_mumble_auto_move_active or not self.protect_return_mumble_channel.isChecked(): return
        if self.mumble_ice_mode.currentData() == "bridge":
            try:
                self._begin_mumble_room_change_guard(8.0)
                result=self.mumble_bridge.return_normal(self.mumble_bridge_url.text().strip(),self.mumble_bridge_token.text().strip())
                self.log(f"Mumble-Bridge: nach Schutz in den freigegebenen Normalraum zurückgekehrt (Channel {result.get('channel','?')}).")
            except Exception as e:
                self.log(f"Mumble-Bridge Rückkehr nach Schutz fehlgeschlagen: {e}")
            finally:
                self.protection_mumble_auto_move_active=False; self.protection_previous_mumble_channel=None
            return
        if self.protection_previous_mumble_channel is None: return
        try:
            host,port=self._mumble_ice_endpoint(); read=self.mumble_read_secret.text(); write=self.mumble_write_secret.text(); name=self._mumble_gateway_name_value()
            self._begin_mumble_room_change_guard(8.0)
            self.mumble_ice.move_gateway(host,port,self.mumble_slice.text(),read,write,name,int(self.protection_previous_mumble_channel),self.mumble_ice_server_id.value())
            self.log(f"Mumble: nach Schutz zurück in vorherigen Channel CID {self.protection_previous_mumble_channel} verschoben.")
        except Exception as e:
            self.log(f"Mumble Rückkehr nach Schutz fehlgeschlagen: {e}")
        finally:
            self.protection_mumble_auto_move_active=False; self.protection_previous_mumble_channel=None

    def build_log(self):
        w=QWidget(); v=QVBoxLayout(w)
        self.logbox=QTextEdit(); self.logbox.setReadOnly(True)

        controls=QHBoxLayout()
        self.verbose_log=QCheckBox("Ausführliches Log")
        self.verbose_log.setChecked(False)
        self.verbose_log.setToolTip(
            "Ohne Haken zeigt die Protokollansicht nur wichtige Betriebsereignisse "
            "wie PTT EIN/AUS, Sprecher, DTMF-Aktionen, Betriebsartwechsel, Schutz- "
            "und Fehlermeldungen. Mit Haken werden zusätzlich technische Detailmeldungen angezeigt. "
            "Die Logdatei auf der Festplatte bleibt unabhängig davon vollständig."
        )
        clear=QPushButton("Anzeige leeren"); clear.clicked.connect(self.logbox.clear)
        controls.addWidget(self.verbose_log)
        controls.addStretch(1)
        controls.addWidget(clear)

        hint=QLabel(
            "Kompaktmodus: wichtige Grundfunktionen. "
            "„Ausführliches Log“ zeigt zusätzlich Diagnose- und Ablaufdetails. "
            "Die gespeicherte Logdatei enthält weiterhin alle Meldungen."
        )
        hint.setWordWrap(True)

        v.addLayout(controls)
        v.addWidget(hint)
        v.addWidget(self.logbox)
        self.tabs.addTab(w,"Protokoll")

    def build_help(self):
        w=QWidget(); v=QVBoxLayout(w); h=QTextEdit(); h.setReadOnly(True); h.setHtml(HELP_HTML)
        v.addWidget(h); self.tabs.addTab(w,"Hilfe")

    @staticmethod
    def _is_compact_log_message(msg):
        """Return True for messages that belong in the normal compact log view."""
        m=str(msg)
        low=m.lower()

        # Always surface anything that looks like an error/problem.
        error_tokens=(
            "fehler","fehlgeschlagen","konnte nicht","nicht gefunden","warnung",
            "timeout","abgebrochen","blockiert","störung","not-aus","tot "
        )
        if any(token in low for token in error_tokens):
            return True

        # Core radio operation and user-visible state changes.
        prefixes=(
            "PTT EIN","PTT AUS",
            "TeamSpeak spricht:","Mumble spricht:",
            "DTMF-Code ","DTMF-Code vollständig:",
            "DTMF-AUTH","AUTH ",
            "Gateway gestartet","Gateway gestoppt",
            "FunkGateway ","Funk-RX aktiv:",
            "Papagei: RX begonnen","Papagei: Aufnahme beendet",
            "Papagei: Wiedergabe gestartet","Papagei: Wiedergabe beendet",
            "Papagei: bereit","Papagei-Isolation:",
            "Dauer-RX:","Selbstrücklauf-Schutz",
            "TeamSpeak aktiver Channel:","Mumble aktiver Channel:",
            "TeamSpeak Raum ","Mumble Raum ",
            "Rogerbeep ","Rufzeichenbake ","Papageibake ",
        )
        if any(m.startswith(prefix) for prefix in prefixes):
            return True

        # Important DTMF acknowledgement states, but not every retry/detail.
        if m.startswith("DTMF-Vollzugsmeldung"):
            important=(
                "PTT EIN","Wiedergabe gestartet","WAV beendet","beendet:",
                "Kanal frei","fehlgeschlagen"
            )
            return any(token in m for token in important)

        # Mode switches should always be visible.
        if ("Papagei EIN" in m or "VoIP-Betrieb" in m) and "DTMF" in m:
            return True

        return False

    def log(self,msg):
        ts=datetime.now().strftime("%H:%M:%S")

        # The on-screen view is compact by default.  The checkbox only controls
        # visibility; the persistent logfile below always receives every entry.
        verbose=bool(hasattr(self,"verbose_log") and self.verbose_log.isChecked())
        if verbose or self._is_compact_log_message(msg):
            self.logbox.append(f"[{ts}] {msg}")

        ensure_cfg()
        with open(LOG_FILE,"a",encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


    def refresh_ports(self):
        """Serielle Schnittstellen neu suchen und den Status verständlich anzeigen."""
        wanted = getattr(self, "_wanted_port", None) or self.selected_port()
        self._wanted_port = None
        self.com_port.clear()

        for dev in discover_serial_ports():
            self.com_port.addItem(friendly_port_name(dev), dev)

        if wanted:
            i = self.com_port.findData(wanted)
            if i >= 0:
                self.com_port.setCurrentIndex(i)
            else:
                self.com_port.setEditText(wanted)

        visible_ports = [
            self.com_port.itemData(i) or self.com_port.itemText(i).split("  – " )[0].strip()
            for i in range(self.com_port.count())
        ]
        usb_ports = [
            port for port in visible_ports
            if str(port).startswith("/dev/ttyUSB") or str(port).startswith("/dev/ttyACM")
        ]

        if usb_ports:
            self.usb_serial_hint.setText(
                "USB-Seriell-Gerät erkannt: " + ", ".join(map(str, usb_ports))
            )
        else:
            self.usb_serial_hint.setText(
                "Kein USB-Seriell-Gerät gefunden. Das ist normal, wenn kein "
                "USB-Adapter angeschlossen ist. USB-Adapter erscheinen meist "
                "als /dev/ttyUSB0 oder /dev/ttyACM0. Danach einfach "
                "„Ports neu suchen“ drücken."
            )

        self.log(f"Serielle Ports neu gesucht: {self.com_port.count()} gefunden.")


    def selected_port(self):
        return self.com_port.currentData() or self.com_port.currentText().split("  – ")[0].strip()


    def ensure_gateway_sink(self):
        """Ensure the virtual FunkGateway_TX sink exists.

        FunkGateway_TX is the virtual playback target that applications such as
        TeamSpeak, Mumble or FRN should use.  PipeWire/Pulse creates it via
        module-null-sink.  The function is safe to call repeatedly.
        """
        try:
            out = subprocess.check_output(
                ["pactl", "list", "short", "sinks"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            if "funkgateway_tx" not in out:
                subprocess.run(
                    [
                        "pactl", "load-module", "module-null-sink",
                        "sink_name=funkgateway_tx",
                        "sink_properties=device.description=FunkGateway_TX",
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.log("Virtueller Ausgang FunkGateway_TX wurde angelegt.")
            else:
                self.log("FunkGateway_TX ist vorhanden.")
            return True
        except Exception as e:
            self.log(f"FunkGateway_TX konnte nicht geprüft/angelegt werden: {e}")
            return False

    def _read_sink_inputs(self):
        """Return active Pulse/PipeWire playback streams in a simple structure."""
        try:
            out = subprocess.check_output(
                ["pactl", "list", "sink-inputs"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return []

        streams = []
        current = None
        for raw in out.splitlines():
            line = raw.strip()
            if line.startswith("Sink Input #"):
                if current:
                    streams.append(current)
                current = {
                    "id": line.split("#", 1)[1].strip(),
                    "sink": "",
                    "app": "",
                    "binary": "",
                    "media": "",
                    "mute": False,
                }
            elif current is not None:
                if line.startswith("Sink:"):
                    current["sink"] = line.split(":", 1)[1].strip()
                elif 'application.name = ' in line:
                    current["app"] = line.split("=", 1)[1].strip().strip('"')
                elif 'application.process.binary = ' in line:
                    current["binary"] = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("Mute:"):
                    current["mute"] = line.split(":",1)[1].strip().lower() == "yes"
                elif 'media.name = ' in line:
                    current["media"] = line.split("=", 1)[1].strip().strip('"')
        if current:
            streams.append(current)
        return streams

    def _funkgateway_sink_id(self):
        try:
            out = subprocess.check_output(
                ["pactl", "list", "short", "sinks"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "funkgateway_tx":
                    return parts[0]
        except Exception:
            pass
        return None

    def refresh_audio_streams(self):
        """Refresh running playback applications for easy GUI routing."""
        if not hasattr(self, "stream_combo"):
            return

        current_data = self.stream_combo.currentData()
        self.stream_combo.clear()
        streams = self._read_sink_inputs()

        for stream in streams:
            name = stream["app"] or stream["binary"] or stream["media"] or "Unbekannt"
            media = f" – {stream['media']}" if stream["media"] and stream["media"] != name else ""
            label = f"{name}{media}  (Stream {stream['id']})"
            self.stream_combo.addItem(label, stream["id"])

        if not streams:
            self.stream_combo.addItem("Keine laufenden Audioprogramme gefunden", None)
            self.stream_status.setText(
                "Starte z. B. TeamSpeak, Mumble oder FRN und lass dort kurz Audio laufen. "
                "Dann „Audioprogramme neu suchen“ drücken."
            )
            return

        # Restore previous selection if possible.
        if current_data is not None:
            for i in range(self.stream_combo.count()):
                if self.stream_combo.itemData(i) == current_data:
                    self.stream_combo.setCurrentIndex(i)
                    break

        self._update_stream_status()

    def _update_stream_status(self):
        if not hasattr(self, "stream_combo"):
            return
        sid = self.stream_combo.currentData()
        if sid is None:
            return
        sink_id = self._funkgateway_sink_id()
        for stream in self._read_sink_inputs():
            if stream["id"] == str(sid):
                if sink_id and stream["sink"] == sink_id:
                    self.stream_status.setText("OK: Dieses Programm läuft tatsächlich über FunkGateway_TX.")
                else:
                    self.stream_status.setText(
                        "ACHTUNG: Dieses Programm läuft derzeit NICHT über FunkGateway_TX. "
                        "Mit dem Routing-Knopf kann es umgeschaltet werden."
                    )
                return

    def route_stream_to_gateway(self, stream_id):
        """Move one active playback stream to FunkGateway_TX."""
        if not self.ensure_gateway_sink():
            return False
        try:
            subprocess.run(
                ["pactl", "move-sink-input", str(stream_id), "funkgateway_tx"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.log(f"Audiostream {stream_id} wurde zu FunkGateway_TX geroutet.")
            return True
        except Exception as e:
            self.log(f"Audiostream {stream_id} konnte nicht geroutet werden: {e}")
            return False

    def route_selected_stream(self):
        sid = self.stream_combo.currentData()
        if sid is None:
            QMessageBox.information(
                self, "Audio-Routing",
                "Es ist noch kein laufendes Audioprogramm ausgewählt."
            )
            return
        if self.route_stream_to_gateway(sid):
            self.refresh_audio_streams()

    def auto_route_known_apps(self):
        """Route common gateway applications automatically at gateway start.

        This intentionally targets only common radio/voice applications instead
        of blindly moving every desktop audio stream (e.g. Firefox or music).
        """
        known = (
            "teamspeak", "ts3client", "mumble", "frn", "free radio network",
            "zello", "discord"
        )
        sink_id = self._funkgateway_sink_id()
        moved = 0
        for stream in self._read_sink_inputs():
            haystack = " ".join(
                [stream["app"], stream["binary"], stream["media"]]
            ).lower()
            if any(token in haystack for token in known):
                if sink_id is None or stream["sink"] != sink_id:
                    if self.route_stream_to_gateway(stream["id"]):
                        moved += 1
        if moved:
            self.log(f"{moved} Audioprogramm(e) automatisch zu FunkGateway_TX geroutet.")
        self.refresh_audio_streams()

    @staticmethod
    def _is_known_voip_stream(stream):
        haystack=" ".join([
            stream.get("app",""),
            stream.get("binary",""),
            stream.get("media","")
        ]).lower()
        known=(
            "teamspeak","ts3client","mumble","frn","free radio network",
            "zello","discord"
        )
        return any(token in haystack for token in known)

    def _sync_parrot_voip_playback_mute(self):
        """Physically mute VoIP playback streams while Papagei mode is active.

        Merely suppressing the PTT trigger is insufficient: while PTT is keyed
        for a Papagei replay/beacon/ACK, an unmuted TeamSpeak/Mumble stream on
        FunkGateway_TX would be mixed into the RF audio.  Therefore known VoIP
        sink-inputs themselves are muted during Papagei mode.
        """
        enabled=bool(
            hasattr(self,"parrot_enabled")
            and self.parrot_enabled.isChecked()
            and hasattr(self,"parrot_mute_voip")
            and self.parrot_mute_voip.isChecked()
        )

        if not enabled:
            if not self.parrot_muted_voip_streams:
                return
            current={str(x["id"]):x for x in self._read_sink_inputs()}
            for sid in list(self.parrot_muted_voip_streams):
                if sid not in current:
                    self.parrot_muted_voip_streams.discard(sid)
                    continue
                try:
                    subprocess.run(
                        ["pactl","set-sink-input-mute",str(sid),"0"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                        check=True,
                    )
                    self.log(f"Papagei: VoIP-Wiedergabestream {sid} wieder freigegeben.")
                except Exception as e:
                    self.log(f"Papagei: VoIP-Wiedergabestream {sid} konnte nicht freigegeben werden: {e}")
                finally:
                    self.parrot_muted_voip_streams.discard(sid)
            return

        sink_id=self._funkgateway_sink_id()
        current_ids=set()
        for stream in self._read_sink_inputs():
            sid=str(stream.get("id",""))
            if not sid:
                continue
            current_ids.add(sid)

            # Only playback that is actually routed to FunkGateway_TX matters.
            if sink_id and stream.get("sink") != str(sink_id):
                continue
            if not self._is_known_voip_stream(stream):
                continue

            # Preserve streams which were already muted by the user/application.
            if stream.get("mute",False):
                continue
            if sid in self.parrot_muted_voip_streams:
                continue

            try:
                subprocess.run(
                    ["pactl","set-sink-input-mute",sid,"1"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    check=True,
                )
                self.parrot_muted_voip_streams.add(sid)
                name=stream.get("app") or stream.get("binary") or "VoIP"
                self.log(f"Papagei: {name}-Wiedergabe auf FunkGateway_TX stummgeschaltet (Stream {sid}).")
            except Exception as e:
                self.log(f"Papagei: VoIP-Wiedergabestream {sid} konnte nicht stummgeschaltet werden: {e}")

        # Forget IDs of streams that vanished while Papagei was active.
        self.parrot_muted_voip_streams.intersection_update(current_ids)

    def routing_watchdog_tick(self):
        """Keep known voice applications routed correctly and enforce Papagei mute."""
        if not self.bridge:
            return

        now=time.monotonic()
        if now-self.last_route_check < 1.5:
            return
        self.last_route_check=now

        # This must run even when automatic routing is disabled: a newly
        # created TeamSpeak/Mumble playback stream must not leak into RF while
        # the Papagei is transmitting.
        self._sync_parrot_voip_playback_mute()

        if not hasattr(self, "auto_route") or not self.auto_route.isChecked():
            return

        sink_id=self._funkgateway_sink_id()
        if not sink_id:
            if not self.ensure_gateway_sink():
                return
            sink_id=self._funkgateway_sink_id()
            if not sink_id:
                return

        changed=False
        for stream in self._read_sink_inputs():
            if not self._is_known_voip_stream(stream):
                continue

            if stream.get("sink") != sink_id:
                try:
                    subprocess.run(
                        ["pactl","move-sink-input",str(stream["id"]),"funkgateway_tx"],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    name=stream.get("app") or stream.get("binary") or "Audioprogramm"
                    self.log(
                        f"Audio-Routing korrigiert: {name} "
                        f"(Stream {stream['id']}) -> FunkGateway_TX"
                    )
                    changed=True
                except Exception as e:
                    self.log(
                        f"Audio-Routing für Stream {stream['id']} fehlgeschlagen: {e}"
                    )

        if changed:
            self.refresh_audio_streams()
            self._sync_parrot_voip_playback_mute()

    def refresh_audio_devices(self):
        """Load real PipeWire/PulseAudio recording sources."""
        self.refresh_sinks()
        self.input_device.clear()
        if hasattr(self, "rx_source"):
            wanted_rx=getattr(self,"_wanted_rx_source",None) or self.rx_source.currentData()
            self.rx_source.clear()
        else:
            wanted_rx=None

        try:
            default_source=""
            try:
                default_source=subprocess.check_output(
                    ["pactl","get-default-source"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            except Exception:
                pass

            out=subprocess.check_output(
                ["pactl","list","short","sources"],
                text=True,
                stderr=subprocess.DEVNULL,
            )

            sources=[]
            for line in out.splitlines():
                parts=line.split()
                if len(parts)<2:
                    continue
                source_name=parts[1]

                # Playback monitors are not microphones.
                if source_name.endswith(".monitor") or source_name == "funkgateway_rx_source":
                    continue

                sources.append(source_name)

            if not sources:
                self.input_device.addItem("Keine Mikrofonquelle gefunden",None)
                return

            for source_name in sources:
                label=source_name
                if source_name == default_source:
                    label += "  (Standard)"
                self.input_device.addItem(label,source_name)
                if hasattr(self, "rx_source"):
                    self.rx_source.addItem(label,source_name)

            if default_source:
                for i in range(self.input_device.count()):
                    if self.input_device.itemData(i) == default_source:
                        self.input_device.setCurrentIndex(i)
                        break
            if hasattr(self, "rx_source"):
                if wanted_rx:
                    i=self.rx_source.findData(wanted_rx)
                    if i>=0: self.rx_source.setCurrentIndex(i)
                elif default_source:
                    i=self.rx_source.findData(default_source)
                    if i>=0: self.rx_source.setCurrentIndex(i)
                self._wanted_rx_source=None

        except Exception as e:
            self.input_device.addItem(
                "Mikrofonquellen konnten nicht gelesen werden",None
            )
            if hasattr(self, "rx_source"):
                self.rx_source.addItem("Funk-Eingangsquellen konnten nicht gelesen werden",None)
            self.log(f"Fehler beim Einlesen der Mikrofone: {e}")
    def refresh_sinks(self):
        wanted=getattr(self,"_wanted_sink",None) or self.target_sink.currentData()
        self.target_sink.clear()
        for name,label in list_sinks():
            if name not in ("funkgateway_tx","funkgateway_rx"): self.target_sink.addItem(label,name)
        if wanted:
            i=self.target_sink.findData(wanted)
            if i>=0: self.target_sink.setCurrentIndex(i)
        self._wanted_sink=None

    def create_sink(self):
        try: make_virtual_sink(); self.log("FunkGateway_TX ist bereit."); QMessageBox.information(self,"Audio","FunkGateway_TX ist bereit und kann als Audio-Ausgang gewählt werden.")
        except Exception as e: self.show_copyable_error("Audio",str(e))

    def create_ptt(self):
        if self.ptt:
            try: self.ptt.close()
            except Exception: pass
        method=self.ptt_method.currentText()
        if method=="Testmodus": self.ptt=DryPTT()
        elif method=="Serieller COM-Port":
            port=self.selected_port()
            if not port: raise RuntimeError("Bitte einen COM-/USB-Port auswählen.")
            self.ptt=SerialPTT(port,self.com_line.currentText(),self.invert.isChecked())
        elif method=="CM108/CM119 GPIO": self.ptt=CM108PTT(self.cm_dev.text().strip(),3,self.invert.isChecked())
        else: self.ptt=GPIOPTT(self.gpio_chip.text().strip(),self.gpio_line.value(),self.invert.isChecked())

    def _return_guard_kind_enabled(self,kind):
        if not self.return_guard_enabled.isChecked():
            return False
        mapping={
            "voip":self.return_after_voip,
            "beacon":self.return_after_beacon,
            "roger":self.return_after_roger,
            "protection":self.return_after_protection,
            "manual":self.return_after_manual,
            "parrot":self.parrot_return_guard if hasattr(self,"parrot_return_guard") else None,
        }
        box=mapping.get(kind)
        return bool(box and box.isChecked())

    def _start_return_guard(self,kind):
        if not kind or not self._return_guard_kind_enabled(kind):
            return
        ms=self.return_guard_ms.value()
        if ms <= 0:
            return
        now=time.monotonic()
        self.return_guard_tx_ended=now
        self.return_guard_until=now+(ms/1000.0)
        self.return_guard_candidate=False
        self.return_guard_rx_started=None
        self.return_guard_muted=True
        self._refresh_rx_forward_mute()
        self.log(f"Selbstrücklauf-Schutz gestartet nach {kind}: RX→VoIP für neue RX-Starts {ms} ms geschützt (Standard: 3500 ms).")

    def set_ptt(self,on):
        if self.tx==on: return
        try:
            if on and self.lead.value()>0:
                self.ptt.key(True); self.tx=True; self.tx_since=time.monotonic(); self.tx_lbl.setText("● PTT EIN / TX"); self.log("PTT EIN")
                time.sleep(self.lead.value()/1000)
            else:
                ending_kind=self.active_tx_kind if not on else None
                self.ptt.key(on); self.tx=on; self.tx_since=time.monotonic() if on else None
                self.tx_lbl.setText("● PTT EIN / TX" if on else "● PTT AUS"); self.log("PTT EIN" if on else "PTT AUS")
                if not on:
                    self._start_return_guard(ending_kind)
                    self.active_tx_kind=None
        except Exception as e: self.log(f"PTT-Fehler: {e}"); self.show_copyable_error("PTT-Fehler",str(e))

    def _tx_sink_index(self):
        """Return PipeWire/Pulse sink index of FunkGateway_TX."""
        try:
            r=subprocess.run(["pactl","list","sinks","short"],text=True,capture_output=True,timeout=3)
            for line in r.stdout.splitlines():
                parts=line.split("\t")
                if len(parts) >= 2 and parts[1].strip().lower() == "funkgateway_tx":
                    return int(parts[0])
        except Exception as e:
            if hasattr(self,"diagnostic_mode") and self.diagnostic_mode.isChecked():
                self.log(f"VoIP-HF-Sprachfilter: FunkGateway_TX konnte nicht ermittelt werden: {e}")
        return None

    def _tx_sink_input_apps(self):
        """Return normalized app descriptions attached to FunkGateway_TX."""
        sink_index=self._tx_sink_index()
        if sink_index is None:
            return []
        try:
            r=subprocess.run(["pactl","list","sink-inputs"],text=True,capture_output=True,timeout=4)
        except Exception:
            return []

        entries=[]
        current=None
        for raw in r.stdout.splitlines()+["Sink Input #END"]:
            line=raw.strip()
            m=re.match(r"Sink Input #(.+)",line)
            if m:
                if current and current.get("sink") == sink_index:
                    desc=" ".join([
                        current.get("name",""),
                        current.get("binary",""),
                        current.get("appid",""),
                        current.get("media",""),
                    ]).lower()
                    entries.append(desc)
                current={"sink":None,"name":"","binary":"","appid":"","media":""}
                continue
            if current is None:
                continue
            if line.startswith("Sink:"):
                try:
                    current["sink"]=int(line.split(":",1)[1].strip())
                except Exception:
                    pass
            elif line.startswith('application.name = '):
                current["name"]=line.split("=",1)[1].strip().strip('"')
            elif line.startswith('application.process.binary = '):
                current["binary"]=line.split("=",1)[1].strip().strip('"')
            elif line.startswith('application.id = '):
                current["appid"]=line.split("=",1)[1].strip().strip('"')
            elif line.startswith('media.name = '):
                current["media"]=line.split("=",1)[1].strip().strip('"')
        return entries

    @staticmethod
    def _voip_app_kind(desc):
        d=(desc or "").lower()
        if "mumble" in d:
            return "mumble"
        if "teamspeak" in d or "ts3client" in d or "ts3" in d:
            return "teamspeak"
        return ""

    def _confirmed_voip_speakers_now(self, kinds):
        """Query live speaker state for VoIP clients currently on FunkGateway_TX."""
        confirmed=[]
        errors=[]

        if "mumble" in kinds:
            if hasattr(self,"mumble_enabled") and self.mumble_enabled.isChecked():
                try:
                    speakers=self.mumble_local.talking_users()
                    if speakers:
                        confirmed.extend([f"Mumble: {x}" for x in speakers])
                except Exception as e:
                    errors.append(f"Mumble: {e}")
            else:
                errors.append("Mumble-Modul ist ausgeschaltet")

        if "teamspeak" in kinds:
            if hasattr(self,"ts_enabled") and self.ts_enabled.isChecked():
                try:
                    self._configure_teamspeak()
                    speakers=self.ts_client.speakers()
                    if speakers:
                        confirmed.extend([f"TeamSpeak: {x}" for x in speakers])
                except Exception as e:
                    errors.append(f"TeamSpeak: {e}")
            else:
                errors.append("TeamSpeak-Modul ist ausgeschaltet")

        return confirmed,errors

    def _voip_hf_voice_allowed(self):
        """Block pure TS/Mumble client tones when no actual speaker is reported."""
        if not hasattr(self,"voip_hf_voice_filter") or not self.voip_hf_voice_filter.isChecked():
            return True,"Filter aus"

        apps=self._tx_sink_input_apps()
        if not apps:
            return True,"keine Sink-Inputs erkannt"

        kinds=[]
        non_voip=[]
        for desc in apps:
            kind=self._voip_app_kind(desc)
            if kind:
                kinds.append(kind)
            else:
                non_voip.append(desc)

        if non_voip:
            # FunkGateway is intentionally generic. Do not block unrelated apps.
            return True,"Nicht-VoIP-Stream am FunkGateway_TX"
        if not kinds:
            return True,"keine VoIP-Streams erkannt"

        confirmed,errors=self._confirmed_voip_speakers_now(set(kinds))
        if confirmed:
            return True,", ".join(confirmed)

        detail="kein aktiver Sprecher gemeldet"
        if errors:
            detail += " (" + "; ".join(errors) + ")"
        return False,detail

    def on_audio_activity(self,active):
        if hasattr(self,"parrot_enabled") and self.parrot_enabled.isChecked():
            # Fremdes VoIP darf weder eine laufende Papagei-Aufnahme noch die
            # Warte-/Wiedergabephase unterbrechen. Interne Papagei-/Baken-Audios
            # bleiben erlaubt.
            internal_parrot_audio = self.tx_source_hint in ("parrot","beacon")
            block_external = bool(self.parrot_mute_voip.isChecked() or self.parrot_cycle_active)
            if active and block_external and not internal_parrot_audio:
                self.outgoing_audio_active=False
                if self.diagnostic_mode.isChecked():
                    self.log("Papagei: externes VoIP→HF während Papageizyklus blockiert.")
                return
        self.outgoing_audio_active=bool(active)
        if self.mumble_room_guard_until and time.monotonic() < self.mumble_room_guard_until:
            if self.ptt and not self.protection_announcement_busy:
                self.set_ptt(False)
            return
        if self.protection_announcement_busy:
            return
        if self.protection_muted:
            if self.ptt: self.set_ptt(False)
            return
        if self.roger_busy:
            # Keep PTT under Rogerbeep control. If computer audio starts during
            # the beep, _finish_roger leaves PTT keyed for that audio.
            return

        if active:
            allowed,detail=self._voip_hf_voice_allowed()
            if not allowed:
                if self.ptt:
                    self.set_ptt(False)
                now=time.monotonic()
                if (self.voip_hf_last_decision != detail
                        or now-self.voip_hf_last_block_log >= 10.0):
                    self.log("VoIP-HF-Sprachfilter: Audio blockiert – " + detail + ".")
                    self.voip_hf_last_block_log=now
                    self.voip_hf_last_decision=detail
                return
            self.voip_hf_last_decision=""
            self.active_tx_kind=self.tx_source_hint or "voip"
        self.set_ptt(active)

    def on_tx_clipping(self,percent):
        percent=int(percent)
        self.tx_clip_label.setText(f"TX Clipping: {percent} %")
        if percent > 0:
            self.tx_clip_label.setStyleSheet("font-weight: bold;")
        else:
            self.tx_clip_label.setStyleSheet("")

    def choose_roger_wav(self):
        p,_=QFileDialog.getOpenFileName(self,"Rogerbeep-WAV wählen","","WAV (*.wav)")
        if p:
            self.roger_wav.setText(p); self.save_cfg()

    def _set_big_rx_status(self,active,blocked=False):
        # A protection state has priority over the ordinary RX/free display.
        # This avoids the misleading situation where the start page says
        # "FUNK KANAL FREI" although the gateway is intentionally still muted.
        if self.protection_muted:
            if self.protection_reason == "Dauer-RX":
                if active:
                    text="STÖRUNG WEITERHIN VORHANDEN"
                    border="#9b1c1c"
                elif self.protection_waiting_for_rx_free and self.protection_rx_free_since is not None:
                    text="PRÜFE, OB STÖRUNG BEENDET IST …"
                    border="#8a6d1d"
                else:
                    text="STÖRUNG NOCH NICHT GEKLÄRT"
                    border="#8a6d1d"
            elif self.protection_reason == "Störungsraum":
                text="GATEWAY IM STÖRUNGSRAUM"
                border="#8a6d1d"
            else:
                text="SCHUTZ AKTIV – GATEWAY GEMUTET"
                border="#8a6d1d"
            self.funk_rx_big.setText(text)
            self.funk_rx_big.setStyleSheet(
                f"font-size: 25px; font-weight: bold; padding: 12px; "
                f"border: 3px solid {border}; border-radius: 8px;"
            )
            return
        if blocked:
            self.funk_rx_big.setText("FUNK RX SPERRZEIT")
            self.funk_rx_big.setStyleSheet("font-size: 28px; font-weight: bold; padding: 12px; border: 2px solid #8a6d1d; border-radius: 8px;")
        elif active:
            self.funk_rx_big.setText("FUNKEMPFANG AKTIV")
            self.funk_rx_big.setStyleSheet("font-size: 28px; font-weight: bold; padding: 12px; border: 3px solid #b36b00; border-radius: 8px;")
        else:
            self.funk_rx_big.setText("FUNK KANAL FREI")
            self.funk_rx_big.setStyleSheet("font-size: 28px; font-weight: bold; padding: 12px; border: 2px solid #555; border-radius: 8px;")

    def on_rx_db_level(self, db):
        self.rx_last_db=float(db)
        self.rx_db_label.setText(f"RX Pegel: {db:.1f} dBFS")
        # A level above the protection-free threshold invalidates an in-progress
        # safe-unmute free period even if RX briefly reported "frei".
        if (self.protection_waiting_for_rx_free and self.protection_muted and
                self.protection_reason in ("Dauer-RX","Selbstrücklauf") and
                self.rx_last_db > self.protect_free_threshold.value()):
            self.protection_rx_free_since=None
            self._set_big_rx_status(bool(self.rx_was_active))

    def _return_guard_tick(self,now):
        if not self.return_guard_muted:
            return
        if self.return_guard_candidate:
            # Ein innerhalb des Schutzfensters begonnener RX bleibt bis zu seinem
            # tatsächlichen Ende stumm, auch wenn die Zeit inzwischen abgelaufen ist.
            return
        if now >= self.return_guard_until:
            self.return_guard_muted=False
            self._refresh_rx_forward_mute()
            if self.diagnostic_mode.isChecked():
                self.log("Selbstrücklauf-Schutz beendet: kein RX innerhalb des Schutzfensters.")

    def _register_return_event(self,duration_ms):
        now=time.monotonic()
        window=self.return_window_s.value()
        self.return_events=[t for t in self.return_events if now-t <= window]
        self.return_events.append(now)
        count=len(self.return_events)
        self.log(f"Selbstrücklauf erkannt: RX-Dauer {duration_ms:.0f} ms – Ereignis {count}/{self.return_count_limit.value()} innerhalb {window} s.")
        if self.return_escalate.isChecked() and count >= self.return_count_limit.value() and not self.protection_muted:
            self.return_events.clear()
            self.mute_gateway("Selbstrücklauf",self.protect_mute_wav.text())
            if self.return_move_rooms.isChecked():
                ts_moved=self._auto_move_to_disturbance_room()
                mumble_moved=self._auto_move_to_mumble_disturbance_room()
                if ts_moved or mumble_moved:
                    self.protection_last_room_announcement=now
                    if self.protect_room_wav.text().strip():
                        self.play_protection_announcement(self.protect_room_wav.text(),"Gateway im Störungsraum")
            if self.protect_auto_unmute.isChecked():
                self.protection_unmute_due=now+self.protect_unmute_seconds.value()
                self.protection_waiting_for_rx_free=self.protect_require_rx_free.isChecked()

    def _announce_lost_passage(self):
        p=self.return_lost_wav.text().strip()
        if not p:
            self.log("Verlorener Durchgang: keine Hinweis-WAV gewählt; keine HF-Ansage gesendet.")
            return
        if self.rx_was_active or self.tx or self.outgoing_audio_active:
            QTimer.singleShot(500,self._announce_lost_passage)
            return
        self.log("Verlorener Durchgang: Wiederholungsansage wird über HF gesendet.")
        self.play_protection_announcement(p,"Durchgang nicht übertragen – bitte wiederholen")

    def _parrot_busy(self):
        return bool(self.parrot_recording or self.parrot_playing or self.parrot_beacon_in_progress or self.tx or self.outgoing_audio_active)

    def _parrot_channel_busy(self):
        return bool(self.rx_was_active or self._parrot_busy() or self.protection_muted or self.protection_announcement_busy or self.roger_busy or self.return_guard_muted)

    def _parrot_mode_toggled(self,enabled):
        # Recalculate the whole FunkGateway_TX.monitor -> radio bridge first.
        # Papagei isolation must be active before any acknowledgement/replay.
        self._set_tx_forward_muted(False)
        if enabled:
            self._ensure_parrot_capture()
            self._sync_parrot_voip_playback_mute()
            with self.parrot_capture_lock:
                self.parrot_prebuffer.clear()

            # If Papagei is enabled by *91# while that same RF carrier is still
            # active, ignore the rest of that control transmission completely.
            if getattr(self,"dtmf_session_active",False) or self.rx_was_active:
                self.dtmf_parrot_wait_rx_free=True
                self.log("Papagei: Aktivierung per DTMF – warte bis Funkende; Steuerdurchgang wird nicht aufgenommen.")
            else:
                self.dtmf_parrot_wait_rx_free=False
        else:
            self.dtmf_parrot_wait_rx_free=False
            self._stop_parrot_capture()
            self._sync_parrot_voip_playback_mute()
            # Now that Papagei is off, release the mixed TX bridge unless a
            # protection state still requires it to remain muted.
            self._set_tx_forward_muted(False)

    def _ensure_parrot_capture(self):
        """Start one continuous raw RX capture used as the Papagei prebuffer."""
        if not hasattr(self,"parrot_enabled") or not self.parrot_enabled.isChecked():
            return False

        src=self.rx_source.currentData() if hasattr(self,"rx_source") else None
        if not src:
            src=self.rx_source.currentText().strip() if hasattr(self,"rx_source") else ""
        if not src:
            self.log("Papagei: RX-Vorlaufpuffer wartet – keine RX-Quelle gewählt.")
            return False

        if self.parrot_capture_proc and self.parrot_capture_proc.poll() is None:
            if self.parrot_capture_source == src:
                return True
            self._stop_parrot_capture()

        self.parrot_capture_stop.clear()
        self.parrot_capture_source=src
        with self.parrot_capture_lock:
            self.parrot_prebuffer.clear()

        try:
            proc=subprocess.Popen(
                ["parec",f"--device={src}","--format=s16le","--rate=48000","--channels=1"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0
            )
            self.parrot_capture_proc=proc
        except Exception as e:
            self.parrot_capture_proc=None
            self.log(f"Papagei: RX-Vorlaufpuffer konnte nicht gestartet werden: {e}")
            return False

        def worker():
            proc_local=proc
            try:
                while not self.parrot_capture_stop.is_set() and proc_local.poll() is None:
                    chunk=proc_local.stdout.read(4096)
                    if not chunk:
                        if proc_local.poll() is not None:
                            break
                        continue
                    with self.parrot_capture_lock:
                        # Während eigener Aussendungen keinen Rücklauf in den
                        # Vorlaufpuffer aufnehmen.
                        if (
                            not self.parrot_playing
                            and not self.parrot_beacon_in_progress
                            and not self.outgoing_audio_active
                            and not getattr(self,"dtmf_session_active",False)
                            and not getattr(self,"dtmf_parrot_wait_rx_free",False)
                            and not self.tx
                        ):
                            self.parrot_prebuffer.extend(chunk)
                            excess=len(self.parrot_prebuffer)-self.parrot_capture_max_bytes
                            if excess > 0:
                                del self.parrot_prebuffer[:excess]

                        if (self.parrot_recording or self.parrot_guard_buffering) and self.parrot_raw_handle:
                            try:
                                self.parrot_raw_handle.write(chunk)
                            except Exception:
                                pass
            except Exception:
                pass

        self.parrot_capture_thread=threading.Thread(
            target=worker,
            name="FunkGateway-Papagei-RX-Puffer",
            daemon=True
        )
        self.parrot_capture_thread.start()
        self.log(f"Papagei: RX-Vorlaufpuffer aktiv ({src}, max. 5 s).")
        return True

    def _stop_parrot_capture(self):
        self.parrot_capture_stop.set()

        proc=self.parrot_capture_proc
        self.parrot_capture_proc=None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                try: proc.kill()
                except Exception: pass

        th=self.parrot_capture_thread
        self.parrot_capture_thread=None
        if th and th.is_alive():
            try: th.join(timeout=1)
            except Exception: pass

        with self.parrot_capture_lock:
            try:
                if self.parrot_raw_handle and self.parrot_guard_buffering:
                    self.parrot_raw_handle.close()
            except Exception:
                pass
            if self.parrot_guard_buffering:
                self.parrot_raw_handle=None
            self.parrot_prebuffer.clear()
        self.parrot_guard_buffering=False
        self.parrot_guard_prebuffer_bytes=0
        self.parrot_capture_source=None

    def _parrot_prebuffer_snapshot(self):
        wanted_ms=self.parrot_rx_prebuffer_ms.value()
        wanted_bytes=int(96000*wanted_ms/1000)
        if wanted_bytes <= 0:
            return b""
        with self.parrot_capture_lock:
            return bytes(self.parrot_prebuffer[-wanted_bytes:])

    def _parrot_begin_guard_candidate(self,now):
        """Buffer an RX that starts inside the return-guard window."""
        if not self._ensure_parrot_capture():
            self.log("Papagei: Schutzfenster-RX erkannt, aber RX-Capture ist nicht verfügbar.")
            return False

        for p in (self.parrot_raw_file,self.parrot_temp_file):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

        pre=self._parrot_prebuffer_snapshot()
        try:
            self.parrot_raw_handle=open(self.parrot_raw_file,"wb")
            if pre:
                self.parrot_raw_handle.write(pre)
                self.parrot_raw_handle.flush()
        except Exception as e:
            self.parrot_raw_handle=None
            self.log(f"Papagei: Schutzfenster-Puffer konnte nicht geöffnet werden: {e}")
            return False

        self.parrot_guard_buffering=True
        self.parrot_guard_prebuffer_bytes=len(pre)
        self.return_guard_candidate=True
        self.return_guard_rx_started=now
        self.rx_was_active=True
        self.rx_active_since=now
        self.ts_commander_wanted=False
        self.rx_status.setText("● PAPAGEI PRÜFT RÜCKLAUF")
        self._set_big_rx_status(False,blocked=True)

        delta=(now-(self.return_guard_tx_ended or now))*1000
        self.log(
            f"Papagei: RX innerhalb Selbstrücklauf-Schutz (+{delta:.0f} ms) – "
            f"wird vorsorglich gepuffert ({len(pre)/96:.0f} ms Vorlauf)."
        )
        return True

    def _parrot_discard_guard_candidate(self):
        self.parrot_guard_buffering=False
        with self.parrot_capture_lock:
            try:
                if self.parrot_raw_handle:
                    self.parrot_raw_handle.flush()
                    self.parrot_raw_handle.close()
            except Exception:
                pass
            self.parrot_raw_handle=None
        try:
            if self.parrot_raw_file.exists():
                self.parrot_raw_file.unlink()
        except Exception:
            pass
        self.parrot_guard_prebuffer_bytes=0

    def _parrot_promote_guard_candidate(self,now):
        """Turn a long return-guard candidate into a normal Papagei recording."""
        if not self.return_guard_candidate or not self.parrot_guard_buffering:
            return False

        started=self.return_guard_rx_started or now
        duration_ms=(now-started)*1000
        if duration_ms < self.return_real_passage_ms.value():
            return False

        # The already buffered candidate file becomes the live Papagei recording.
        self.return_guard_candidate=False
        self.return_guard_rx_started=None
        self.return_guard_muted=False
        self._refresh_rx_forward_mute()

        self.parrot_guard_buffering=False
        self.parrot_recording=True
        self.parrot_cycle_active=True
        self.parrot_rx_started=started
        self.roger_pending_token += 1

        self.rx_was_active=True
        self.rx_active_since=started
        self.rx_status.setText("● PAPAGEI NIMMT AUF")
        self._set_big_rx_status(True)
        self.ts_commander_wanted=False

        buffered_bytes=0
        try:
            if self.parrot_raw_file.exists():
                buffered_bytes=self.parrot_raw_file.stat().st_size
        except Exception:
            pass

        self.log(
            f"Papagei: Schutzfenster-RX ist echter Funkdurchgang "
            f"({duration_ms:.0f} ms) – Puffer wird zur Aufnahme übernommen "
            f"({buffered_bytes} Byte, Anfang bleibt erhalten)."
        )
        return True

    def _abort_parrot_recording_for_dtmf_ack(self):
        """Drop any stale Papagei capture so a mode acknowledgement has priority."""
        if not (self.parrot_recording or self.parrot_guard_buffering):
            with self.parrot_capture_lock:
                self.parrot_prebuffer.clear()
            return

        self.parrot_recording=False
        self.parrot_guard_buffering=False
        self.parrot_cycle_active=False
        self.parrot_rx_started=None
        self.return_guard_candidate=False
        self.return_guard_rx_started=None

        with self.parrot_capture_lock:
            try:
                if self.parrot_raw_handle:
                    self.parrot_raw_handle.flush()
                    self.parrot_raw_handle.close()
            except Exception:
                pass
            self.parrot_raw_handle=None
            self.parrot_prebuffer.clear()

        for p in (self.parrot_raw_file,self.parrot_temp_file):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

        self.log("Papagei: laufende/stale Aufnahme für DTMF-Vollzugsmeldung verworfen.")

    def _parrot_start_recording(self):
        if self.parrot_recording or self.parrot_playing or self.parrot_beacon_in_progress:
            return

        if not self._ensure_parrot_capture():
            self.log("Papagei: Aufnahme abgebrochen – RX-Vorlaufpuffer nicht verfügbar.")
            return

        try:
            if self.parrot_raw_file.exists():
                self.parrot_raw_file.unlink()
        except Exception:
            pass
        try:
            if self.parrot_temp_file.exists():
                self.parrot_temp_file.unlink()
        except Exception:
            pass

        pre=self._parrot_prebuffer_snapshot()

        try:
            self.parrot_raw_handle=open(self.parrot_raw_file,"wb")
            if pre:
                self.parrot_raw_handle.write(pre)
                self.parrot_raw_handle.flush()
        except Exception as e:
            self.parrot_raw_handle=None
            self.log(f"Papagei: Aufnahme konnte nicht gestartet werden: {e}")
            return

        self.parrot_recording=True
        self.parrot_cycle_active=True
        # Alle eventuell noch geplanten normalen Rogerbeeps ungültig machen.
        self.roger_pending_token += 1
        self.parrot_rx_started=time.monotonic()
        self.log(
            f"Papagei: RX begonnen – Aufnahme gestartet "
            f"(Vorlaufpuffer {len(pre)/96:.0f} ms / {len(pre)} Byte)."
        )

    def _parrot_stop_recording(self,reason="Funkende"):
        if not self.parrot_recording:
            return

        self.parrot_recording=False
        dur=(time.monotonic()-(self.parrot_rx_started or time.monotonic()))
        self.parrot_rx_started=None

        # Der kontinuierliche parec-Prozess bleibt für den nächsten Vorlaufpuffer
        # aktiv. Nur die aktuelle Durchgangsdatei wird geschlossen.
        with self.parrot_capture_lock:
            try:
                if self.parrot_raw_handle:
                    self.parrot_raw_handle.flush()
                    self.parrot_raw_handle.close()
            except Exception:
                pass
            self.parrot_raw_handle=None

        self.log(f"Papagei: Aufnahme beendet ({reason}) – erkannte RX-Dauer {dur:.1f} s.")

        try:
            raw=self.parrot_raw_file.read_bytes() if self.parrot_raw_file.exists() else b""
            if len(raw) < 9600:
                self.parrot_cycle_active=False
                self.log(f"Papagei: Aufnahme zu kurz/leer ({len(raw)} Byte) – keine Rücksendung.")
                return
            with wave.open(str(self.parrot_temp_file),"wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(48000)
                wf.writeframes(raw)
            self.log(
                f"Papagei: WAV bereit – {len(raw)} Byte Audiodaten "
                f"(inkl. bis zu {self.parrot_rx_prebuffer_ms.value()} ms RX-Vorlauf)."
            )
        except Exception as e:
            self.parrot_cycle_active=False
            self.log(f"Papagei: WAV-Erstellung fehlgeschlagen: {e}")
            return
        finally:
            try:
                if self.parrot_raw_file.exists():
                    self.parrot_raw_file.unlink()
            except Exception:
                pass

        QTimer.singleShot(self.parrot_delay_ms.value(),self._parrot_playback)

    def _parrot_playback(self):
        if not self.parrot_enabled.isChecked():
            self.parrot_cycle_active=False
            return
        if self.rx_was_active or self.tx or self.outgoing_audio_active or self.protection_announcement_busy:
            QTimer.singleShot(250,self._parrot_playback)
            return
        if not self.parrot_temp_file.exists():
            self.parrot_cycle_active=False
            self.log("Papagei: Wiedergabe abgebrochen – WAV-Datei fehlt.")
            return

        self.parrot_playing=True
        self.parrot_cycle_active=True
        self.roger_pending_token += 1
        self.active_tx_kind="parrot"
        with self.parrot_capture_lock:
            self.parrot_prebuffer.clear()

        try:
            self.set_ptt(True)
            lead=self.parrot_lead_ms.value()
            self.log(f"Papagei: PTT EIN – Vorlauf {lead} ms vor Wiedergabe.")
        except Exception as e:
            self.parrot_playing=False
            self.parrot_cycle_active=False
            self.log(f"Papagei: PTT konnte nicht eingeschaltet werden: {e}")
            return

        def finish_cycle():
            # PTT bleibt bis nach optionalem Rogerbeep und Nachlauf eingeschaltet.
            def release_ptt():
                try:
                    if self.tx:
                        self.set_ptt(False)
                except Exception as e:
                    self.log(f"Papagei: PTT AUS fehlgeschlagen: {e}")
                self.parrot_playing=False
                self.parrot_cycle_active=False
                self.log("Papagei: bereit.")

            QTimer.singleShot(max(100,self.hang.value()),release_ptt)

        def play_inline_roger():
            if not self.parrot_roger.isChecked():
                finish_cycle()
                return
            try:
                sink=self.target_sink.currentData()
                if not sink:
                    self.log("Papagei: Rogerbeep übersprungen – kein Funkgeräte-Ausgang gewählt.")
                    finish_cycle()
                    return
                path=self._prepare_roger_file()
                volume=max(1,min(100,self.roger_volume.value()))
                pa_volume=int(65536*volume/100)
                self.roger_busy=True
                proc_r=subprocess.Popen(
                    ["paplay",f"--device={sink}",f"--volume={pa_volume}",str(path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.log(f"Papagei: Rogerbeep in gleicher PTT gestartet: {self.roger_type.currentText()}")
            except Exception as e:
                self.roger_busy=False
                self.log(f"Papagei: Rogerbeep fehlgeschlagen: {e}")
                finish_cycle()
                return

            def poll_roger():
                if proc_r.poll() is None:
                    QTimer.singleShot(50,poll_roger)
                    return
                self.roger_busy=False
                self.last_roger_time=time.monotonic()
                self.rx_ignore_until=self.last_roger_time+(self.rx_ignore_after_roger.value()/1000.0)
                self.log("Papagei: Rogerbeep in gleicher PTT beendet.")
                finish_cycle()
            QTimer.singleShot(50,poll_roger)

        def start_audio():
            if not self.parrot_enabled.isChecked():
                self.parrot_playing=False
                self.parrot_cycle_active=False
                try: self.set_ptt(False)
                except Exception: pass
                return
            try:
                proc=self.play_to_virtual(self.parrot_temp_file,"parrot")
                self.log("Papagei: Wiedergabe gestartet.")
            except Exception as e:
                self.parrot_playing=False
                self.parrot_cycle_active=False
                self.log(f"Papagei: Wiedergabe fehlgeschlagen: {e}")
                try: self.set_ptt(False)
                except Exception: pass
                return

            def done():
                if proc.poll() is None:
                    QTimer.singleShot(100,done)
                    return
                self.log(f"Papagei: Wiedergabe beendet (paplay Exit-Code {proc.returncode}).")
                play_inline_roger()
            QTimer.singleShot(100,done)

        QTimer.singleShot(self.parrot_lead_ms.value(),start_audio)

    def _queue_parrot_beacon(self):
        if not self.parrot_pending_beacon:
            self.parrot_pending_beacon=True
            self.parrot_beacon_free_since=None
            self.log("Papageibake fällig – wartet auf freien Funkkanal.")

    def _parrot_send_beacon(self):
        if not self.parrot_enabled.isChecked() or not self.parrot_beacon_enabled.isChecked():
            self.parrot_pending_beacon=False
            return
        p=self.parrot_beacon_file.text().strip()
        if not p:
            self.log("Papageibake fällig, aber keine WAV-Datei gewählt.")
            return
        if self._parrot_channel_busy():
            self._queue_parrot_beacon()
            return

        self.parrot_beacon_in_progress=True
        self.parrot_pending_beacon=False
        self.parrot_beacon_free_since=None
        self.roger_pending_token += 1
        self.active_tx_kind="beacon"
        with self.parrot_capture_lock:
            self.parrot_prebuffer.clear()

        try:
            self.set_ptt(True)
            lead=self.parrot_beacon_lead_ms.value()
            self.log(f"Papageibake: PTT EIN – Vorlauf {lead} ms.")
        except Exception as e:
            self.parrot_beacon_in_progress=False
            self.log(f"Papageibake: PTT konnte nicht eingeschaltet werden: {e}")
            return

        def start_beacon_audio():
            if not self.parrot_enabled.isChecked():
                self.parrot_beacon_in_progress=False
                try: self.set_ptt(False)
                except Exception: pass
                return
            try:
                proc=self.play_to_virtual(p,"beacon")
                self.parrot_beacon_proc=proc
                self.log(f"Papageibake gestartet: {Path(p).name}")
            except Exception as e:
                self.parrot_beacon_in_progress=False
                self.parrot_beacon_proc=None
                self.log(f"Papageibake fehlgeschlagen: {e}")
                try: self.set_ptt(False)
                except Exception: pass
                return

            def poll():
                if proc.poll() is None:
                    QTimer.singleShot(100,poll)
                    return
                self.parrot_beacon_proc=None
                self.log("Papageibake Audio beendet – PTT-Nachlauf läuft.")

                def finish():
                    try:
                        if self.tx:
                            self.set_ptt(False)
                    except Exception as e:
                        self.log(f"Papageibake: PTT AUS fehlgeschlagen: {e}")
                    self.parrot_beacon_in_progress=False
                    self.parrot_last_beacon=time.monotonic()
                    self.log(f"Papageibake beendet – Intervall neu gestartet: {self.parrot_beacon_interval.value()} Minuten.")
                tail=max(0,self.parrot_beacon_tail_ms.value())
                self.log(f"Papageibake: Audio vollständig beendet – PTT-Nachlauf {tail} ms.")
                QTimer.singleShot(tail,finish)

            QTimer.singleShot(100,poll)

        QTimer.singleShot(self.parrot_beacon_lead_ms.value(),start_beacon_audio)

    def _parrot_tick(self,now):
        if not hasattr(self,"parrot_enabled") or not self.parrot_enabled.isChecked():
            return

        # Capture-Wächter: Stirbt parec während einer laufenden Aufnahme,
        # wird der Durchgang verworfen statt als scheinbar vollständige WAV
        # zurückgesendet. Neustart erfolgt erst im freien Zustand.
        capture_dead = bool(
            self.parrot_capture_proc is not None
            and self.parrot_capture_proc.poll() is not None
        )
        if capture_dead:
            rc=self.parrot_capture_proc.returncode
            self.parrot_capture_proc=None
            if self.parrot_recording or self.parrot_guard_buffering:
                was_guard_candidate=self.parrot_guard_buffering and not self.parrot_recording
                self.parrot_recording=False
                self.parrot_guard_buffering=False
                self.parrot_cycle_active=False
                self.parrot_rx_started=None
                self.return_guard_candidate=False
                self.return_guard_rx_started=None
                with self.parrot_capture_lock:
                    try:
                        if self.parrot_raw_handle:
                            self.parrot_raw_handle.close()
                    except Exception:
                        pass
                    self.parrot_raw_handle=None
                try:
                    if self.parrot_raw_file.exists():
                        self.parrot_raw_file.unlink()
                except Exception:
                    pass
                if was_guard_candidate:
                    self.log(f"Papagei: RX-Capture während Schutzfenster-Pufferung ausgefallen (Exit-Code {rc}) – Kandidat verworfen.")
                else:
                    self.log(f"Papagei: RX-Capture während Aufnahme ausgefallen (Exit-Code {rc}) – Durchgang verworfen.")
            elif not self.parrot_playing and not self.parrot_beacon_in_progress:
                self.log(f"Papagei: RX-Vorlaufpuffer beendet (Exit-Code {rc}) – Neustart wird versucht.")
            self.parrot_capture_fault_logged=True

        if (self.parrot_capture_proc is None
                and not self.parrot_recording
                and not self.parrot_playing
                and not self.parrot_beacon_in_progress):
            if self._ensure_parrot_capture():
                self.parrot_capture_fault_logged=False
        if self.return_guard_candidate and self.parrot_guard_buffering and self.return_guard_rx_started is not None:
            self._parrot_promote_guard_candidate(now)

        if self.parrot_recording and self.parrot_rx_started is not None:
            if now-self.parrot_rx_started >= self.parrot_max_seconds.value():
                self._parrot_stop_recording("maximale Aufnahmedauer erreicht")
        if self.parrot_beacon_enabled.isChecked() and not self.parrot_pending_beacon and not self.parrot_beacon_in_progress:
            if now-self.parrot_last_beacon >= self.parrot_beacon_interval.value()*60:
                self._queue_parrot_beacon()
        if self.parrot_pending_beacon and not self.parrot_beacon_in_progress:
            if self._parrot_channel_busy():
                self.parrot_beacon_free_since=None
            else:
                if self.parrot_beacon_free_since is None:
                    self.parrot_beacon_free_since=now
                    self.log(f"Papageibake: Kanal frei – Freiwartezeit {self.parrot_beacon_free_wait_ms.value()} ms läuft.")
                elif (now-self.parrot_beacon_free_since)*1000 >= self.parrot_beacon_free_wait_ms.value():
                    self._parrot_send_beacon()

    def on_rx_activity(self,active):
        now=time.monotonic()

        if hasattr(self,"parrot_enabled") and self.parrot_enabled.isChecked():
            # *91# may enable Papagei while the same RF carrier is still up.
            # IMPORTANT: this release gate must run before the pending-ACK gate.
            # Otherwise the control carrier would remain marked active forever
            # and "Papagei EIN" could never be transmitted.
            if getattr(self,"dtmf_parrot_wait_rx_free",False):
                if active:
                    self.rx_was_active=True
                    self.rx_active_since=now
                    self.ts_commander_wanted=False
                    self.rx_status.setText("● PAPAGEI WARTET AUF FUNKENDE")
                    self._set_big_rx_status(False,blocked=True)
                    return

                self.dtmf_parrot_wait_rx_free=False
                self.dtmf_control_rx_active=False
                self.rx_was_active=False
                self.rx_active_since=None
                self.ts_commander_wanted=False
                with self.parrot_capture_lock:
                    self.parrot_prebuffer.clear()
                self.rx_status.setText("● PAPAGEI WARTET AUF BESTÄTIGUNG" if getattr(self,"dtmf_mode_ack_pending",False) else "● PAPAGEI WARTET")
                self._set_big_rx_status(False)
                self.log("Papagei: DTMF-Steuerdurchgang beendet – Kanal für Vollzugsmeldung frei.")
                return

            # A pending mode confirmation has priority.  Do not start a new
            # Papagei recording before "Papagei aktiv" has actually gone out.
            if getattr(self,"dtmf_mode_ack_pending",False):
                if active:
                    self.rx_was_active=True
                    self.rx_active_since=now
                    self.ts_commander_wanted=False
                    self.rx_status.setText("● PAPAGEI WARTET AUF BESTÄTIGUNG")
                    self._set_big_rx_status(False,blocked=True)
                else:
                    self.rx_was_active=False
                    self.rx_active_since=None
                    self.ts_commander_wanted=False
                    self.rx_status.setText("● PAPAGEI WARTET AUF BESTÄTIGUNG")
                    self._set_big_rx_status(False)
                return

            # Internal acknowledgement audio must never become Papagei input.
            if self.outgoing_audio_active:
                return

            # Eigene Papagei-/Roger-Aussendungen dürfen nach PTT AUS nicht sofort
            # als neuer Papagei-Durchgang gelten. Anders als zuvor wird ein RX
            # im Schutzfenster aber gepuffert, damit ein echter Funkdurchgang
            # später vollständig übernommen werden kann.
            if active and self.return_guard_muted and not self.return_guard_candidate:
                if now <= self.return_guard_until:
                    if self._parrot_begin_guard_candidate(now):
                        return
                    # Wenn die Pufferung ausnahmsweise nicht möglich ist,
                    # bleibt die alte Schutzwirkung erhalten.
                    self.return_guard_candidate=True
                    self.return_guard_rx_started=now
                    self.rx_was_active=True
                    self.ts_commander_wanted=False
                    self.log("Papagei: RX im Schutzfenster – Pufferung fehlgeschlagen, Durchgang wird nur vermessen.")
                    return
                self.return_guard_muted=False
                self._refresh_rx_forward_mute()

            if active and self.return_guard_candidate:
                self.rx_was_active=True
                self.ts_commander_wanted=False
                # Bei einem langen Kandidaten wird normalerweise bereits der
                # Timer hochstufen. Diese Prüfung macht das Verhalten auch bei
                # weiteren RX-Events deterministisch.
                self._parrot_promote_guard_candidate(now)
                return

            if (not active) and self.return_guard_candidate:
                started=self.return_guard_rx_started or now
                duration=(now-started)*1000
                buffered=self.parrot_guard_buffering
                self.return_guard_candidate=False
                self.return_guard_rx_started=None
                self.return_guard_muted=False
                self._refresh_rx_forward_mute()
                self.rx_was_active=False
                self.rx_active_since=None
                self.ts_commander_wanted=False
                self.rx_status.setText("● PAPAGEI WARTET")
                self._set_big_rx_status(False)

                if buffered:
                    self._parrot_discard_guard_candidate()

                if duration <= self.return_max_tail_ms.value():
                    self.log(f"Papagei: kurzer Schutzfenster-RX beendet ({duration:.0f} ms) – als Selbstrücklauf verworfen.")
                    self._register_return_event(duration)
                elif duration >= self.return_real_passage_ms.value():
                    # Dieser Fall sollte nur auftreten, falls der Tick während
                    # des Durchgangs nicht rechtzeitig zur Hochstufung kam.
                    self.log(
                        f"Papagei: echter Funkdurchgang im Schutzfenster endete nach {duration:.0f} ms, "
                        f"konnte aber nicht mehr hochgestuft werden."
                    )
                else:
                    self.log(f"Papagei: RX im Schutzfenster beendet ({duration:.0f} ms) – Übergangsbereich, verworfen.")
                return

            # Im Papageibetrieb übernimmt der Papagei die RX-Verarbeitung komplett.
            # Dadurch wird der normale RX-Rogerbeep nicht zusätzlich ausgelöst.
            if self.parrot_playing or self.parrot_beacon_in_progress:
                return

            if active:
                self.rx_was_active=True
                self.rx_active_since=now
                self.rx_status.setText("● PAPAGEI NIMMT AUF")
                self._set_big_rx_status(True)
                self.ts_commander_wanted=False
                if not self.parrot_recording:
                    self._parrot_start_recording()
                return

            self.rx_was_active=False
            self.rx_active_since=None
            self.rx_status.setText("● PAPAGEI WARTET")
            self._set_big_rx_status(False)
            self.ts_commander_wanted=False
            if self.parrot_recording:
                self._parrot_stop_recording("Funkende")
            return

        # A DTMF control carrier is not a normal voice QSO.  When the
        # carrier drops after *...#, release the channel explicitly and do not
        # schedule the normal Rogerbeep.  The Vollzugsmeldung is already the
        # acknowledgement for this control transmission.
        if (not active) and getattr(self,"dtmf_control_rx_active",False):
            self.dtmf_control_rx_active=False
            self.rx_was_active=False
            self.rx_active_since=None
            self.ts_commander_wanted=False
            self.roger_pending_token += 1
            self.rx_status.setText("● FUNK RX FREI")
            self._set_big_rx_status(False)
            self.log("DTMF-Steuerdurchgang beendet – kein normaler Rogerbeep; Kanal für Vollzugsmeldung frei.")
            return

        # Selbstrücklauf: Nur RX, das innerhalb des Schutzfensters BEGINNT,
        # wird blockiert. Später beginnende Funkdurchgänge bleiben unangetastet.
        if active and self.return_guard_muted and not self.return_guard_candidate:
            if now <= self.return_guard_until:
                self.return_guard_candidate=True
                self.return_guard_rx_started=now
                self._refresh_rx_forward_mute()
                self.rx_was_active=True
                self.rx_status.setText("● FUNK RX / RÜCKLAUFSCHUTZ")
                self._set_big_rx_status(False,blocked=True)
                self.ts_commander_wanted=False
                delta=(now-(self.return_guard_tx_ended or now))*1000
                self.log(f"RX innerhalb Selbstrücklauf-Schutz begonnen (+{delta:.0f} ms) – kompletter Durchgang wird vermessen.")
                return
            else:
                self.return_guard_muted=False
                self._refresh_rx_forward_mute()

        if active and self.return_guard_candidate:
            # Folgemeldungen während desselben blockierten RX-Durchgangs.
            self.rx_was_active=True
            self.ts_commander_wanted=False
            return

        if (not active) and self.return_guard_candidate:
            started=self.return_guard_rx_started or now
            duration=(now-started)*1000
            self.return_guard_candidate=False
            self.return_guard_rx_started=None
            self.return_guard_muted=False
            self._refresh_rx_forward_mute()
            self.rx_was_active=False
            self.rx_active_since=None
            self.ts_commander_wanted=False
            self.rx_status.setText("● FUNK RX FREI")
            self._set_big_rx_status(False)
            if duration <= self.return_max_tail_ms.value():
                self._register_return_event(duration)
            elif duration >= self.return_real_passage_ms.value():
                self.log(f"Echter Funkdurchgang während Selbstrücklauf-Schutz erkannt: {duration:.0f} ms – nicht zu VoIP übertragen.")
                QTimer.singleShot(self.return_repeat_wait_ms.value(),self._announce_lost_passage)
            else:
                self.log(f"RX während Selbstrücklauf-Schutz beendet: {duration:.0f} ms – Übergangsbereich, nicht als Rücklauf gezählt.")
            return

        if self.roger_busy or now < self.rx_ignore_until:
            if hasattr(self,"diagnostic_mode") and self.diagnostic_mode.isChecked():
                self.log("RX-Ereignis während Rogerbeep/Sperrzeit ignoriert.")
            self.rx_was_active=False
            self.rx_active_since=None
            self.rx_status.setText("● FUNK RX SPERRZEIT")
            self._set_big_rx_status(False,blocked=True)
            self.ts_commander_wanted=False
            return
        if active:
            self.protection_rx_free_since=None
            self.roger_pending_token += 1
            self.rx_was_active=True
            if self.rx_active_since is None: self.rx_active_since=now
            self.rx_status.setText("● FUNK RX / SIGNAL")
            self._set_big_rx_status(True)
            self.ts_commander_wanted=True
            if self.diagnostic_mode.isChecked(): self.log("RX erkannt: gültiger Funkdurchgang aktiv.")
            return

        self.rx_status.setText("● FUNK RX FREI")
        self.ts_commander_wanted=False
        self.rx_active_since=None
        # In Dauer-RX safe mode a single "frei" event no longer unlocks the
        # protection. _protection_tick() requires a continuous stable free time.
        if self.protection_waiting_for_rx_free and self.protection_muted and self.protection_reason in ("Dauer-RX","Selbstrücklauf"):
            self.protection_rx_free_since=now
        self._set_big_rx_status(False)
        if not self.rx_was_active:
            return
        self.rx_was_active=False
        if self.diagnostic_mode.isChecked(): self.log("RX beendet: Kanal ist frei.")
        if self.roger_type.currentText() == "Aus":
            return
        self.roger_pending_token += 1
        token=self.roger_pending_token
        delay=self.roger_min_free.value()+self.roger_delay.value()
        if self.diagnostic_mode.isChecked():
            self.log(f"Rogerbeep geplant nach {delay} ms (Frei-Zeit + Verzögerung).")
        QTimer.singleShot(delay, lambda t=token:self._roger_after_delay(t))

    def _roger_after_delay(self,token):
        if hasattr(self,"parrot_enabled") and self.parrot_enabled.isChecked():
            if self.diagnostic_mode.isChecked():
                self.log("Rogerbeep verworfen: Papageibetrieb aktiv.")
            return
        if token != self.roger_pending_token or self.rx_was_active:
            if self.diagnostic_mode.isChecked(): self.log("Rogerbeep verworfen: neues RX-Signal erkannt.")
            return
        now=time.monotonic()
        cooldown=self.roger_cooldown.value()/1000.0
        if cooldown > 0 and self.last_roger_time and now-self.last_roger_time < cooldown:
            if self.diagnostic_mode.isChecked(): self.log("Rogerbeep verworfen: Cooldown noch aktiv.")
            return
        if self.tx or self.roger_busy or not self.bridge or not self.ptt:
            self.log("Rogerbeep übersprungen: Sender/Gateway ist gerade nicht frei.")
            return
        self.send_roger_beep()

    def _prepare_roger_file(self):
        kind=self.roger_type.currentText()
        if kind == "CW K (-.-)":
            make_cw("K",ROGER_FILE,self.roger_wpm.value(),self.roger_freq.value())
            return ROGER_FILE
        if kind == "Kurzer Einzelton":
            make_roger_tone(ROGER_FILE,"single",self.roger_freq.value())
            return ROGER_FILE
        if kind == "Doppelton":
            make_roger_tone(ROGER_FILE,"double",self.roger_freq.value())
            return ROGER_FILE
        if kind == "Eigene WAV-Datei":
            p=Path(self.roger_wav.text().strip())
            if not p.exists():
                raise RuntimeError("Bitte zuerst eine gültige Rogerbeep-WAV auswählen.")
            return p
        raise RuntimeError("Rogerbeep ist ausgeschaltet.")

    def send_roger_beep(self):
        if self.roger_busy:
            return
        sink=self.target_sink.currentData()
        if not sink:
            self.log("Rogerbeep nicht gesendet: kein Funkgeräte-Ausgang gewählt.")
            return
        try:
            path=self._prepare_roger_file()
            self.roger_busy=True
            self.rx_was_active=False
            self.active_tx_kind="roger"
            self.set_ptt(True)
            volume=max(1,min(100,self.roger_volume.value()))
            pa_volume=int(65536*volume/100)
            self.roger_proc=subprocess.Popen([
                "paplay",f"--device={sink}",f"--volume={pa_volume}",str(path)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log(f"Rogerbeep über HF gestartet: {self.roger_type.currentText()}")
            QTimer.singleShot(50,self._poll_roger)
        except Exception as e:
            self.roger_busy=False
            if self.ptt and not self.outgoing_audio_active:
                self.set_ptt(False)
            self.log(f"Rogerbeep-Fehler: {e}")
            self.show_copyable_error("Rogerbeep",str(e))

    def _poll_roger(self):
        if not self.roger_busy:
            return
        if self.roger_proc and self.roger_proc.poll() is None:
            QTimer.singleShot(50,self._poll_roger)
            return
        QTimer.singleShot(120,self._finish_roger)

    def _finish_roger(self):
        if not self.roger_busy:
            return
        self.roger_busy=False
        self.roger_proc=None
        self.last_roger_time=time.monotonic()
        self.rx_ignore_until=self.last_roger_time+(self.rx_ignore_after_roger.value()/1000.0)
        self.rx_was_active=False
        if not self.outgoing_audio_active:
            self.set_ptt(False)
        self.log("Rogerbeep über HF beendet.")

    def test_roger_beep(self):
        if self.roger_type.currentText() == "Aus":
            QMessageBox.information(self,"Rogerbeep","Bitte zuerst einen Rogerbeep-Typ auswählen.")
            return
        try:
            if not self.ptt:
                self.create_ptt()
            self.send_roger_beep()
        except Exception as e:
            self.show_copyable_error("Rogerbeep-Test",str(e))

    def start_gateway(self):

        self.ensure_gateway_sink()
        if hasattr(self, "auto_route") and self.auto_route.isChecked():
            self.auto_route_known_apps()
        try:
            make_virtual_sink(); self.create_ptt(); sink=self.target_sink.currentData()
            if not sink: raise RuntimeError("Bitte zuerst den Ausgang zum Funkgerät auswählen.")
            if self.bridge: self.bridge.stop()
            self.bridge=AudioBridge(sink,self.threshold.value(),self.hang.value(),self.tx_gain.value())
            self.bridge.set_output_muted(self.protection_muted)
            self.bridge.signals.level.connect(self.meter.setValue)
            self.bridge.signals.db_level.connect(lambda db:self.tx_db_label.setText(f"TX Eingang: {db:.1f} dBFS"))
            self.bridge.signals.clipping.connect(self.on_tx_clipping)
            self.bridge.signals.activity.connect(self.on_audio_activity)
            self.bridge.signals.error.connect(lambda e:self.log(f"Audiofehler: {e}")); self.bridge.start()

            if self.rx_detector: self.rx_detector.stop()
            self.rx_detector=None
            rx_source=self.rx_source.currentData() if hasattr(self,"rx_source") else None
            if rx_source:
                make_rx_source()
                self.rx_detector=RxActivityDetector(
                    rx_source,self.rx_threshold.value(),self.rx_hang.value(),
                    self.rx_gain.value(),self.rx_hysteresis.value(),self.rx_min_signal.value()
                )
                self.rx_detector.signals.level.connect(self.rx_meter.setValue)
                self.rx_detector.signals.db_level.connect(self.on_rx_db_level)
                self.rx_detector.signals.activity.connect(self.on_rx_activity)
                self.rx_detector.signals.dtmf.connect(self._on_dtmf_digit)
                self.rx_detector.signals.error.connect(lambda e:self.log(f"RX-Erkennungsfehler: {e}"))
                self._apply_dtmf_detector_settings()
                self.rx_detector.start()
                self._refresh_rx_forward_mute()
                self.log(f"Funk-RX aktiv: {rx_source} -> FunkGateway_RX_Input, RX-Gain: {self.rx_gain.value()} dB")
                if hasattr(self,"parrot_enabled") and self.parrot_enabled.isChecked():
                    self._ensure_parrot_capture()
            self.save_cfg()
            if hasattr(self,"auto_route") and self.auto_route.isChecked():
                self.auto_route_known_apps()
            self._set_tx_forward_muted(False)
            self.log(f"Gateway gestartet. Audio-Automatik und Routing-Wächter aktiv. TX-Gain: {self.tx_gain.value()} dB")
        except Exception as e: self.show_copyable_error("Start fehlgeschlagen",str(e))

    def stop_gateway(self):
        self._stop_parrot_capture()
        self.ts_commander_wanted=False
        self._set_big_rx_status(False)
        if self.rx_detector: self.rx_detector.stop(); self.rx_detector=None
        if self.bridge: self.bridge.stop(); self.bridge=None
        if self.roger_proc:
            try: self.roger_proc.terminate()
            except Exception: pass
            self.roger_proc=None
        self.roger_busy=False; self.outgoing_audio_active=False
        self.dtmf_session_active=False; self.dtmf_session_muted=False; self.dtmf_buffer=""
        self.dtmf_control_rx_active=False
        self.dtmf_ack_waiting_labels.clear()
        self.dtmf_mode_ack_generation += 1
        self.dtmf_mode_ack_pending=False
        if self.ptt: self.set_ptt(False)
        self.log("Gateway gestoppt.")

    def emergency(self):
        self.ts_commander_wanted=False
        self._set_big_rx_status(False)
        if self.rx_detector: self.rx_detector.stop(); self.rx_detector=None
        if self.bridge: self.bridge.stop(); self.bridge=None
        if self.roger_proc:
            try: self.roger_proc.terminate()
            except Exception: pass
            self.roger_proc=None
        self.roger_busy=False; self.outgoing_audio_active=False
        try:
            if self.ptt: self.ptt.key(False)
        except Exception: pass
        self.tx=False; self.tx_since=None; self.tx_lbl.setText("● PTT AUS"); self.log("NOT-AUS ausgelöst: PTT AUS.")

    def test_ptt(self):
        try:
            self.create_ptt(); self.set_ptt(True); QApplication.processEvents(); time.sleep(.7); self.set_ptt(False)
            QMessageBox.information(self,"PTT-Test","PTT-Test abgeschlossen.")
        except Exception as e: self.show_copyable_error("PTT-Test",str(e))

    def update_cos_label(self): self.cos_lbl.setText("● KANAL BELEGT" if self.cos_manual.isChecked() else "● KANAL FREI")
    def choose_id(self):
        p,_=QFileDialog.getOpenFileName(self,"Rufzeichen-WAV wählen","","WAV (*.wav)")
        if p: self.id_file.setText(p); self.save_cfg()
    def play_to_virtual(self,path,kind="manual"):
        if not Path(path).exists(): raise RuntimeError(f"Datei nicht gefunden: {path}")
        make_virtual_sink()
        self.tx_source_hint=kind

        isolated_parrot=bool(
            kind in ("parrot","beacon","dtmf_ack")
            and hasattr(self,"parrot_enabled")
            and self.parrot_enabled.isChecked()
            and hasattr(self,"parrot_mute_voip")
            and self.parrot_mute_voip.isChecked()
        )

        if isolated_parrot:
            sink=self.target_sink.currentData() if hasattr(self,"target_sink") else None
            if not sink:
                raise RuntimeError("Kein Funkgeräte-Ausgang für isolierte Papagei-Wiedergabe gewählt.")
            # IMPORTANT: bypass FunkGateway_TX.monitor entirely.  That monitor
            # contains the mixed application audio, including TeamSpeak.
            proc=subprocess.Popen(["paplay",f"--device={sink}",str(path)])
            self.log(f"Papagei-Isolation: interne {kind}-WAV direkt zum Funkgeräte-Ausgang gesendet.")
        else:
            proc=subprocess.Popen(["paplay","--device=funkgateway_tx",str(path)])
        def clear_hint():
            if proc.poll() is None:
                QTimer.singleShot(100,clear_hint)
                return
            # AudioBridge/Hang darf das aktuelle TX-Ende noch mit der Quelle verknüpfen.
            QTimer.singleShot(max(300,self.hang.value()+150),lambda:self._clear_tx_source_hint(kind))
        QTimer.singleShot(100,clear_hint)
        return proc

    def _clear_tx_source_hint(self,kind):
        if self.tx_source_hint == kind:
            self.tx_source_hint=None

    def record_id(self):
        """Record the callsign announcement from the selected Pulse source."""
        source=self.input_device.currentData()
        if not source:
            QMessageBox.critical(
                self,
                "Aufnahme nicht verfügbar",
                "Bitte zuerst eine gültige Mikrofonquelle auswählen."
            )
            return

        try:
            ensure_cfg()
            seconds=self.id_record_seconds.value()
            rate=48000

            QMessageBox.information(
                self,
                "Aufnahme",
                f"Nach OK beginnt die Aufnahme für {seconds} Sekunden.\\n"
                "Sprich danach deine Rufzeichenansage."
            )
            QApplication.processEvents()

            self.log(
                f"Rufzeichenaufnahme gestartet ({seconds} s) "
                f"von Quelle: {source}"
            )

            proc=subprocess.Popen(
                [
                    "parec",
                    f"--device={source}",
                    "--format=s16le",
                    f"--rate={rate}",
                    "--channels=1",
                    "--file-format=wav",
                    str(ID_RECORDING_FILE),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )

            time.sleep(seconds)
            proc.send_signal(signal.SIGINT)

            try:
                _,err=proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                proc.terminate()
                _,err=proc.communicate(timeout=2)

            if not ID_RECORDING_FILE.exists():
                raise RuntimeError("Es wurde keine WAV-Datei erzeugt.")

            if ID_RECORDING_FILE.stat().st_size < 1000:
                raise RuntimeError("Die Aufnahme ist leer oder unvollständig.")

            with wave.open(str(ID_RECORDING_FILE),"rb") as wf:
                if wf.getsampwidth() != 2:
                    raise RuntimeError(
                        "Die Aufnahme hat ein unerwartetes Audioformat."
                    )
                frames=wf.readframes(wf.getnframes())

            samples=array.array("h")
            samples.frombytes(frames)

            if not samples:
                raise RuntimeError("Die Aufnahme enthält keine Audiodaten.")

            sum_sq=sum(int(s)*int(s) for s in samples)
            rms=(sum_sq/len(samples))**0.5
            dbfs=-120.0 if rms <= 0 else 20.0*math.log10(rms/32768.0)

            self.log(f"Rufzeichenaufnahme Pegel: {dbfs:.1f} dBFS")

            if dbfs < -65.0:
                QMessageBox.warning(
                    self,
                    "Aufnahme sehr leise",
                    "Die WAV-Datei wurde aufgenommen, enthält aber praktisch "
                    "kein hörbares Signal.\\n\\n"
                    f"Gemessener Pegel: {dbfs:.1f} dBFS\\n"
                    "Bitte prüfe die ausgewählte Mikrofonquelle."
                )
                self.log("Warnung: Rufzeichenaufnahme ist praktisch stumm.")
                return

            self.id_file.setText(str(ID_RECORDING_FILE))
            self.log("Rufzeichenaufnahme gespeichert.")

            QMessageBox.information(
                self,
                "Aufnahme fertig",
                f"Die Rufzeichenansage wurde gespeichert.\\n"
                f"Aufnahmepegel: {dbfs:.1f} dBFS"
            )
            self.save_cfg()

        except Exception as e:
            self.show_copyable_error("Aufnahmefehler",str(e))
            self.log(f"Rufzeichenaufnahme fehlgeschlagen: {e}")
    def preview_id(self):
        p=self.id_file.text().strip()
        if not p or not Path(p).exists(): QMessageBox.warning(self,"Rufzeichen","Bitte zuerst eine gültige Rufzeichendatei auswählen oder aufnehmen."); return
        subprocess.Popen(["paplay",p])

    def _id_channel_busy(self):
        return bool(
            self.tx or self.outgoing_audio_active or self.rx_was_active
            or self.roger_busy or self.protection_announcement_busy
            or self.protection_muted or self.return_guard_muted or self.cos_manual.isChecked()
        )

    def _queue_id(self,reason="Intervall"):
        if not self.pending_id:
            self.pending_id=True
            self.id_channel_free_since=None
            self.log(f"Rufzeichenbake fällig ({reason}) – wartet auf freien Funk-/VoIP-Weg.")

    def send_id(self):
        p=self.id_file.text().strip()
        if not p:
            QMessageBox.warning(self,"Rufzeichen","Bitte zuerst eine WAV-Datei auswählen.")
            return
        if self.id_in_progress:
            return
        if self.id_wait_free.isChecked() and self._id_channel_busy():
            self._queue_id("manuell")
            return
        try:
            self.id_in_progress=True
            self.pending_id=False
            self.id_channel_free_since=None
            proc=self.play_to_virtual(p,"beacon")
            self.id_proc=proc
            self.log(f"Rufzeichenbake gestartet: {Path(p).name}")
            def poll_id():
                if proc.poll() is None:
                    QTimer.singleShot(100,poll_id)
                    return
                self.id_in_progress=False
                self.id_proc=None
                self.last_id=time.monotonic()
                self.log(f"Rufzeichenbake beendet – Intervall neu gestartet: {self.id_interval.value()} Minuten.")
            QTimer.singleShot(100,poll_id)
        except Exception as e:
            self.id_in_progress=False
            self.id_proc=None
            self.show_copyable_error("Rufzeichen",str(e))

    def _try_send_pending_id(self,now):
        if not self.pending_id or self.id_in_progress:
            return
        if self._id_channel_busy():
            self.id_channel_free_since=None
            return
        if self.id_channel_free_since is None:
            self.id_channel_free_since=now
            self.log(f"Rufzeichenbake: Kanal frei – Freiwartezeit {self.id_free_wait_ms.value()} ms läuft.")
            return
        if (now-self.id_channel_free_since)*1000 >= self.id_free_wait_ms.value():
            self.send_id()

    def send_cw(self):
        try: make_cw(self.cw_text.text(),CW_FILE,self.cw_wpm.value(),self.cw_freq.value()); self.play_to_virtual(CW_FILE,"manual"); self.log(f"CW gesendet: {self.cw_text.text()}")
        except Exception as e: self.show_copyable_error("CW",str(e))
    def send_dtmf(self):
        try: make_dtmf(self.dtmf_text.text(),DTMF_FILE); self.play_to_virtual(DTMF_FILE,"manual"); self.log(f"DTMF gesendet: {self.dtmf_text.text()}")
        except Exception as e: self.show_copyable_error("DTMF",str(e))

    def tick(self):
        self.update_cos_label()
        self.routing_watchdog_tick()
        now=time.monotonic()
        self._protection_tick(now)
        if self.rx_status.text() == "● FUNK RX SPERRZEIT" and now >= self.rx_ignore_until:
            self.rx_status.setText("● FUNK RX FREI")
            self._set_big_rx_status(False)
        if self.tx and self.tx_since and now-self.tx_since>self.tot.value():
            tx_duration=now-self.tx_since
            sink_id=self._funkgateway_sink_id()
            names=[]
            for stream in self._read_sink_inputs():
                if sink_id and stream.get("sink") == sink_id:
                    name=stream.get("app") or stream.get("binary") or stream.get("media") or f"Stream {stream.get('id','?')}"
                    if name not in names:
                        names.append(name)
            detail=", ".join(names) if names else "kein zuordenbarer Audiostream"
            self.log(f"TOT: maximale Sendezeit überschritten nach {tx_duration:.1f} s. Aktiv auf FunkGateway_TX: {detail}")
            self.emergency()
            QMessageBox.warning(self,"TOT","Maximale Sendezeit erreicht. PTT wurde abgeschaltet. Details stehen im Protokoll.")
        self._return_guard_tick(now)
        self._dtmf_tick(now)
        self._try_send_pending_id(now)
        if (not self.parrot_enabled.isChecked()) and self.id_auto.isChecked() and not self.pending_id and not self.id_in_progress and now-self.last_id>=self.id_interval.value()*60:
            self._queue_id("Intervall erreicht")
        self._parrot_tick(now)

    def save_cfg(self):
        ensure_cfg(); data={"ptt_method":self.ptt_method.currentText(),"com_port":self.selected_port(),"com_line":self.com_line.currentText(),
        "cm_dev":self.cm_dev.text(),"gpio_chip":self.gpio_chip.text(),"gpio_line":self.gpio_line.value(),"invert":self.invert.isChecked(),
        "lead":self.lead.value(),"tot":self.tot.value(),"target_sink":self.target_sink.currentData(),"threshold":self.threshold.value(),
        "hang":self.hang.value(),"tx_gain_db":self.tx_gain.value(),"rx_source":self.rx_source.currentData(),"rx_threshold":self.rx_threshold.value(),"rx_hang":self.rx_hang.value(),"rx_gain_db":self.rx_gain.value(),
        "rx_hysteresis_db":self.rx_hysteresis.value(),"rx_min_signal_ms":self.rx_min_signal.value(),"rx_ignore_after_roger_ms":self.rx_ignore_after_roger.value(),
        "roger_min_free_ms":self.roger_min_free.value(),"roger_cooldown_ms":self.roger_cooldown.value(),"diagnostic_mode":self.diagnostic_mode.isChecked(),
        "verbose_log":self.verbose_log.isChecked(),
        "roger_type":self.roger_type.currentText(),"roger_delay":self.roger_delay.value(),"roger_freq":self.roger_freq.value(),"roger_wpm":self.roger_wpm.value(),
        "roger_volume":self.roger_volume.value(),"roger_wav":self.roger_wav.text(),"id_file":self.id_file.text(),"id_interval":self.id_interval.value(),"id_record_seconds":self.id_record_seconds.value(),
        "id_auto":self.id_auto.isChecked(),"id_wait_free":self.id_wait_free.isChecked(),"id_free_wait_ms":self.id_free_wait_ms.value(),"cw_text":self.cw_text.text(),
        "ts_enabled":self.ts_enabled.isChecked(),"ts_commander_enabled":self.ts_commander_enabled.isChecked(),
        "ts_host":self.ts_host.text(),"ts_port":self.ts_port.value(),"ts_api_key":self.ts_api_key.text(),
        "mumble_enabled":self.mumble_enabled.isChecked(),"voip_hf_voice_filter":self.voip_hf_voice_filter.isChecked(),"mumble_ice_mode":self.mumble_ice_mode.currentData(),
        "mumble_ice_host":self.mumble_ice_host.text(),"mumble_ice_port":self.mumble_ice_port.value(),"mumble_ice_server_id":self.mumble_ice_server_id.value(),
        "dtmf_enabled":self.dtmf_enabled.isChecked(),"dtmf_suppress_voip":self.dtmf_suppress_voip.isChecked(),
        "dtmf_start_char":self.dtmf_start_char.text(),"dtmf_end_char":self.dtmf_end_char.text(),
        "dtmf_interdigit_ms":self.dtmf_interdigit_ms.value(),"dtmf_session_max_s":self.dtmf_session_max_s.value(),
        "dtmf_release_ms":self.dtmf_release_ms.value(),
        "dtmf_auth_enabled":self.dtmf_auth_enabled.isChecked(),
        "dtmf_auth_method":self.dtmf_auth_method.currentData(),
        "dtmf_auth_prefix":self.dtmf_auth_prefix.text(),
        "dtmf_auth_logout_code":self.dtmf_auth_logout_code.text(),
        "dtmf_auth_valid_s":self.dtmf_auth_valid_s.value(),
        "dtmf_auth_max_attempts":self.dtmf_auth_max_attempts.value(),
        "dtmf_auth_lockout_s":self.dtmf_auth_lockout_s.value(),
        "dtmf_auth_pin_salt":self.dtmf_auth_pin_salt,
        "dtmf_auth_pin_hash":self.dtmf_auth_pin_hash,
        "dtmf_totp_secret":self.dtmf_totp_secret,
        "dtmf_totp_last_counter":self.dtmf_totp_last_counter,
        "dtmf_totp_digits":self.dtmf_totp_digits.value(),
        "dtmf_totp_period":self.dtmf_totp_period.value(),
        "dtmf_totp_window":self.dtmf_totp_window.value(),
        "dtmf_totp_label":self.dtmf_totp_label.text(),
        "dtmf_totp_account":self.dtmf_totp_account.text(),
        "dtmf_auth_success_wav":self.dtmf_auth_success_wav.text(),
        "dtmf_auth_required_wav":self.dtmf_auth_required_wav.text(),
        "dtmf_auth_failed_wav":self.dtmf_auth_failed_wav.text(),
        "dtmf_auth_req_parrot":self.dtmf_auth_req_parrot.isChecked(),
        "dtmf_auth_req_voip":self.dtmf_auth_req_voip.isChecked(),
        "dtmf_auth_req_ts_mute":self.dtmf_auth_req_ts_mute.isChecked(),
        "dtmf_auth_req_ts_unmute":self.dtmf_auth_req_ts_unmute.isChecked(),
        "dtmf_auth_req_ts_deaf":self.dtmf_auth_req_ts_deaf.isChecked(),
        "dtmf_auth_req_ts_undeaf":self.dtmf_auth_req_ts_undeaf.isChecked(),
        "dtmf_auth_req_mumble_mute":self.dtmf_auth_req_mumble_mute.isChecked(),
        "dtmf_auth_req_mumble_unmute":self.dtmf_auth_req_mumble_unmute.isChecked(),
        "dtmf_auth_req_mumble_deaf":self.dtmf_auth_req_mumble_deaf.isChecked(),
        "dtmf_auth_req_mumble_undeaf":self.dtmf_auth_req_mumble_undeaf.isChecked(),
        "dtmf_ts_room_auth":[cb.isChecked() for cb in self.dtmf_ts_room_auth],
        "dtmf_mumble_room_auth":[cb.isChecked() for cb in self.dtmf_mumble_room_auth],
        "dtmf_code_parrot_on":self.dtmf_code_parrot_on.text(),"dtmf_code_voip_on":self.dtmf_code_voip_on.text(),
        "dtmf_code_ts_mute":self.dtmf_code_ts_mute.text(),"dtmf_code_ts_unmute":self.dtmf_code_ts_unmute.text(),
        "dtmf_code_ts_deaf":self.dtmf_code_ts_deaf.text(),"dtmf_code_ts_undeaf":self.dtmf_code_ts_undeaf.text(),
        "dtmf_code_mumble_mute":self.dtmf_code_mumble_mute.text(),"dtmf_code_mumble_unmute":self.dtmf_code_mumble_unmute.text(),
        "dtmf_code_mumble_deaf":self.dtmf_code_mumble_deaf.text(),"dtmf_code_mumble_undeaf":self.dtmf_code_mumble_undeaf.text(),
        "dtmf_ack_enabled":self.dtmf_ack_enabled.isChecked(),
        "dtmf_ack_tail_ms":self.dtmf_ack_tail_ms.value(),
        "dtmf_ack_parrot_wav":self.dtmf_ack_parrot_wav.text(),
        "dtmf_ack_voip_wav":self.dtmf_ack_voip_wav.text(),
        "dtmf_ack_default_wav":self.dtmf_ack_default_wav.text(),
        "dtmf_ts_rooms":self._save_dtmf_room_rows(self.dtmf_ts_room_rows),
        "dtmf_mumble_rooms":self._save_dtmf_room_rows(self.dtmf_mumble_room_rows),
        "mumble_slice":self.mumble_slice.text(),"mumble_ssh_host":self.mumble_ssh_host.text(),"mumble_ssh_port":self.mumble_ssh_port.value(),
        "mumble_ssh_user":self.mumble_ssh_user.text(),"mumble_gateway_name":self.mumble_gateway_name.text(),
        "mumble_bridge_url":self.mumble_bridge_url.text(),
        "mumble_disturbance_rooms":self.mumble_disturbance_rooms,
        "protect_rx_enabled":self.protect_rx_enabled.isChecked(),"protect_rx_seconds":self.protect_rx_seconds.value(),
        "protect_auto_unmute":self.protect_auto_unmute.isChecked(),"protect_unmute_seconds":self.protect_unmute_seconds.value(),
        "protect_require_rx_free":self.protect_require_rx_free.isChecked(),"protect_free_seconds":self.protect_free_seconds.value(),
        "protect_free_threshold":self.protect_free_threshold.value(),"protect_move_to_room":self.protect_move_to_room.isChecked(),
        "protect_return_channel":self.protect_return_channel.isChecked(),"protect_move_to_mumble_room":self.protect_move_to_mumble_room.isChecked(),
        "protect_return_mumble_channel":self.protect_return_mumble_channel.isChecked(),"protect_room_enabled":self.protect_room_enabled.isChecked(),
        "protect_room_repeat":self.protect_room_repeat.isChecked(),"protect_room_repeat_min":self.protect_room_repeat_min.value(),
        "protect_mute_wav":self.protect_mute_wav.text(),"protect_room_wav":self.protect_room_wav.text(),
        "protect_restore_wav":self.protect_restore_wav.text(),"protection_ts_rooms":self.protection_ts_rooms,
        "return_guard_enabled":self.return_guard_enabled.isChecked(),
        "return_after_voip":self.return_after_voip.isChecked(),"return_after_beacon":self.return_after_beacon.isChecked(),
        "return_after_roger":self.return_after_roger.isChecked(),"return_after_protection":self.return_after_protection.isChecked(),
        "return_after_manual":self.return_after_manual.isChecked(),"return_guard_ms":self.return_guard_ms.value(),
        "return_max_tail_ms":self.return_max_tail_ms.value(),"return_real_passage_ms":self.return_real_passage_ms.value(),
        "return_repeat_wait_ms":self.return_repeat_wait_ms.value(),"return_window_s":self.return_window_s.value(),
        "return_count_limit":self.return_count_limit.value(),"return_escalate":self.return_escalate.isChecked(),
        "return_move_rooms":self.return_move_rooms.isChecked(),"return_lost_wav":self.return_lost_wav.text(),
        "update_check_start":self.update_check_start.isChecked(),
        "parrot_enabled":self.parrot_enabled.isChecked(),"parrot_max_seconds":self.parrot_max_seconds.value(),
        "parrot_rx_prebuffer_ms":self.parrot_rx_prebuffer_ms.value(),
        "parrot_delay_ms":self.parrot_delay_ms.value(),"parrot_lead_ms":self.parrot_lead_ms.value(),"parrot_mute_voip":self.parrot_mute_voip.isChecked(),
        "parrot_return_guard":self.parrot_return_guard.isChecked(),"parrot_roger":self.parrot_roger.isChecked(),
        "parrot_beacon_enabled":self.parrot_beacon_enabled.isChecked(),"parrot_beacon_file":self.parrot_beacon_file.text(),
        "parrot_beacon_interval":self.parrot_beacon_interval.value(),"parrot_beacon_free_wait_ms":self.parrot_beacon_free_wait_ms.value(),
        "parrot_beacon_lead_ms":self.parrot_beacon_lead_ms.value(),"parrot_beacon_tail_ms":self.parrot_beacon_tail_ms.value()}
        CFG_FILE.write_text(json.dumps(data,indent=2),encoding="utf-8")
        try: CFG_FILE.chmod(0o600)
        except Exception: pass

    def load_cfg(self):
        self._wanted_sink=None; self._wanted_rx_source=None
        if not CFG_FILE.exists(): return
        try:
            d=json.loads(CFG_FILE.read_text(encoding="utf-8"))
            for combo,val in ((self.ptt_method,d.get("ptt_method")),(self.com_line,d.get("com_line"))):
                i=combo.findText(val or "")
                if i>=0: combo.setCurrentIndex(i)
            self._wanted_port=d.get("com_port",""); self.cm_dev.setText(d.get("cm_dev","/dev/hidraw0")); self.gpio_chip.setText(d.get("gpio_chip","/dev/gpiochip0"))
            self.gpio_line.setValue(d.get("gpio_line",3)); self.invert.setChecked(d.get("invert",False)); self.lead.setValue(d.get("lead",250)); self.tot.setValue(d.get("tot",180))
            self.threshold.setValue(d.get("threshold",-42)); self.hang.setValue(d.get("hang",550))
            self.tx_gain.setValue(int(d.get("tx_gain_db",0) or 0))
            self._wanted_rx_source=d.get("rx_source"); self.rx_threshold.setValue(d.get("rx_threshold",-45)); self.rx_hang.setValue(d.get("rx_hang",550))
            self.rx_gain.setValue(int(d.get("rx_gain_db",0) or 0))
            self.rx_hysteresis.setValue(int(d.get("rx_hysteresis_db",3) or 0))
            self.rx_min_signal.setValue(int(d.get("rx_min_signal_ms",200) or 0))
            self.rx_ignore_after_roger.setValue(int(d.get("rx_ignore_after_roger_ms",3000) or 0))
            self.roger_min_free.setValue(int(d.get("roger_min_free_ms",300) or 0))
            self.roger_cooldown.setValue(int(d.get("roger_cooldown_ms",5000) or 0))
            self.diagnostic_mode.setChecked(bool(d.get("diagnostic_mode",False)))
            self.verbose_log.setChecked(bool(d.get("verbose_log",False)))
            i=self.roger_type.findText(d.get("roger_type","Aus"));
            if i>=0: self.roger_type.setCurrentIndex(i)
            self.roger_delay.setValue(d.get("roger_delay",250)); self.roger_freq.setValue(d.get("roger_freq",800)); self.roger_wpm.setValue(d.get("roger_wpm",20))
            self.roger_volume.setValue(d.get("roger_volume",70)); self.roger_wav.setText(d.get("roger_wav",""))
            self.id_file.setText(d.get("id_file","")); self.id_interval.setValue(d.get("id_interval",10))
            self.id_record_seconds.setValue(d.get("id_record_seconds",8)); self.id_auto.setChecked(d.get("id_auto",True)); self.id_wait_free.setChecked(d.get("id_wait_free",True)); self.id_free_wait_ms.setValue(int(d.get("id_free_wait_ms",1500) or 1500)); self.cw_text.setText(d.get("cw_text","")); self._wanted_sink=d.get("target_sink")
            self.ts_enabled.setChecked(bool(d.get("ts_enabled",False)))
            self.ts_commander_enabled.setChecked(bool(d.get("ts_commander_enabled",True)))
            self.ts_host.setText(d.get("ts_host","127.0.0.1"))
            self.ts_port.setValue(int(d.get("ts_port",25639) or 25639))
            self.ts_api_key.setText(d.get("ts_api_key",""))
            self.dtmf_enabled.setChecked(bool(d.get("dtmf_enabled",False)))
            self.dtmf_suppress_voip.setChecked(bool(d.get("dtmf_suppress_voip",True)))
            self.dtmf_start_char.setText(str(d.get("dtmf_start_char","*") or "*")[:1])
            self.dtmf_end_char.setText(str(d.get("dtmf_end_char","#") or "#")[:1])
            self.dtmf_interdigit_ms.setValue(int(d.get("dtmf_interdigit_ms",2000) or 2000))
            self.dtmf_session_max_s.setValue(int(d.get("dtmf_session_max_s",10) or 10))
            self.dtmf_release_ms.setValue(int(d.get("dtmf_release_ms",250) or 250))
            self.dtmf_auth_enabled.setChecked(bool(d.get("dtmf_auth_enabled",False)))
            auth_method=str(d.get("dtmf_auth_method","pin") or "pin")
            auth_idx=self.dtmf_auth_method.findData(auth_method)
            if auth_idx>=0: self.dtmf_auth_method.setCurrentIndex(auth_idx)
            self.dtmf_auth_prefix.setText(d.get("dtmf_auth_prefix","*00*"))
            self.dtmf_auth_logout_code.setText(d.get("dtmf_auth_logout_code","*00*0#"))
            self.dtmf_auth_valid_s.setValue(int(d.get("dtmf_auth_valid_s",180) or 180))
            self.dtmf_auth_max_attempts.setValue(int(d.get("dtmf_auth_max_attempts",3) or 3))
            self.dtmf_auth_lockout_s.setValue(int(d.get("dtmf_auth_lockout_s",60) or 60))
            self.dtmf_auth_pin_salt=str(d.get("dtmf_auth_pin_salt","") or "")
            self.dtmf_auth_pin_hash=str(d.get("dtmf_auth_pin_hash","") or "")
            self.dtmf_totp_secret=str(d.get("dtmf_totp_secret","") or "")
            self.dtmf_totp_last_counter=int(d.get("dtmf_totp_last_counter",-1) or -1)
            self.dtmf_totp_digits.setValue(int(d.get("dtmf_totp_digits",6) or 6))
            self.dtmf_totp_period.setValue(int(d.get("dtmf_totp_period",30) or 30))
            self.dtmf_totp_window.setValue(int(d.get("dtmf_totp_window",1) or 1))
            self.dtmf_totp_label.setText(d.get("dtmf_totp_label","FunkGateway"))
            self.dtmf_totp_account.setText(d.get("dtmf_totp_account","DTMF"))
            self._refresh_dtmf_totp_uri()
            self.dtmf_auth_success_wav.setText(d.get("dtmf_auth_success_wav",""))
            self.dtmf_auth_required_wav.setText(d.get("dtmf_auth_required_wav",""))
            self.dtmf_auth_failed_wav.setText(d.get("dtmf_auth_failed_wav",""))
            self.dtmf_auth_req_parrot.setChecked(bool(d.get("dtmf_auth_req_parrot",True)))
            self.dtmf_auth_req_voip.setChecked(bool(d.get("dtmf_auth_req_voip",True)))
            self.dtmf_auth_req_ts_mute.setChecked(bool(d.get("dtmf_auth_req_ts_mute",True)))
            self.dtmf_auth_req_ts_unmute.setChecked(bool(d.get("dtmf_auth_req_ts_unmute",True)))
            self.dtmf_auth_req_ts_deaf.setChecked(bool(d.get("dtmf_auth_req_ts_deaf",True)))
            self.dtmf_auth_req_ts_undeaf.setChecked(bool(d.get("dtmf_auth_req_ts_undeaf",True)))
            self.dtmf_auth_req_mumble_mute.setChecked(bool(d.get("dtmf_auth_req_mumble_mute",True)))
            self.dtmf_auth_req_mumble_unmute.setChecked(bool(d.get("dtmf_auth_req_mumble_unmute",True)))
            self.dtmf_auth_req_mumble_deaf.setChecked(bool(d.get("dtmf_auth_req_mumble_deaf",True)))
            self.dtmf_auth_req_mumble_undeaf.setChecked(bool(d.get("dtmf_auth_req_mumble_undeaf",True)))
            ts_auth=d.get("dtmf_ts_room_auth",[True]*5)
            mum_auth=d.get("dtmf_mumble_room_auth",[True]*5)
            if isinstance(ts_auth,list):
                for cb,val in zip(self.dtmf_ts_room_auth,ts_auth): cb.setChecked(bool(val))
            if isinstance(mum_auth,list):
                for cb,val in zip(self.dtmf_mumble_room_auth,mum_auth): cb.setChecked(bool(val))
            if (self.dtmf_auth_method.currentData() or "pin")=="totp":
                self.dtmf_auth_status.setText("AUTH: TOTP eingerichtet; nicht angemeldet" if self.dtmf_totp_secret else "AUTH: kein TOTP-Geheimnis")
            else:
                self.dtmf_auth_status.setText("AUTH: PIN gesetzt; nicht angemeldet" if self.dtmf_auth_pin_hash else "AUTH: kein PIN gesetzt")
            self.dtmf_code_parrot_on.setText(d.get("dtmf_code_parrot_on","*91#"))
            self.dtmf_code_voip_on.setText(d.get("dtmf_code_voip_on","*90#"))
            self.dtmf_code_ts_mute.setText(d.get("dtmf_code_ts_mute","*51#"))
            self.dtmf_code_ts_unmute.setText(d.get("dtmf_code_ts_unmute","*52#"))
            self.dtmf_code_ts_deaf.setText(d.get("dtmf_code_ts_deaf","*53#"))
            self.dtmf_code_ts_undeaf.setText(d.get("dtmf_code_ts_undeaf","*54#"))
            self.dtmf_code_mumble_mute.setText(d.get("dtmf_code_mumble_mute","*61#"))
            self.dtmf_code_mumble_unmute.setText(d.get("dtmf_code_mumble_unmute","*62#"))
            self.dtmf_code_mumble_deaf.setText(d.get("dtmf_code_mumble_deaf","*63#"))
            self.dtmf_code_mumble_undeaf.setText(d.get("dtmf_code_mumble_undeaf","*64#"))
            self.dtmf_ack_enabled.setChecked(bool(d.get("dtmf_ack_enabled",True)))
            self.dtmf_ack_tail_ms.setValue(int(d.get("dtmf_ack_tail_ms",2500) or 2500))
            self.dtmf_ack_parrot_wav.setText(d.get("dtmf_ack_parrot_wav",""))
            self.dtmf_ack_voip_wav.setText(d.get("dtmf_ack_voip_wav",""))
            self.dtmf_ack_default_wav.setText(d.get("dtmf_ack_default_wav",""))
            self._load_dtmf_room_rows(d.get("dtmf_ts_rooms",[]),self.dtmf_ts_room_rows,"TeamSpeak")
            self._load_dtmf_room_rows(d.get("dtmf_mumble_rooms",[]),self.dtmf_mumble_room_rows,"Mumble")
            self.mumble_enabled.setChecked(bool(d.get("mumble_enabled",False)))
            self.voip_hf_voice_filter.setChecked(bool(d.get("voip_hf_voice_filter",True)))
            i=self.mumble_ice_mode.findData(d.get("mumble_ice_mode","off"));
            if i>=0: self.mumble_ice_mode.setCurrentIndex(i)
            self.mumble_ice_host.setText(d.get("mumble_ice_host","127.0.0.1")); self.mumble_ice_port.setValue(int(d.get("mumble_ice_port",6502) or 6502)); self.mumble_ice_server_id.setValue(int(d.get("mumble_ice_server_id",1) or 1))
            self.mumble_slice.setText(d.get("mumble_slice","")); self.mumble_ssh_host.setText(d.get("mumble_ssh_host","")); self.mumble_ssh_port.setValue(int(d.get("mumble_ssh_port",22) or 22)); self.mumble_ssh_user.setText(d.get("mumble_ssh_user","")); self.mumble_gateway_name.setText(d.get("mumble_gateway_name","")); self.mumble_bridge_url.setText(d.get("mumble_bridge_url",""))
            rooms=d.get("mumble_disturbance_rooms",{}); self.mumble_disturbance_rooms=rooms if isinstance(rooms,dict) else {}
            room=self.mumble_disturbance_rooms.get(self._mumble_server_key())
            if room: self.mumble_disturbance_status.setText(f"Mumble-Störungsraum: {room.get('name','?')} (CID {room.get('cid','?')})")
            self.protect_rx_enabled.setChecked(bool(d.get("protect_rx_enabled",False)))
            self.protect_rx_seconds.setValue(int(d.get("protect_rx_seconds",180) or 180))
            self.protect_auto_unmute.setChecked(bool(d.get("protect_auto_unmute",False)))
            self.protect_unmute_seconds.setValue(int(d.get("protect_unmute_seconds",60) or 60))
            self.protect_require_rx_free.setChecked(bool(d.get("protect_require_rx_free",True)))
            self.protect_free_seconds.setValue(int(d.get("protect_free_seconds",3) or 3))
            self.protect_free_threshold.setValue(int(d.get("protect_free_threshold",-30) or -30))
            self.protect_move_to_room.setChecked(bool(d.get("protect_move_to_room",False)))
            self.protect_return_channel.setChecked(bool(d.get("protect_return_channel",True)))
            self.protect_move_to_mumble_room.setChecked(bool(d.get("protect_move_to_mumble_room",False)))
            self.protect_return_mumble_channel.setChecked(bool(d.get("protect_return_mumble_channel",True)))
            self.protect_room_enabled.setChecked(bool(d.get("protect_room_enabled",False)))
            self.protect_room_repeat.setChecked(bool(d.get("protect_room_repeat",True)))
            self.protect_room_repeat_min.setValue(int(d.get("protect_room_repeat_min",10) or 10))
            self.protect_mute_wav.setText(d.get("protect_mute_wav","")); self.protect_room_wav.setText(d.get("protect_room_wav","")); self.protect_restore_wav.setText(d.get("protect_restore_wav",""))
            self.return_guard_enabled.setChecked(bool(d.get("return_guard_enabled",True)))
            self.return_after_voip.setChecked(bool(d.get("return_after_voip",True)))
            self.return_after_beacon.setChecked(bool(d.get("return_after_beacon",True)))
            self.return_after_roger.setChecked(bool(d.get("return_after_roger",True)))
            self.return_after_protection.setChecked(bool(d.get("return_after_protection",True)))
            self.return_after_manual.setChecked(bool(d.get("return_after_manual",False)))
            self.return_guard_ms.setValue(int(d.get("return_guard_ms",3500) or 3500))
            self.return_max_tail_ms.setValue(int(d.get("return_max_tail_ms",2500) or 2500))
            self.return_real_passage_ms.setValue(int(d.get("return_real_passage_ms",5000) or 5000))
            self.return_repeat_wait_ms.setValue(int(d.get("return_repeat_wait_ms",3000) or 3000))
            self.return_window_s.setValue(int(d.get("return_window_s",30) or 30))
            self.return_count_limit.setValue(int(d.get("return_count_limit",3) or 3))
            self.return_escalate.setChecked(bool(d.get("return_escalate",True)))
            self.return_move_rooms.setChecked(bool(d.get("return_move_rooms",True)))
            self.return_lost_wav.setText(d.get("return_lost_wav",""))
            self.update_check_start.setChecked(bool(d.get("update_check_start",False)))
            self.parrot_enabled.setChecked(bool(d.get("parrot_enabled",False)))
            self.parrot_max_seconds.setValue(int(d.get("parrot_max_seconds",30) or 30))
            self.parrot_rx_prebuffer_ms.setValue(int(d.get("parrot_rx_prebuffer_ms",1500) or 1500))
            self.parrot_delay_ms.setValue(int(d.get("parrot_delay_ms",1000) or 1000))
            self.parrot_lead_ms.setValue(int(d.get("parrot_lead_ms",1200) or 1200))
            self.parrot_mute_voip.setChecked(bool(d.get("parrot_mute_voip",True)))
            self.parrot_return_guard.setChecked(bool(d.get("parrot_return_guard",True)))
            self.parrot_roger.setChecked(bool(d.get("parrot_roger",False)))
            self.parrot_beacon_enabled.setChecked(bool(d.get("parrot_beacon_enabled",True)))
            self.parrot_beacon_file.setText(d.get("parrot_beacon_file",""))
            self.parrot_beacon_interval.setValue(int(d.get("parrot_beacon_interval",10) or 10))
            self.parrot_beacon_free_wait_ms.setValue(int(d.get("parrot_beacon_free_wait_ms",1500) or 1500))
            self.parrot_beacon_lead_ms.setValue(int(d.get("parrot_beacon_lead_ms",1200) or 1200))
            self.parrot_beacon_tail_ms.setValue(int(d.get("parrot_beacon_tail_ms",800) or 800))
            rooms=d.get("protection_ts_rooms",{})
            self.protection_ts_rooms=rooms if isinstance(rooms,dict) else {}
        except Exception as e: self.log(f"Konfiguration konnte nicht vollständig geladen werden: {e}")


    def closeEvent(self,ev):
        self.save_cfg(); self.stop_gateway()
        try:
            if self.ts_commander_state:
                self._configure_teamspeak()
                self.ts_client.set_channel_commander(False)
        except Exception:
            pass
        self.ts_client.close()
        try: self.mumble_ice.stop_tunnel()
        except Exception: pass
        if self.ptt: self.ptt.close()
        ev.accept()