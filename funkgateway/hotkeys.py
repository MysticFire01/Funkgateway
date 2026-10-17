from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication


class ModifierHoldWatcher(QObject):
    """Watch only Ctrl/Alt/Shift/Meta state for hold-style PTT.

    No character keys or typed text are observed. Normal shortcuts remain
    handled by QShortcut elsewhere.
    """

    pressed = Signal()
    released = Signal()

    def __init__(self, parent=None, interval_ms: int = 40):
        super().__init__(parent)
        self._name = ""
        self._down = False
        self._timer = QTimer(self)
        self._timer.setInterval(max(20, int(interval_ms)))
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def set_key(self, name: str):
        name = str(name or "").strip()
        if name not in ("Ctrl", "Alt", "AltGr", "Shift", "Meta"):
            name = ""
        if name != self._name:
            self._name = name
            self._down = False

    def _poll(self):
        if not self._name:
            self._down = False
            return

        flags = {
            "Ctrl": Qt.KeyboardModifier.ControlModifier,
            "Alt": Qt.KeyboardModifier.AltModifier,
            "AltGr": Qt.KeyboardModifier.GroupSwitchModifier,
            "Shift": Qt.KeyboardModifier.ShiftModifier,
            "Meta": Qt.KeyboardModifier.MetaModifier,
        }
        wanted = flags[self._name]
        down = bool(QApplication.keyboardModifiers() & wanted)

        if down and not self._down:
            self._down = True
            self.pressed.emit()
        elif not down and self._down:
            self._down = False
            self.released.emit()
