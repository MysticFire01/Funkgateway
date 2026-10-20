"""Permission-gated Mumble channel ACL editor.

Never shows cached ACL information. Only a fresh server ACL response reveals
groups/rules. All writes are subject to the server's own ACL checks.
"""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QDialog,QVBoxLayout,QHBoxLayout,QLabel,QCheckBox,QTableWidget,
    QTableWidgetItem,QPushButton,QMessageBox,QTabWidget,QWidget,QHeaderView,QListWidget,QListWidgetItem,QDialogButtonBox
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
    def __init__(self,mask,parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mumble-Berechtigungen auswählen")
        self.resize(410,540)
        self._other=int(mask)&~KNOWN_MASK
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel("Welche Aktionen sollen ausdrücklich erlaubt bzw. verweigert werden?"))
        self.list=QListWidget()
        for bit,name in PERMISSIONS:
            item=QListWidgetItem(name)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if int(mask)&bit else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole,bit)
            self.list.addItem(item)
        layout.addWidget(self.list,1)
        if self._other:
            layout.addWidget(QLabel("Unbekannte/zusätzliche Rechte-Bits bleiben unverändert erhalten."))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mask(self):
        value=self._other
        for i in range(self.list.count()):
            item=self.list.item(i)
            if item.checkState()==Qt.CheckState.Checked:
                value|=int(item.data(Qt.ItemDataRole.UserRole))
        return value


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
        QTimer.singleShot(0,self.request)

    def connection_state(self,connected):
        if not connected:
            self.denied("Mumble-Verbindung getrennt.")

    def request(self):
        self._loaded=False
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
        self.groups.setRowCount(0)
        self.rules.setRowCount(0)
        self.inherit.setEnabled(False)
        self.save.setEnabled(False)
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
        self.inherit.setChecked(bool(data["inherit_acls"]))
        self.inherit.setEnabled(True)
        for group in data["groups"]:
            n=self.groups.rowCount()
            self.groups.insertRow(n)
            vals=[group["name"],",".join(map(str,group["add"])),",".join(map(str,group["remove"])),
                  str(int(group["inherit"])),str(int(group["inheritable"]))]
            for c,v in enumerate(vals):self._cell(self.groups,n,c,v)
        for rule in data["rules"]:
            n=self.rules.rowCount()
            self.rules.insertRow(n)
            vals=[rule["group"],"" if rule["user_id"] is None else str(rule["user_id"]),
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
        cell=self.rules.item(row,col)
        if cell is None:return
        mask=cell.data(Qt.ItemDataRole.UserRole)
        if mask is None:mask=0
        picker=PermissionPicker(int(mask),self)
        if picker.exec()==QDialog.DialogCode.Accepted:
            self._permission_cell(row,col,picker.mask())

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

    @staticmethod
    def _ids(value):
        return [int(v.strip()) for v in value.split(",") if v.strip()]

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
                if uid:values["user_id"]=int(uid)
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
