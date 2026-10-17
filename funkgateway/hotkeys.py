from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Qt, QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QKeySequence


class ModifierHoldWatcher(QObject):
    """Watch only Ctrl/Alt/Shift/Meta state for hold-style PTT.

    No character keys or typed text are observed. Normal shortcuts remain
    handled by QShortcut elsewhere.
    """

    pressed = Signal()
    released = Signal()

    def __init__(self, parent=None, interval_ms: int = 10):
        super().__init__(parent)
        self._name = ""
        self._down = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(max(5, int(interval_ms)))
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


class LocalPttHotkey(QObject):
    """Press/release hotkey inside FunkGateway only.

    This observes only Qt key events delivered to this application and only
    compares them with the configured PTT key.
    """

    pressed = Signal()
    released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hotkey = ""
        self._active = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def set_hotkey(self, text: str):
        self._hotkey = str(text or "").strip()
        self._active = False

    def _matches(self, event):
        text = self._hotkey
        if not text:
            return False
        special = {
            "Ctrl": Qt.Key.Key_Control,
            "Alt": Qt.Key.Key_Alt,
            "AltGr": Qt.Key.Key_AltGr,
            "Shift": Qt.Key.Key_Shift,
            "Meta": Qt.Key.Key_Meta,
        }
        if text in special:
            return event.key() == special[text]
        try:
            actual = QKeySequence(event.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText)
            return actual == text
        except Exception:
            return False

    def eventFilter(self, obj, event):
        et = event.type()
        if et not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if not self._matches(event):
            return False
        if et == QEvent.Type.KeyPress:
            if not event.isAutoRepeat() and not self._active:
                self._active = True
                self.pressed.emit()
            return True
        if not event.isAutoRepeat() and self._active:
            self._active = False
            self.released.emit()
        return True
