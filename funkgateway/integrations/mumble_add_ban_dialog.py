"""Dialog for creating a Mumble server ban entry."""
import ipaddress
from datetime import datetime, timezone
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QSpinBox,
    QComboBox,QDialogButtonBox,QMessageBox)

class MumbleAddBanDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mumble – Sperre hinzufügen")
        self.resize(490,280)
        outer=QVBoxLayout(self)
        form=QFormLayout()
        self.name=QLineEdit()
        self.address=QLineEdit()
        self.address.setPlaceholderText("z. B. 192.0.2.10 oder 2001:db8::1")
        self.mask=QSpinBox()
        self.mask.setRange(0,32)
        self.mask.setValue(32)
        self.address.textChanged.connect(self._address_changed)
        self.reason=QLineEdit()
        self.hash=QLineEdit()
        self.hash.setPlaceholderText("Optional: Zertifikat-Hash")
        self.duration=QComboBox()
        self.duration.addItem("Dauerhaft",0)
        self.duration.addItem("1 Stunde",3600)
        self.duration.addItem("1 Tag",86400)
        self.duration.addItem("7 Tage",604800)
        self.duration.addItem("30 Tage",2592000)
        self.duration.addItem("Eigene Dauer (Sekunden)",-1)
        self.custom_seconds=QSpinBox()
        self.custom_seconds.setRange(1,2147483647)
        self.custom_seconds.setValue(3600)
        self.custom_seconds.setEnabled(False)
        self.duration.currentIndexChanged.connect(lambda _:self.custom_seconds.setEnabled(self.duration.currentData()==-1))
        form.addRow("Benutzername:",self.name)
        form.addRow("IP-Adresse:",self.address)
        form.addRow("Netzmaske (CIDR):",self.mask)
        form.addRow("Begründung:",self.reason)
        form.addRow("Zertifikat-Hash:",self.hash)
        form.addRow("Dauer:",self.duration)
        form.addRow("Eigene Dauer:",self.custom_seconds)
        outer.addLayout(form)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

    def _address_changed(self,text):
        try:
            maximum=32 if ipaddress.ip_address(text.strip()).version==4 else 128
        except ValueError:
            maximum=128 if ":" in text else 32
        self.mask.setRange(0,maximum)
        if self.mask.value()>maximum:
            self.mask.setValue(maximum)

    def accept(self):
        try:
            address=ipaddress.ip_address(self.address.text().strip())
        except ValueError:
            QMessageBox.warning(self,"Mumble","Bitte eine gültige IPv4- oder IPv6-Adresse eingeben.")
            return
        # Avoid accidental global bans (0.0.0.0/0 or ::/0).
        if self.mask.value()==0:
            QMessageBox.warning(self,"Mumble","Eine Netzmaske /0 würde alle IP-Adressen sperren und wird hier nicht erlaubt.")
            return
        if not self.name.text().strip() and not self.hash.text().strip() and not self.address.text().strip():
            QMessageBox.warning(self,"Mumble","Mindestens ein Sperrkriterium fehlt.")
            return
        if address.version==4:
            mapped=ipaddress.IPv6Address("::ffff:"+str(address))
            raw=mapped.packed
            mask=96+self.mask.value()
        else:
            raw=address.packed
            mask=self.mask.value()
        duration=int(self.duration.currentData())
        if duration==-1:
            duration=self.custom_seconds.value()
        self.entry={
            "address":raw,"mask":mask,
            "name":self.name.text().strip(),
            "reason":self.reason.text().strip(),
            "hash":self.hash.text().strip(),
            "start":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration":duration,
        }
        super().accept()
