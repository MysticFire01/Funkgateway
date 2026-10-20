"""Mumble server BanList administration.

The server is authoritative. Never show bans until a fresh BanList reply.
Any modification is a full-list replacement, requiring explicit confirmation.
"""
import ipaddress
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QTableWidget,QTableWidgetItem,QMessageBox)

class MumbleBanPanel(QWidget):
    def __init__(self,client,parent=None):
        super().__init__(parent)
        self.client=client
        self._entries=[]
        self._pending=False
        self._authorized=False
        outer=QVBoxLayout(self)
        self.status=QLabel("Die Bannliste wird nur nach einer Antwort des Mumble-Servers angezeigt.")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.table=QTableWidget(0,5)
        self.table.setHorizontalHeaderLabels(["Name","IP / Netz","Grund","Seit","Dauer (Sek.)"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        outer.addWidget(self.table,1)
        buttons=QHBoxLayout()
        self.reload=QPushButton("Bannliste vom Server laden")
        self.remove_button=QPushButton("Ausgewählte Sperre entfernen …")
        self.remove_button.setEnabled(False)
        buttons.addWidget(self.reload)
        buttons.addWidget(self.remove_button)
        outer.addLayout(buttons)
        self.reload.clicked.connect(self.load)
        self.remove_button.clicked.connect(self.remove_selected)
        self.table.itemSelectionChanged.connect(self._selection)
        client.banListReceived.connect(self.received)
        client.aclDenied.connect(self.denied)
        client.connectedChanged.connect(self.connection_changed)

    def connection_changed(self,connected):
        self._clear("Verbunden. Bannliste bei Bedarf laden." if connected else "Nicht verbunden.")

    def _clear(self,message):
        self._authorized=False
        self._pending=False
        self._entries=[]
        self.table.setRowCount(0)
        self.remove_button.setEnabled(False)
        self.status.setText(message)

    def load(self):
        self._clear("Fordere aktuelle Bannliste vom Mumble-Server an …")
        self._pending=True
        try:
            self.client.request_ban_list()
        except Exception as exc:
            self._clear("Bannliste nicht verfügbar: "+str(exc))
            return
        QTimer.singleShot(8000,self._timeout)

    def _timeout(self):
        if self._pending:
            self._clear("Keine Antwort innerhalb von 8 Sekunden. Ein Timeout beweist kein fehlendes Serverrecht.")

    def denied(self,detail):
        if self._pending:
            self._clear("Zugriff auf die Bannliste verweigert: "+str(detail))
        elif self._authorized:
            self._clear("Der Server hat eine Änderung abgelehnt. Bitte erneut laden: "+str(detail))

    def received(self,entries):
        if not self._pending:
            return
        self._pending=False
        self._authorized=True
        self._entries=list(entries)
        self.table.setRowCount(0)
        for entry in self._entries:
            row=self.table.rowCount()
            self.table.insertRow(row)
            ip="Nicht verfügbar"
            try:
                ip=str(ipaddress.ip_address(entry["address"]))
                if ip.startswith("::ffff:"):
                    ip=ip[7:]
                ip+=f'/{entry["mask"]}'
            except (ValueError,KeyError,TypeError):
                pass
            for col,value in enumerate((entry.get("name",""),ip,entry.get("reason",""),
                                       entry.get("start",""),entry.get("duration",0))):
                self.table.setItem(row,col,QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        self.status.setText(f"{len(self._entries)} Sperren vom Server empfangen.")

    def _selection(self):
        self.remove_button.setEnabled(self._authorized and 0<=self.table.currentRow()<len(self._entries))

    def remove_selected(self):
        row=self.table.currentRow()
        if not self._authorized or row<0 or row>=len(self._entries):
            return
        name=self._entries[row].get("name") or self.table.item(row,1).text()
        answer=QMessageBox.question(self,"Mumble – Entbannen bestätigen",
            f"Die Sperre „{name}“ entfernen?\n"
            "Achtung: Das Mumble-Protokoll ersetzt beim Speichern die GESAMTE Bannliste. "
            "Änderungen anderer Administratoren seit dem Laden könnten überschrieben werden.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:
            return
        try:
            # Make the potentially destructive action explicit. Never assume that
            # a successful send means server-side acceptance.
            remaining=[dict(x) for i,x in enumerate(self._entries) if i!=row]
            self.client.replace_ban_list(remaining)
            self._clear("Entbannung an den Server gesendet. Zur Kontrolle neu laden.")
        except Exception as exc:
            QMessageBox.warning(self,"Mumble – Bannliste",str(exc))
