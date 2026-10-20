"""Server-authorized list of registered Mumble users, independent of channel ACL."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,
    QPushButton,QTableWidget,QTableWidgetItem,QMessageBox)

class MumbleRegisteredPanel(QWidget):
    def __init__(self,client,parent=None):
        super().__init__(parent)
        self.client=client
        self._rows=[]
        self._pending=False
        v=QVBoxLayout(self)
        self.status=QLabel("Registrierte Benutzer werden nur bei Freigabe durch den Mumble-Server angezeigt.")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.search=QLineEdit()
        self.search.setPlaceholderText("Name oder Benutzer-ID suchen")
        self.search.textChanged.connect(self.filter)
        v.addWidget(self.search)
        self.table=QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(["Benutzername","Benutzer-ID","Zuletzt gesehen","Zuletzt genutzter Raum"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.table,1)
        actions=QHBoxLayout()
        self.reload=QPushButton("Benutzerliste laden")
        self.delete=QPushButton("Registrierung entfernen …")
        self.delete.setEnabled(False)
        self.reload.clicked.connect(self.load)
        self.delete.clicked.connect(self.remove)
        self.table.itemSelectionChanged.connect(self._selection)
        actions.addWidget(self.reload)
        actions.addWidget(self.delete)
        v.addLayout(actions)
        client.registeredUsersReceived.connect(self.received)
        client.aclDenied.connect(self.denied)
        client.connectedChanged.connect(self.connection_changed)

    def connection_changed(self,connected):
        self._pending=False
        self._rows=[]
        self.table.setRowCount(0)
        self.delete.setEnabled(False)
        self.status.setText("Verbunden. Liste bei Bedarf laden." if connected else "Nicht mit Mumble verbunden.")

    def load(self):
        self._pending=True
        self._rows=[]
        self.table.setRowCount(0)
        self.delete.setEnabled(False)
        self.status.setText("Fordere registrierte Benutzer beim Server an …")
        try:
            self.client.request_registered_users()
        except Exception as exc:
            self._pending=False
            self.status.setText("Benutzerliste konnte nicht angefordert werden: "+str(exc))
            return
        QTimer.singleShot(10000,self._timeout)

    def _timeout(self):
        if self._pending:
            self._pending=False
            self.status.setText("Keine Antwort vom Server innerhalb von 10 Sekunden. "
                "Ein Timeout allein beweist keine fehlenden Berechtigungen.")

    def denied(self,message):
        if self._pending:
            self._pending=False
            self._rows=[]
            self.table.setRowCount(0)
            self.delete.setEnabled(False)
            self.status.setText("Server hat die Anfrage abgelehnt: "+str(message))

    def received(self,rows):
        if not self._pending:
            return
        self._pending=False
        self._rows=sorted(rows,key=lambda r:str(r.get("name","")).casefold())
        self.status.setText(f"{len(rows)} Registrierungen vom Server erhalten.")
        self.filter()

    def filter(self,*_):
        term=self.search.text().strip().casefold()
        paths={}
        try:
            paths={int(c["id"]):str(c.get("name") or "") for c in self.client.channel_snapshot()}
        except Exception:
            pass
        self.table.setRowCount(0)
        for record in self._rows:
            if term not in str(record.get("name","")).casefold() and term not in str(record.get("user_id","")):
                continue
            cid=record.get("last_channel")
            room=paths.get(cid, f"ID {cid}" if cid is not None else "Nicht bekannt")
            if cid is not None and cid in paths:
                room=f"{room} (ID {cid})"
            n=self.table.rowCount()
            self.table.insertRow(n)
            for col,value in enumerate((record.get("name",""),record.get("user_id",""),
                                        record.get("last_seen",""),room)):
                self.table.setItem(n,col,QTableWidgetItem(str(value)))
        self.delete.setEnabled(False)
        self.table.resizeColumnsToContents()

    def _selection(self):
        self.delete.setEnabled(bool(self._rows) and self.table.currentRow()>=0)

    def remove(self):
        row=self.table.currentRow()
        if row<0:return
        uid=int(self.table.item(row,1).text())
        name=self.table.item(row,0).text()
        if uid<=0:
            QMessageBox.warning(self,"Mumble","Systemkonto kann nicht entfernt werden.")
            return
        answer=QMessageBox.question(self,"Registrierung löschen?",
            f"Registrierung von „{name}“ (ID {uid}) entfernen?\n"
            "Dabei können die Gruppenmitgliedschaften und individuellen Rechte verloren gehen.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        try:
            self.client.remove_registered_user(uid)
            self.status.setText("Löschanforderung gesendet; der Server entscheidet.")
            QTimer.singleShot(1200,self.load)
        except Exception as exc:
            QMessageBox.warning(self,"Mumble – Registrierung",str(exc))
