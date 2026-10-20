"""Permission-gated Mumble channel ACL editor.

Never shows cached ACL information. Only a fresh server ACL response reveals
groups/rules. All writes are subject to the server's own ACL checks.
"""
import re
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QDialog,QVBoxLayout,QHBoxLayout,QLabel,QCheckBox,QTableWidget,
    QTableWidgetItem,QPushButton,QMessageBox,QTabWidget,QWidget,QHeaderView,QListWidget,QListWidgetItem,QDialogButtonBox,QComboBox,QInputDialog,QLineEdit
)



# Mumble Permission flags are stable protocol bits, not UI-specific indexes.
PERMISSIONS = [
    (0x1,"ACL verwalten"),(0x2,"Raum durchqueren"),(0x4,"Raum betreten"),
    (0x8,"Sprechen"),(0x10,"Andere stumm/taub schalten"),
    (0x20,"Benutzer verschieben"),(0x40,"Permanente Räume anlegen"),
    (0x80,"Räume verknüpfen"),(0x100,"Flüstern"),
    (0x200,"Textnachrichten senden"),(0x400,"Temporäre Räume anlegen"),
    (0x10000,"Benutzer kicken"),(0x20000,"Benutzer bannen"),
    (0x40000,"Benutzer registrieren"),(0x80000,"Selbstregistrierung"),
    (0x100000,"Benutzerdaten zurücksetzen"),
]
KNOWN_MASK=sum(bit for bit,_ in PERMISSIONS)


class PermissionPicker(QDialog):
    def __init__(self,grant,deny,parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mumble-Rechte: Erlauben / Verweigern / Nicht festgelegt")
        self.resize(590,600)
        self._grant_extra=int(grant)&~KNOWN_MASK
        self._deny_extra=int(deny)&~KNOWN_MASK
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel("Jedes Recht hat drei Zustände. Nicht festgelegt lässt andere ACL-Regeln entscheiden."))
        self.choices=[]
        form=QTableWidget(len(PERMISSIONS),2)
        form.setHorizontalHeaderLabels(["Berechtigung","Einstellung"])
        form.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row,(bit,name) in enumerate(PERMISSIONS):
            cell=QTableWidgetItem(name)
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            form.setItem(row,0,cell)
            combo=QComboBox()
            combo.addItems(["Nicht festgelegt","Erlauben","Verweigern"])
            combo.setCurrentIndex(1 if int(grant)&bit else (2 if int(deny)&bit else 0))
            form.setCellWidget(row,1,combo)
            self.choices.append((bit,combo))
        layout.addWidget(form,1)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def masks(self):
        grant,deny=self._grant_extra,self._deny_extra
        for bit,combo in self.choices:
            if combo.currentIndex()==1:grant|=bit
            elif combo.currentIndex()==2:deny|=bit
        return grant,deny


def permission_names(mask):
    known=[name for bit,name in PERMISSIONS if int(mask)&bit]
    other=int(mask)&~KNOWN_MASK
    if other: known.append(f"Weitere Rechte ({hex(other)})")
    return ", ".join(known) if known else "Keine Rechte ausgewählt"

class MumbleAclDialog(QDialog):
    def __init__(self,client,channel_id,channel_name,parent=None):
        super().__init__(parent)
        self.client=client
        self.channel_id=int(channel_id)
        self._loaded=False
        self._user_names={}
        self.setWindowTitle("Mumble-Rechte – "+str(channel_name))
        self.resize(840,530)
        layout=QVBoxLayout(self)
        self.status=QLabel("Warte auf Freigabe und ACL-Antwort des Mumble-Servers …")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.inherit=QCheckBox("ACLs vom übergeordneten Raum erben")
        self.inherit.setEnabled(False)
        layout.addWidget(self.inherit)
        tabs=QTabWidget()
        layout.addWidget(tabs,1)
        self.groups=QTableWidget(0,5)
        self.groups.setHorizontalHeaderLabels(["Gruppe","Mitglieder hinzufügen (IDs)","Mitglieder ausschließen (IDs)","Erben","Weitervererben"])
        self.rules=QTableWidget(0,7)
        self.rules.cellDoubleClicked.connect(self._edit_permissions)
        self.rules.setHorizontalHeaderLabels(["Gruppe","Benutzer (ID)","Erlaubte Rechte","Verweigerte Rechte","Hier","Unterräume","Geerbt"])
        for label,table in [("Gruppen",self.groups),("ACL-Regeln",self.rules)]:
            page=QWidget()
            v=QVBoxLayout(page)
            v.addWidget(table)
            controls=QHBoxLayout()
            add=QPushButton("Eintrag hinzufügen")
            remove=QPushButton("Ausgewählten Eintrag entfernen")
            add.clicked.connect(lambda checked=False,t=table:self._add_row(t))
            remove.clicked.connect(lambda checked=False,t=table:self._remove_row(t))
            controls.addWidget(add)
            controls.addWidget(remove)
            v.addLayout(controls)
            table._add_button=add
            table._remove_button=remove
            add.setEnabled(False)
            remove.setEnabled(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            tabs.addTab(page,label)
        self.member_add=QPushButton("Registrierten Benutzer zur ausgewählten Gruppe hinzufügen …")
        self.member_add.setEnabled(False)
        self.member_add.clicked.connect(self._add_member)
        layout.addWidget(self.member_add)
        registered=QWidget(self)
        self._registered_widget=registered
        reglayout=QVBoxLayout(registered)
        self.registered_status=QLabel("Benutzerliste noch nicht beim Server abgefragt.")
        reglayout.addWidget(self.registered_status)
        self.registered_filter=QLineEdit()
        self.registered_filter.setPlaceholderText("Nach Namen oder ID suchen …")
        reglayout.addWidget(self.registered_filter)
        self.registered=QTableWidget(0,3)
        self.registered.setHorizontalHeaderLabels(["Name","Benutzer-ID","Zuletzt gesehen"])
        self.registered.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.registered.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        reglayout.addWidget(self.registered,1)
        controls=QHBoxLayout()
        self.load_registered=QPushButton("Registrierte Benutzer vom Server laden")
        self.delete_registered=QPushButton("Ausgewählte Registrierung entfernen …")
        self.delete_registered.setEnabled(False)
        self.load_registered.clicked.connect(self._request_registered)
        self.delete_registered.clicked.connect(self._remove_registered)
        self.registered_filter.textChanged.connect(self._filter_registered)
        controls.addWidget(self.load_registered)
        controls.addWidget(self.delete_registered)
        reglayout.addLayout(controls)
        # The registered-user directory is its own Mumble integration tab.
        # This hidden model supports the group-user picker without duplicating the UI.
        self._registered_rows=[]
        client.registeredUsersReceived.connect(self._registered_received)
        self.registered.itemSelectionChanged.connect(lambda:self.delete_registered.setEnabled(
            self._loaded and self.registered.currentRow()>=0))
        note=QLabel("Doppelklick auf Erlaubte/Verweigerte Rechte öffnet die Rechteauswahl. "
                    "Geerbte Regeln sind nur lesbar. Der Server entscheidet über Änderungen.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons=QHBoxLayout()
        self.reload=QPushButton("Vom Server neu laden")
        self.save=QPushButton("ACL-Änderungen speichern")
        self.save.setEnabled(False)
        cancel=QPushButton("Schließen")
        buttons.addWidget(self.reload);buttons.addStretch()
        buttons.addWidget(self.save);buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.reload.clicked.connect(self.request)
        self.save.clicked.connect(self.persist)
        cancel.clicked.connect(self.close)
        client.aclReceived.connect(self.received)
        client.aclDenied.connect(self.denied)
        client.connectedChanged.connect(self.connection_state)
        self._directory_poll=QTimer(self)
        self._directory_poll.setInterval(500)
        self._directory_poll.timeout.connect(self._poll_directory)
        QTimer.singleShot(0,self.request)

    def _poll_directory(self):
        if not self._loaded:
            self._directory_poll.stop()
            return
        cached=self.client.cached_registered_users()
        if cached:
            fingerprint=tuple(sorted((int(r["user_id"]),str(r.get("name",""))) for r in cached))
            if fingerprint!=getattr(self,"_directory_fingerprint",None):
                self._directory_fingerprint=fingerprint
                self._registered_received(cached)
            self._directory_poll.stop()

    def _request_registered(self):
        if not self._loaded:
            QMessageBox.warning(self,"Keine Berechtigung","Zuerst muss die ACL des Raums erfolgreich gelesen werden.")
            return
        cached=self.client.cached_registered_users()
        if cached:
            self._registered_pending=True
            self._registered_received(cached)
            return
        if getattr(self,"_registered_pending",False):
            self.registered_status.setText("Benutzerliste wird bereits vom Server angefordert …")
            return
        self._registered_pending=True
        self.registered.setRowCount(0)
        self._registered_rows=[]
        self.delete_registered.setEnabled(False)
        self.registered_status.setText("Frage registrierte Benutzer beim Server an …")
        try:
            self.client.request_registered_users()
        except Exception as exc:
            self.registered_status.setText("Benutzerliste nicht verfügbar: "+str(exc))
            self._registered_pending=False
            return
        QTimer.singleShot(10000,self._registered_timeout)

    def _registered_timeout(self):
        if getattr(self,"_registered_pending",False):
            self._registered_pending=False
            self.registered_status.setText("Keine Antwort auf die UserList-Anfrage innerhalb von 10 Sekunden. "
                "Das ist kein Beleg für fehlende Administratorrechte. "
                "Bitte Mumble-Serverversion und Debug-Protokoll prüfen.")

    def _registered_received(self,rows):
        if not self._loaded:
            return
        self._registered_pending=False
        self._directory_fingerprint=tuple(sorted((int(r["user_id"]),str(r.get("name",""))) for r in rows))
        # Store the directory FIRST. A malformed display row must never prevent
        # the member picker from receiving the successful server result.
        self._registered_rows=sorted(
            [dict(r) for r in rows if r.get("user_id") is not None],
            key=lambda r:str(r.get("name","")).casefold())
        for user in self._registered_rows:
            try:
                uid=int(user["user_id"])
                name=str(user.get("name") or "").strip()
                if name:self._user_names[uid]=name
            except (ValueError,TypeError):
                continue
        self.registered_status.setText(
            f"{len(self._registered_rows)} registrierte Benutzer vom Server empfangen.")
        # An ACL group is keyed by persistent IDs, not names. Redraw existing
        # labels, preserving the membership IDs even if one name is unknown.
        for row in range(self.groups.rowCount()):
            for col in (1,2):
                value=self._text(self.groups,row,col)
                if not value:
                    continue
                try:
                    ids=self._ids(value)
                    self._cell(self.groups,row,col,
                               ",".join(self._user_label(uid) for uid in ids))
                except (TypeError,ValueError):
                    pass
        for row in range(self.rules.rowCount()):
            value=self._text(self.rules,row,1)
            if not value:
                continue
            try:
                uid=self._parse_user_id(value)
                self._cell(self.rules,row,1,self._user_label(uid))
            except (TypeError,ValueError):
                pass
        self._filter_registered()
        if hasattr(self,"_refresh_group_ui"):
            selected=self.group_select.currentIndex()
            self._refresh_group_ui()
            if selected>=0 and selected<self.group_select.count():
                self.group_select.setCurrentIndex(selected)
        if hasattr(self,"_refresh_rule_ui"):
            selected=self.rule_list.currentRow()
            self._refresh_rule_ui(max(0,selected))

    def _filter_registered(self,*_):
        term=self.registered_filter.text().strip().casefold()
        rows=[r for r in self._registered_rows
              if term in str(r["name"]).casefold() or term in str(r["user_id"])]
        self.registered.setRowCount(0)
        for r in rows:
            n=self.registered.rowCount()
            self.registered.insertRow(n)
            for col,value in enumerate((r["name"],r["user_id"],r.get("last_seen",""))):
                self._cell(self.registered,n,col,value)
        self.delete_registered.setEnabled(False)

    def _selected_registered(self):
        row=self.registered.currentRow()
        if row<0:return None
        return {"name":self._text(self.registered,row,0),
                "user_id":int(self._text(self.registered,row,1))}

    def _add_member(self):
        if not self._loaded:return
        row=self.groups.currentRow()
        if row<0:
            QMessageBox.information(self,"Gruppe auswählen",
                "Bitte zuerst eine Gruppe in der Gruppentabelle auswählen.")
            return
        candidates=self._registered_rows
        if not candidates:
            self._request_registered()
            QMessageBox.information(self,"Benutzerliste wird geladen",
                "Die Liste registrierter Benutzer wurde angefordert. "
                "Nach dem Empfang kannst du den Benutzer hier auswählen.")
            return
        choices=[f"{u['name']} (ID {u['user_id']})" for u in candidates]
        selected,ok=QInputDialog.getItem(self,"Gruppenmitglied hinzufügen",
                    "Registrierten Benutzer auswählen:",choices,0,False)
        if not ok or not selected:return
        uid=self._parse_user_id(selected)
        cell=self.groups.item(row,1)
        ids=self._ids(cell.text() if cell else "")
        if uid not in ids:ids.append(uid)
        self._cell(self.groups,row,1,",".join(self._user_label(v) for v in ids))
        self.status.setText("Mitglied vorgemerkt. Bitte ACL-Änderungen speichern.")

    def _remove_registered(self):
        user=self._selected_registered()
        if user is None or not self._loaded:return
        uid=user["user_id"]
        if uid<=0:
            QMessageBox.warning(self,"Schutz","Systembenutzer können nicht entfernt werden.")
            return
        answer=QMessageBox.question(self,"Registrierung endgültig entfernen?",
            f"Die Registrierung von „{user['name']}“ (ID {uid}) entfernen?\\n"
            "Dies ist kein Kick/Ban. Zugeordnete Gruppenrechte können verloren gehen.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        try:
            self.client.remove_registered_user(uid)
            self.registered_status.setText("Entfernung beantragt; Serverbestätigung steht aus.")
            QTimer.singleShot(900,self._request_registered)
        except Exception as exc:
            QMessageBox.warning(self,"Registrierung entfernen",str(exc))

    def connection_state(self,connected):
        if not connected:
            self.denied("Mumble-Verbindung getrennt.")

    def request(self):
        self._loaded=False
        self._directory_poll.stop()
        self._directory_fingerprint=None
        self._clear()
        self.status.setText("Rechte werden vom Server angefordert …")
        self._request_pending=True
        try:
            self.client.request_channel_acl(self.channel_id)
        except Exception as exc:
            self.denied(str(exc))
            return
        QTimer.singleShot(3500,self._timeout)

    def _timeout(self):
        if getattr(self,"_request_pending",False):
            self.denied("Keine ACL-Antwort vom Mumble-Server erhalten. "
                        "Möglicherweise fehlt das Recht zur Einsicht.")

    def _clear(self):
        self._registered_pending=False
        self._registered_rows=[]
        self._user_names={}
        self.registered.setRowCount(0)
        self.registered_status.setText("Keine Benutzerliste freigegeben.")
        self.groups.setRowCount(0)
        self.rules.setRowCount(0)
        self.inherit.setEnabled(False)
        self.save.setEnabled(False)
        self.member_add.setEnabled(False)
        self.delete_registered.setEnabled(False)
        for t in (self.groups,self.rules):
            t._add_button.setEnabled(False)
            t._remove_button.setEnabled(False)

    def denied(self,message):
        if not getattr(self,"_request_pending",False):
            # Any later server denial can also be a rejected edit.
            if self._loaded:
                self.status.setText("Server hat eine Änderung abgelehnt: "+str(message))
            return
        self._request_pending=False
        self._loaded=False
        self._clear()
        self.status.setText("Keine Berechtigung zur ACL-Einsicht: "+str(message))
        QMessageBox.warning(self,"Mumble – Rechte verweigert",self.status.text())

    @staticmethod
    def _cell(table,row,col,value):
        table.setItem(row,col,QTableWidgetItem(str(value)))

    def received(self,data):
        if int(data.get("channel_id",-1))!=self.channel_id or not getattr(self,"_request_pending",False):
            return
        self._request_pending=False
        self._loaded=True
        self._clear()
        self._user_names=self.client.registered_user_names()
        # Use an already authenticated UserList before drawing ACL entries.
        # The separate Mumble users tab may have loaded it earlier.
        directory=self.client.cached_registered_users()
        for user in directory:
            try:
                self._user_names[int(user["user_id"])]=str(user.get("name") or "")
            except (ValueError,TypeError,KeyError):
                continue
        self.inherit.setChecked(bool(data["inherit_acls"]))
        self.inherit.setEnabled(True)
        for group in data["groups"]:
            n=self.groups.rowCount()
            self.groups.insertRow(n)
            vals=[group["name"],",".join(self._user_label(v) for v in group["add"]),
                  ",".join(self._user_label(v) for v in group["remove"]),
                  str(int(group["inherit"])),str(int(group["inheritable"]))]
            for c,v in enumerate(vals):self._cell(self.groups,n,c,v)
        for rule in data["rules"]:
            n=self.rules.rowCount()
            self.rules.insertRow(n)
            vals=[rule["group"],"" if rule["user_id"] is None else self._user_label(rule["user_id"]),
                  hex(rule["grant"]),hex(rule["deny"]),str(int(rule["apply_here"])),
                  str(int(rule["apply_subs"])),str(int(rule["inherited"]))]
            for c,v in enumerate(vals):self._cell(self.rules,n,c,v)
            self._permission_cell(n,2,rule["grant"])
            self._permission_cell(n,3,rule["deny"])
            if rule["inherited"]:
                for c in range(7):
                    cell=self.rules.item(n,c)
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._source_groups=data["groups"]
        self._source_rules=data["rules"]
        self.status.setText("ACL vom Server empfangen. Änderungen nur entsprechend deiner Serverrechte.")
        self.save.setEnabled(True)
        self.member_add.setEnabled(True)
        self._request_registered()
        self._directory_poll.start()
        for t in (self.groups,self.rules):
            t._add_button.setEnabled(True)
            t._remove_button.setEnabled(True)

    def _permission_cell(self,row,col,mask):
        cell=self.rules.item(row,col)
        if cell is None:
            cell=QTableWidgetItem()
            self.rules.setItem(row,col,cell)
        cell.setText(permission_names(mask))
        cell.setToolTip("Doppelklick: Rechte per Häkchen auswählen")
        cell.setData(Qt.ItemDataRole.UserRole,int(mask))
        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def _edit_permissions(self,row,col):
        if not self._loaded or col not in (2,3) or self._text(self.rules,row,6)=="1":
            return
        picker=PermissionPicker(self._mask(row,2),self._mask(row,3),self)
        if picker.exec()==QDialog.DialogCode.Accepted:
            grant,deny=picker.masks()
            self._permission_cell(row,2,grant)
            self._permission_cell(row,3,deny)

    def _mask(self,row,col):
        item=self.rules.item(row,col)
        if item is None:return 0
        value=item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else int(item.text().strip() or "0",0)

    def _add_row(self,table):
        if not self._loaded:return
        n=table.rowCount()
        table.insertRow(n)
        values=(["","","","1","1"] if table is self.groups
                else ["all","","0","0","1","1","0"])
        for c,value in enumerate(values):self._cell(table,n,c,value)
        if table is self.rules:
            self._permission_cell(n,2,0)
            self._permission_cell(n,3,0)

    def _remove_row(self,table):
        if not self._loaded:return
        n=table.currentRow()
        if n<0:return
        if table is self.rules and self._text(table,n,6)=="1":
            QMessageBox.warning(self,"Mumble","Geerbte ACL-Regeln können hier nicht entfernt werden.")
            return
        table.removeRow(n)

    @staticmethod
    def _text(table,row,column):
        item=table.item(row,column)
        return item.text().strip() if item else ""

    def _user_label(self,user_id):
        uid=int(user_id)
        name=self._user_names.get(uid,"")
        return f"{name} (ID {uid})" if name else f"ID {uid} (Name unbekannt)"

    @staticmethod
    def _parse_user_id(text):
        text=str(text or "").strip()
        if text.isdecimal():
            return int(text)
        match=re.search(r"\\bID\\s+(\\d+)\\b",text,re.I)
        if match:
            return int(match.group(1))
        raise ValueError("Benutzer-ID nicht erkennbar. Bitte Zahl oder 'Name (ID 123)' verwenden.")

    @classmethod
    def _ids(cls,value):
        return [cls._parse_user_id(v) for v in value.split(",") if v.strip()]

    def persist(self):
        if not self._loaded:return
        try:
            groups=[]
            for row in range(self.groups.rowCount()):
                name=self._text(self.groups,row,0)
                if not name:raise ValueError("Gruppenname darf nicht leer sein.")
                groups.append(dict(name=name,inherited=False,inherit=bool(int(self._text(self.groups,row,3))),
                    inheritable=bool(int(self._text(self.groups,row,4))),
                    add=self._ids(self._text(self.groups,row,1)),
                    remove=self._ids(self._text(self.groups,row,2))))
            rules=[]
            for row in range(self.rules.rowCount()):
                if self._text(self.rules,row,6)=="1":continue
                group=self._text(self.rules,row,0)
                uid=self._text(self.rules,row,1)
                if not group and not uid:raise ValueError("Regel benötigt Gruppe oder Benutzer-ID.")
                values=dict(inherited=False,user_id=None,group=None,apply_here=bool(int(self._text(self.rules,row,4))),
                    apply_subs=bool(int(self._text(self.rules,row,5))),
                    grant=self._mask(row,2),
                    deny=self._mask(row,3))
                if uid:values["user_id"]=self._parse_user_id(uid)
                else:values["group"]=group
                rules.append(values)
            confirm=QMessageBox.question(self,"ACL-Änderungen senden?",
                "Die ACL-Regeln dieses Raums werden vollständig an den Mumble-Server "
                "gesendet. Falsche Rechte können den Zugriff verändern. Fortfahren?",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if confirm!=QMessageBox.StandardButton.Yes:return
            self.client.save_channel_acl(self.channel_id,self.inherit.isChecked(),groups,rules)
            self.status.setText("ACL-Änderung gesendet. Die serverseitige Annahme ist noch nicht bestätigt.")
        except Exception as exc:
            QMessageBox.warning(self,"Mumble – ACL nicht gespeichert",str(exc))
