from __future__ import annotations
import html
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPushButton,
    QComboBox,QSpinBox,QCheckBox,QTabWidget,QTableWidget,QTableWidgetItem,QHeaderView,QPlainTextEdit,
    QProgressBar,QAbstractItemView,QMessageBox,QGroupBox)
from .frn_native import FrnNativeClient,FrnSystemExplorer,FrnConfig,MANAGERS,sd

class FrnPanel(QWidget):
    statusChanged=Signal(str)
    connectedChanged=Signal(bool)
    talkerChanged=Signal(str)
    levelsChanged=Signal(float,float)
    pttStateChanged=Signal(bool)

    def __init__(self,parent=None):
        super().__init__(parent); self.client=None; self.rows=[]; self.filtered_rows=[]; self.direct_rooms=[]; self.talker_name=''; self.connected=False
        self.tx_db=-120.0; self.rx_db=-120.0; self.ptt_active=False; self._pending_room=None; self._room_switch_active=False; self._room_switch_reconnect_scheduled=False; self.selected_server_row=None; self._last_auto_client_type=None; self._active_room_count=None; self._radio_auto_mode=False
        self._sm_auto_interval_ms=180000
        self._sm_backoff_steps_ms=(60000,120000,300000,600000)
        self._sm_backoff_index=0
        self.explorer=FrnSystemExplorer(); self.explorer.signals.result.connect(self._explorer_result); self.explorer.signals.status.connect(self._set_explorer_status); self.explorer.signals.error.connect(self._explorer_error)
        self._build(); self.refresh_audio_devices(); self._update_status()
        self._room_refresh_timer=QTimer(self); self._room_refresh_timer.setInterval(self._sm_auto_interval_ms); self._room_refresh_timer.timeout.connect(self._refresh_room_counts); self._room_refresh_timer.start()

    @staticmethod
    def _radio_icon(color):
        pm=QPixmap(20,20); pm.fill(Qt.transparent); p=QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
        c=QColor(color); p.setPen(QPen(c,2)); p.setBrush(c); p.drawRoundedRect(4,6,12,10,2,2); p.drawLine(8,5,13,2); p.setBrush(Qt.NoBrush); p.drawEllipse(7,9,6,4); p.end(); return QIcon(pm)

    def _build(self):
        v=QVBoxLayout(self)
        head=QHBoxLayout(); title=QLabel('<b>FRN Native</b>'); badge=QLabel('ALPHA'); badge.setStyleSheet('font-weight:800;padding:3px 8px;border:1px solid #F2994A;border-radius:5px;')
        self.state_label=QLabel('FRN: getrennt'); head.addWidget(title); head.addWidget(badge); head.addStretch(1); head.addWidget(self.state_label); v.addLayout(head)
        note=QLabel('Native FRN-Unterstützung ist noch Alpha. Server-/Raumlisten, Audio und Protokollverhalten werden weiter getestet.'); note.setWordWrap(True); v.addWidget(note)
        tabs=QTabWidget(); v.addWidget(tabs)
        # Connection
        w=QWidget(); f=QFormLayout(w)
        self.manager=QComboBox(); [self.manager.addItem(x['label'],k) for k,x in MANAGERS.items()]
        self.server=QLineEdit(); self.port=QSpinBox(); self.port.setRange(1,65535); self.port.setValue(10024); self.room=QLineEdit()
        self.email=QLineEdit(); self.password=QLineEdit(); self.password.setEchoMode(QLineEdit.Password); self.show_password=QCheckBox('Passwort anzeigen'); self.show_password.toggled.connect(lambda x:self.password.setEchoMode(QLineEdit.Normal if x else QLineEdit.Password))
        self.callsign=QLineEdit(); self.description=QLineEdit('FunkGateway UI'); self.band=QLineEdit(); self.country=QLineEdit('Germany'); self.city=QLineEdit()
        self.client_type=QComboBox(); self.client_type.addItem('Automatisch nach FunkGateway-Modus','auto'); self.client_type.addItem('Gateway (CL=1)',1); self.client_type.addItem('PC only (CL=2)',2); self.client_type.addItem('Crosslink (CL=0)',0)
        self.protocol_version=QLineEdit('20261016'); self.protocol_version.setToolTip('FRN-Protokoll-/Clientversionskennung (VX). Keine Fremdsoftware wird imitiert.')
        self.audio_enabled=QCheckBox('FRN-Audio aktiv'); self.audio_enabled.setChecked(True); self.audio_in=QComboBox(); self.audio_out=QComboBox(); rb=QPushButton('Audiogeräte neu laden'); rb.clicked.connect(self.refresh_audio_devices)
        self.connect_btn=QPushButton('Verbinden'); self.disconnect_btn=QPushButton('Trennen'); self.disconnect_btn.setEnabled(False); self.connect_btn.clicked.connect(self.connect_frn); self.disconnect_btn.clicked.connect(self.disconnect_frn)
        br=QHBoxLayout(); br.addWidget(self.connect_btn); br.addWidget(self.disconnect_btn)
        compat_note=QLabel('Kompatibilität: Standardmäßig wird CL passend zum FunkGateway-Modus gewählt. Bei Servern mit Client-Filtern kann die legitime FRN-Klasse manuell gewählt werden.'); compat_note.setWordWrap(True)
        for label,obj in [('SystemManager:',self.manager),('Server:',self.server),('Port:',self.port),('Raum:',self.room),('E-Mail:',self.email),('Passwort:',self.password),('',self.show_password),('Rufzeichen / Name:',self.callsign),('Beschreibung:',self.description),('Band / Kanal:',self.band),('Land:',self.country),('Stadt / Bereich:',self.city),('FRN Client-Typ (CL):',self.client_type),('FRN Version (VX):',self.protocol_version),('',compat_note),('',self.audio_enabled),('Audio Eingang:',self.audio_in),('Audio Ausgang:',self.audio_out),('',rb),('',br)]: f.addRow(label,obj)
        tabs.addTab(w,'Verbindung')
        # Servers & rooms
        w=QWidget(); vv=QVBoxLayout(w); top=QHBoxLayout(); self.explorer_manager=QComboBox(); self.explorer_manager.addItem('Alle','all'); self.explorer_manager.addItem('DE Allgemein / Original','de_orig'); self.explorer_manager.addItem('DE Alternativ','de_alt'); self.explorer_manager.addItem('Russland','ru'); load=QPushButton('Serverliste laden'); load.clicked.connect(lambda:self.explorer.refresh(self.explorer_manager.currentData())); self.explorer_manager.currentIndexChanged.connect(lambda *_:self.explorer.refresh(self.explorer_manager.currentData())); self.explorer_status=QLabel('Noch nicht geladen'); top.addWidget(self.explorer_manager); top.addWidget(load); top.addWidget(self.explorer_status); vv.addLayout(top)
        server_note=QLabel('Der in der Serverliste angezeigte Raum ist nur ein veröffentlichter Hinweis. Server auswählen lädt die bekannten Räume; verbunden wird erst nach bewusster Raumwahl.'); server_note.setWordWrap(True); vv.addWidget(server_note)
        search_row=QHBoxLayout(); search_row.addWidget(QLabel('Server suchen:')); self.server_search=QLineEdit(); self.server_search.setPlaceholderText('Server, Host/IP, Port oder Raum eingeben …'); self.server_search.setClearButtonEnabled(True); self.server_search.textChanged.connect(self.filter_servers); self.server_search.returnPressed.connect(self.connect_first_filtered_server); search_row.addWidget(self.server_search,1); vv.addLayout(search_row)
        self.server_table=QTableWidget(0,4); self.server_table.setHorizontalHeaderLabels(['Server','Port','Raum','Clients']); self.server_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch); self.server_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); self.server_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.server_table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.server_table.cellClicked.connect(lambda *_:self.use_selected_server(False)); self.server_table.cellDoubleClicked.connect(lambda *_:self.use_selected_server(False)); vv.addWidget(self.server_table)
        sb=QHBoxLayout(); use=QPushButton('Server auswählen / Räume anzeigen'); use.clicked.connect(lambda:self.use_selected_server(False)); dis=QPushButton('Trennen'); dis.clicked.connect(self.disconnect_frn); sb.addWidget(use); sb.addWidget(dis); vv.addLayout(sb)
        self.room_table=QTableWidget(0,3); self.room_table.setHorizontalHeaderLabels(['Raum / Netzwerk','Clients','Quelle']); self.room_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch); self.room_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.room_table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.room_table.cellClicked.connect(lambda *_:self._room_selection_changed()); self.room_table.cellDoubleClicked.connect(lambda *_:self.join_selected_room()); vv.addWidget(QLabel('<b>Räume des aktuellen Servers</b>')); vv.addWidget(self.room_table)
        manual=QHBoxLayout(); manual.addWidget(QLabel('Raum manuell:')); self.manual_room=QLineEdit(); self.manual_room.setPlaceholderText('Raumnamen eingeben oder aus der Liste wählen …'); self.manual_room.setClearButtonEnabled(True); self.manual_room.returnPressed.connect(self.join_selected_room); manual.addWidget(self.manual_room,1); vv.addLayout(manual)
        rr=QHBoxLayout(); self.room_source=QComboBox(); self.room_source.addItem('SystemManager','systemmanager'); self.room_source.addItem('Direkt vom Server (NET_NAMES)','server'); self.room_source.addItem('Zusammengeführt','combined'); self.room_source.setCurrentIndex(2); self.room_source.currentIndexChanged.connect(self.populate_rooms); refresh=QPushButton('Raumliste aktualisieren'); refresh.clicked.connect(self.populate_rooms); sw=QPushButton('Raum beitreten / wechseln'); sw.clicked.connect(self.join_selected_room); rr.addWidget(self.room_source); rr.addWidget(refresh); rr.addWidget(sw); vv.addLayout(rr); tabs.addTab(w,'Server & Räume')
        # participants
        w=QWidget(); vv=QVBoxLayout(w); self.talker=QLabel('FRN RX: –'); self.talker.setStyleSheet('font-size:16px;font-weight:700;padding:6px;'); vv.addWidget(self.talker); self.participants=QTableWidget(0,6); self.participants.setHorizontalHeaderLabels(['','Name','Typ','Band','Land','Ort']); self.participants.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch); self.participants.setEditTriggers(QAbstractItemView.NoEditTriggers); vv.addWidget(self.participants); tabs.addTab(w,'Teilnehmer')
        # audio/PTT
        w=QWidget(); f=QFormLayout(w); self.rx_meter=QProgressBar(); self.tx_meter=QProgressBar(); self.rx_meter.setRange(0,60); self.tx_meter.setRange(0,60); self.rx_label=QLabel('RX: < -60 dBFS'); self.tx_label=QLabel('TX: < -60 dBFS'); f.addRow('FRN Empfang:',self.rx_meter); f.addRow('',self.rx_label); f.addRow('FRN Senden:',self.tx_meter); f.addRow('',self.tx_label)
        self.ptt_mode=QComboBox(); self.ptt_mode.addItem('Halten zum Senden','hold'); self.ptt_mode.addItem('Klick zum Verriegeln','latch'); self.ptt_limit_enabled=QCheckBox('Automatische TX-Abschaltung'); self.ptt_limit_enabled.setChecked(True); self.ptt_limit=QSpinBox(); self.ptt_limit.setRange(1,1800); self.ptt_limit.setValue(180); self.ptt_limit.setSuffix(' s'); self.ptt_hint=QLabel('Die globale FRN-PTT befindet sich oben in FunkGateway und bleibt in jedem Reiter erreichbar. Im Gatewaymodus wird sie ausgeblendet.'); self.ptt_hint.setWordWrap(True); f.addRow('Manuelle PTT:',self.ptt_mode); f.addRow('',self.ptt_limit_enabled); f.addRow('Max. Sendedauer:',self.ptt_limit); f.addRow('',self.ptt_hint); tabs.addTab(w,'Audio / PTT')
        # diag
        w=QWidget(); vv=QVBoxLayout(w); self.log=QPlainTextEdit(); self.log.setReadOnly(True); vv.addWidget(self.log); tabs.addTab(w,'Diagnose')

    def refresh_audio_devices(self):
        oldi=self.audio_in.currentData() if self.audio_in.count() else None; oldo=self.audio_out.currentData() if self.audio_out.count() else None; self.audio_in.clear(); self.audio_out.clear(); self.audio_in.addItem('Systemstandard',None); self.audio_out.addItem('Systemstandard',None)
        if sd:
            try:
                for i,d in enumerate(sd.query_devices()):
                    name=f'{i}: {d["name"]}'
                    if d.get('max_input_channels',0)>0:self.audio_in.addItem(name,i)
                    if d.get('max_output_channels',0)>0:self.audio_out.addItem(name,i)
            except Exception as e:self._log('Audio: '+str(e))
        for cb,val in ((self.audio_in,oldi),(self.audio_out,oldo)):
            j=cb.findData(val); cb.setCurrentIndex(j if j>=0 else 0)

    def _cfg(self):
        if not self.server.text().strip(): raise ValueError('Bitte FRN-Server auswählen oder eintragen.')
        if not self.room.text().strip(): raise ValueError('Bitte zuerst einen Raum auswählen. FRN benötigt für die Anmeldung einen Raum.')
        selected=self.client_type.currentData()
        parent_mode=(self.parent()._mode() if self.parent() is not None and hasattr(self.parent(),'_mode') else 'pc')
        radio_auto=parent_mode in ('gateway','radio_parrot')
        if selected=='auto':
            client_type=1 if radio_auto else 2
        else:
            client_type=int(selected)
        vx=self.protocol_version.text().strip() or '20261016'
        pulse_input='funkgateway_rx_source' if radio_auto else None
        return FrnConfig(self.manager.currentData(),self.server.text().strip(),self.port.value(),self.email.text().strip(),self.password.text(),self.callsign.text().strip(),vx,client_type,self.band.text().strip(),self.description.text().strip(),self.country.text().strip(),self.city.text().strip(),self.room.text().strip(),self.audio_in.currentData(),self.audio_out.currentData(),self.audio_enabled.isChecked(),pulse_input)

    def connect_frn(self):
        try: cfg=self._cfg()
        except Exception as e: QMessageBox.warning(self,'FRN',str(e)); return
        if self.client:self.client.stop()
        self.client=FrnNativeClient(cfg); s=self.client.signals; s.log.connect(self._log); s.state.connect(lambda _:self._update_status()); s.connected.connect(self._connected); s.participant_list.connect(self.update_participants); s.server_room_list.connect(self._direct_rooms); s.rx_talker.connect(self.update_talker); s.audio_level.connect(self._tx_level); s.rx_audio_level.connect(self._rx_level); s.tx_granted.connect(self._tx_granted); s.error.connect(lambda e:self._log('FEHLER: '+e)); self.connect_btn.setEnabled(False); self.client.start()
    def disconnect_frn(self, room_switch=False):
        self.ptt(False,force=True)
        if not room_switch:
            self._room_switch_active=False
            self._room_switch_reconnect_scheduled=False
            self._pending_room=None
        if self.client:
            self.client.stop()
        self.client=None
        # stop() kann das connected(False)-Signal bereits synchron auslösen.
        # Nur nachziehen, wenn der Zustand danach noch als verbunden gilt.
        if self.connected:
            self._connected(False)

    def _reset_session_view(self):
        """Clear data that belongs to the finished FRN session.

        The global SystemManager server list, its filter and the search text stay
        untouched so a new server can be selected immediately.  A room switch
        deliberately skips this reset because _pending_room is set in that case.
        """
        self.direct_rooms=[]
        self._active_room_count=None
        self.talker_name=''
        self.ptt_active=False
        self.rx_db=-120.0; self.tx_db=-120.0
        self.room.clear()
        if hasattr(self,'manual_room'): self.manual_room.clear()
        if hasattr(self,'room_table'):
            self.room_table.clearSelection(); self.room_table.setRowCount(0)
        if hasattr(self,'participants'):
            self.participants.clearSelection(); self.participants.setRowCount(0)
        if hasattr(self,'talker'): self.talker.setText('FRN RX: –')
        if hasattr(self,'rx_meter'): self.rx_meter.setValue(0)
        if hasattr(self,'tx_meter'): self.tx_meter.setValue(0)
        if hasattr(self,'rx_label'): self.rx_label.setText('RX: < -60 dBFS')
        if hasattr(self,'tx_label'): self.tx_label.setText('TX: < -60 dBFS')
        self.talkerChanged.emit('')
        self.levelsChanged.emit(self.rx_db,self.tx_db)
        self.pttStateChanged.emit(False)

    def _connected(self,yes):
        self.connected=bool(yes); self.connect_btn.setEnabled(not yes); self.disconnect_btn.setEnabled(bool(yes)); self.connectedChanged.emit(bool(yes)); self._update_status()
        if yes:
            self._room_switch_active=False
            self._room_switch_reconnect_scheduled=False
            self._pending_room=None
            return
        if self._room_switch_active:
            if self._pending_room:
                self.room.setText(self._pending_room)
                if hasattr(self,'manual_room'):
                    self.manual_room.setText(self._pending_room)
            if not self._room_switch_reconnect_scheduled:
                self._room_switch_reconnect_scheduled=True
                QTimer.singleShot(250,self._reconnect_pending_room)
            return
        self._reset_session_view(); self._update_status()

    def _reconnect_pending_room(self):
        if not self._room_switch_active or not self._pending_room:
            self._room_switch_reconnect_scheduled=False
            return
        self.room.setText(self._pending_room)
        if hasattr(self,'manual_room'):
            self.manual_room.setText(self._pending_room)
        self._room_switch_reconnect_scheduled=False
        self.connect_frn()
    def _tx_granted(self,yes):
        self.ptt_active=bool(yes); self.pttStateChanged.emit(self.ptt_active); self._refresh_participant_tx_state(); self._update_status()
    def ptt(self,on,force=False):
        if not self.client or not self.connected:
            if on and not force:self._log('PTT: FRN ist nicht verbunden.')
            return
        self.ptt_active=bool(on); self.client.request_tx(bool(on)); self.pttStateChanged.emit(bool(on)); self._update_status()
    def toggle_ptt(self): self.ptt(not self.ptt_active)
    def ptt_settings(self): return self.ptt_mode.currentData(),self.ptt_limit_enabled.isChecked(),self.ptt_limit.value()
    def set_gateway_mode(self,is_gateway):
        radio_auto=bool(is_gateway)
        was_radio_auto=self._radio_auto_mode
        self._radio_auto_mode=radio_auto
        self.ptt_mode.setEnabled(not radio_auto); self.ptt_limit_enabled.setEnabled(not radio_auto); self.ptt_limit.setEnabled(not radio_auto); self.ptt_hint.setText('Funkmodus: keine manuelle FRN-PTT. Funk-RX/VOX steuert FRN TX automatisch; bei Funkende geht FRN sicher auf RX0.' if radio_auto else 'Die globale FRN-PTT befindet sich oben in FunkGateway und bleibt in jedem Reiter erreichbar.')
        if radio_auto and not was_radio_auto and self.ptt_active:
            self.ptt(False,force=True)
        if self.client_type.currentData()=='auto':
            desired=1 if radio_auto else 2
            if self._last_auto_client_type != desired:
                self._last_auto_client_type=desired
                self._log('FRN Client-Typ automatisch: '+('Gateway (CL=1)' if desired==1 else 'PC only (CL=2)'))
        else:
            self._last_auto_client_type=None

    def _explorer_result(self,rows):
        self.rows=list(rows or [])
        self._sm_backoff_index=0
        if hasattr(self,'_room_refresh_timer'):
            self._room_refresh_timer.setInterval(self._sm_auto_interval_ms)
        self.filter_servers()
        self.populate_rooms()

    def _explorer_error(self,text):
        self._log(str(text))
        delay=self._sm_backoff_steps_ms[min(self._sm_backoff_index,len(self._sm_backoff_steps_ms)-1)]
        self._sm_backoff_index=min(self._sm_backoff_index+1,len(self._sm_backoff_steps_ms)-1)
        if hasattr(self,'_room_refresh_timer'):
            self._room_refresh_timer.setInterval(delay)
        self._log(f'FRN SystemManager: automatische Aktualisierung pausiert für {delay//60000} Minute(n).')

    def _auto_manager_key(self):
        """Choose one manager for background refresh; never poll all managers automatically."""
        if self.selected_server_row:
            key=str(self.selected_server_row.get('manager','') or '')
            if key in MANAGERS:
                return key
        key=self.manager.currentData() if hasattr(self,'manager') else None
        return key if key in MANAGERS else None

    def _refresh_room_counts(self):
        """Polite background refresh of non-active room occupancy."""
        key=self._auto_manager_key()
        if not key:
            return
        try:
            self.explorer.refresh(key)
        except Exception as exc:
            self._explorer_error('FRN Raumbelegung: Aktualisierung fehlgeschlagen: '+str(exc))

    def filter_servers(self):
        query=(self.server_search.text() if hasattr(self,'server_search') else '').strip().casefold()
        selected_key=None
        if self.selected_server_row:
            selected_key=(str(self.selected_server_row.get('manager','')),str(self.selected_server_row.get('host','')).lower(),int(self.selected_server_row.get('port',0)))
        if query:
            self.filtered_rows=[x for x in self.rows if query in ' '.join((
                str(x.get('host','')), str(x.get('port','')), str(x.get('room','')),
                str(x.get('manager','')), str(x.get('clients',''))
            )).casefold()]
        else:
            self.filtered_rows=list(self.rows)
        self.server_table.setRowCount(len(self.filtered_rows))
        restore_row=-1
        for r,x in enumerate(self.filtered_rows):
            for c,val in enumerate((x.get('host',''),x.get('port',''),x.get('room',''),x.get('clients',0))):
                self.server_table.setItem(r,c,QTableWidgetItem(str(val)))
            key=(str(x.get('manager','')),str(x.get('host','')).lower(),int(x.get('port',0)))
            if selected_key and key==selected_key: restore_row=r
        if restore_row>=0:
            self.server_table.selectRow(restore_row)
        elif self.filtered_rows and not selected_key:
            self.server_table.selectRow(0)
        if hasattr(self,'explorer_status') and self.rows:
            base=f'{len(self.filtered_rows)} von {len(self.rows)} Servern' if query else f'{len(self.rows)} Server'
            self.explorer_status.setText(base)

    def connect_first_filtered_server(self):
        if not self.filtered_rows:
            return
        self.server_table.selectRow(0)
        self.use_selected_server(connect=False)
    def _set_explorer_status(self,t): self.explorer_status.setText(t)
    def use_selected_server(self,connect=False):
        r=self.server_table.currentRow()
        if r<0:return
        if r>=len(self.filtered_rows):return
        x=self.filtered_rows[r]
        new_host=x.get('host',''); new_port=int(x.get('port',10024)); new_mgr=x.get('manager')
        changed=(self.server.text().strip().lower()!=str(new_host).strip().lower() or self.port.value()!=new_port or self.manager.currentData()!=new_mgr)
        self.server.setText(new_host); self.port.setValue(new_port); self.manager.setCurrentIndex(max(0,self.manager.findData(new_mgr)))
        self.selected_server_row=dict(x)
        if changed:
            self.direct_rooms=[]
            if hasattr(self,'manual_room'): self.manual_room.clear()
        if not self.connected:
            self.room.clear()
        self.populate_rooms()
        advertised=str(x.get('room','')).strip()
        if advertised:
            for rr in range(self.room_table.rowCount()):
                it=self.room_table.item(rr,0)
                if it and it.text().strip()==advertised:
                    self.room_table.selectRow(rr)
                    if hasattr(self,'manual_room'): self.manual_room.setText(advertised)
                    break
        self._log(f"Server ausgewählt: {new_host}:{new_port}. Noch nicht verbunden; bitte Raum wählen.")
    def _direct_rooms(self,rooms): self.direct_rooms=[str(x).strip() for x in rooms or [] if str(x).strip()]; self.populate_rooms()
    def populate_rooms(self):
        host=self.server.text().strip().lower(); port=self.port.value(); mgr=self.manager.currentData(); sm={x.get('room',''):x.get('clients',0) for x in self.rows if x.get('manager')==mgr and x.get('host','').lower()==host and int(x.get('port',0))==port and x.get('room','')}; direct=set(self.direct_rooms); mode=self.room_source.currentData(); names=set(sm) if mode=='systemmanager' else direct if mode=='server' else set(sm)|direct
        selected=self.selected_room_name(); active=(self.client.cfg.net if self.connected and self.client else '')
        self.room_table.setRowCount(len(names))
        restore=-1
        for r,name in enumerate(sorted(names,key=str.lower)):
            origin='beide' if name in sm and name in direct else ('Server' if name in direct else 'SystemManager')
            clients=sm.get(name,'–')
            if active and name==active and self._active_room_count is not None:
                clients=self._active_room_count
            vals=(name,clients,origin)
            for c,v in enumerate(vals): self.room_table.setItem(r,c,QTableWidgetItem(str(v)))
            if name==selected: restore=r
        if restore>=0: self.room_table.selectRow(restore)
    def selected_room_name(self):
        r=self.room_table.currentRow(); it=self.room_table.item(r,0) if r>=0 else None
        return it.text().strip() if it else ''

    def _room_selection_changed(self):
        name=self.selected_room_name()
        if name and hasattr(self,'manual_room'):
            self.manual_room.setText(name)

    def join_selected_room(self):
        new=(self.manual_room.text().strip() if hasattr(self,'manual_room') else '') or self.selected_room_name()
        if not new:
            QMessageBox.information(self,'FRN','Bitte einen Raum auswählen oder einen Raumnamen manuell eingeben.')
            return
        self.room.setText(new)
        if self.connected:
            if self.client and self.client.cfg.net==new:
                # Auswahl-/Refresh-Ereignisse können denselben aktiven Raum
                # mehrfach anstoßen. Das ist kein Fehler und soll das Protokoll
                # nicht mit redundanten Meldungen füllen.
                return
            self._pending_room=new; self._room_switch_active=True; self._room_switch_reconnect_scheduled=False; self.disconnect_frn(room_switch=True)
        else:
            self.connect_frn()

    def switch_room(self):
        # Rückwärtskompatibler Alias für ältere Signalverbindungen.
        self.join_selected_room()
    def _own_name(self):
        if self.client and getattr(self.client,'cfg',None):
            return str(getattr(self.client.cfg,'callsign_user','') or '').strip()
        return self.callsign.text().strip()

    def _refresh_participant_tx_state(self):
        parts=[]
        for r in range(self.participants.rowCount()):
            parts.append({
                'name': self.participants.item(r,1).text() if self.participants.item(r,1) else '',
                'type': self.participants.item(r,2).text() if self.participants.item(r,2) else '',
                'band': self.participants.item(r,3).text() if self.participants.item(r,3) else '',
                'country': self.participants.item(r,4).text() if self.participants.item(r,4) else '',
                'city': self.participants.item(r,5).text() if self.participants.item(r,5) else '',
            })
        if parts:
            self.update_participants(parts)

    def update_participants(self,parts):
        parts=list(parts or []); self._active_room_count=len(parts); self.populate_rooms(); self.participants.setRowCount(len(parts)); red=self._radio_icon('#D32F2F'); green=self._radio_icon('#2E7D32'); orange=self._radio_icon('#F57C00')
        own=self._own_name()
        for r,p in enumerate(parts):
            name=str(p.get('name','')); own_tx=bool(self.ptt_active and own and name==own); remote_tx=bool(name==self.talker_name and name and not own_tx)
            iconitem=QTableWidgetItem(); iconitem.setIcon(orange if own_tx else red if remote_tx else green); self.participants.setItem(r,0,iconitem)
            for c,val in enumerate((name,p.get('type',''),p.get('band',''),p.get('country',''),p.get('city','')),start=1):
                it=QTableWidgetItem(str(val))
                if own_tx:
                    it.setForeground(QColor('#F57C00')); f=it.font(); f.setBold(True); it.setFont(f)
                elif remote_tx:
                    it.setForeground(QColor('#D32F2F')); f=it.font(); f.setBold(True); it.setFont(f)
                self.participants.setItem(r,c,it)
    def update_talker(self,name):
        self.talker_name=(name or '').strip(); self.talker.setText('FRN RX: '+(self.talker_name or '–')); self.talkerChanged.emit(self.talker_name); self.update_participants([{'name':self.participants.item(r,1).text() if self.participants.item(r,1) else '', 'type':self.participants.item(r,2).text() if self.participants.item(r,2) else '', 'band':self.participants.item(r,3).text() if self.participants.item(r,3) else '', 'country':self.participants.item(r,4).text() if self.participants.item(r,4) else '', 'city':self.participants.item(r,5).text() if self.participants.item(r,5) else ''} for r in range(self.participants.rowCount())])
    def _level(self,db,meter,label,prefix): meter.setValue(max(0,min(60,int(db+60)))); label.setText(f'{prefix}: {db:.1f} dBFS' if db>=-60 else f'{prefix}: < -60 dBFS')
    def _tx_level(self,db): self.tx_db=float(db); self._level(self.tx_db,self.tx_meter,self.tx_label,'TX'); self.levelsChanged.emit(self.rx_db,self.tx_db)
    def _rx_level(self,db): self.rx_db=float(db); self._level(self.rx_db,self.rx_meter,self.rx_label,'RX'); self.levelsChanged.emit(self.rx_db,self.tx_db)
    def _update_status(self):
        state='verbunden' if self.connected else 'getrennt'
        if self.connected and self.client:
            extra=f' · {self.client.cfg.server} · {self.client.cfg.net}'
        else:
            extra=''
        tx=' · TX' if self.ptt_active else (f' · RX {self.talker_name}' if self.talker_name else '')
        t=f'FRN: {state}{extra}{tx}'; self.state_label.setText(t); self.statusChanged.emit(t)
    def _log(self,t): self.log.appendPlainText(str(t))
    def to_config(self):
        return {'manager':self.manager.currentData(),'server':self.server.text(),'port':self.port.value(),'room':self.room.text(),'email':self.email.text(),'password':self.password.text(),'callsign':self.callsign.text(),'description':self.description.text(),'band':self.band.text(),'country':self.country.text(),'city':self.city.text(),'audio_enabled':self.audio_enabled.isChecked(),'audio_input':self.audio_in.currentData(),'audio_output':self.audio_out.currentData(),'ptt_mode':self.ptt_mode.currentData(),'explorer_manager':self.explorer_manager.currentData(),'client_type':self.client_type.currentData(),'protocol_version':self.protocol_version.text(),'manual_room':(self.manual_room.text() if hasattr(self,'manual_room') else ''),'ptt_limit_enabled':self.ptt_limit_enabled.isChecked(),'ptt_limit':self.ptt_limit.value()}
    def load_config(self,d):
        if not isinstance(d,dict):return
        for cb,key in ((self.manager,'manager'),(self.ptt_mode,'ptt_mode'),(self.explorer_manager,'explorer_manager'),(self.client_type,'client_type')):
            i=cb.findData(d.get(key));
            if i>=0:cb.setCurrentIndex(i)
        self.protocol_version.setText(str(d.get('protocol_version','20261016') or '20261016'));
        if hasattr(self,'manual_room'): self.manual_room.setText(d.get('manual_room',''))
        self.server.setText(d.get('server','')); self.port.setValue(int(d.get('port',10024) or 10024)); self.room.setText(d.get('room','')); self.email.setText(d.get('email','')); self.password.setText(d.get('password','')); self.callsign.setText(d.get('callsign','')); self.description.setText(d.get('description','FunkGateway UI')); self.band.setText(d.get('band','')); self.country.setText(d.get('country','Germany')); self.city.setText(d.get('city','')); self.audio_enabled.setChecked(bool(d.get('audio_enabled',True))); self.ptt_limit_enabled.setChecked(bool(d.get('ptt_limit_enabled',True))); self.ptt_limit.setValue(int(d.get('ptt_limit',180) or 180))
        for cb,key in ((self.audio_in,'audio_input'),(self.audio_out,'audio_output')):
            i=cb.findData(d.get(key));
            if i>=0:cb.setCurrentIndex(i)
