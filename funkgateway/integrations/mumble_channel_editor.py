"""Mumble channel editor. Server permissions are authoritative."""
from PySide6.QtWidgets import (QDialog,QFormLayout,QLineEdit,QSpinBox,QCheckBox,
                               QDialogButtonBox,QLabel,QVBoxLayout)


class ChannelEditor(QDialog):
    def __init__(self,parent=None,create=True,details=None):
        super().__init__(parent)
        details=details or {}
        self.setWindowTitle("Mumble – Raum anlegen" if create else "Mumble – Raum bearbeiten")
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel("Der Server entscheidet über die erforderlichen Rechte."))
        form=QFormLayout()
        self.name=QLineEdit(str(details.get("name") or ""))
        self.name.setMaxLength(200)
        form.addRow("Raumname:",self.name)
        self.description=QLineEdit(str(details.get("description") or ""))
        form.addRow("Beschreibung:",self.description)
        self.temporary=QCheckBox("Temporärer Raum (wird bei Leerstand entfernt)")
        self.temporary.setChecked(bool(details.get("temporary",True if create else False)))
        self.temporary.setEnabled(create)
        form.addRow("Art:",self.temporary)
        self.position=QSpinBox()
        self.position.setRange(-100000,100000)
        self.position.setValue(int(details.get("position") or 0))
        form.addRow("Reihenfolge / Position:",self.position)
        layout.addLayout(form)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _accept(self):
        if not self.name.text().strip():
            self.name.setFocus()
            return
        self.accept()

    def values(self):
        return dict(name=self.name.text().strip(),
                    description=self.description.text().strip(),
                    temporary=self.temporary.isChecked(),
                    position=self.position.value())
