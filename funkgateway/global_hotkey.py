from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class GlobalPttHotkey(QObject):
    pressed = Signal()
    released = Signal()
    statusChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listener = None
        self._hotkey = ""
        self._pressed = set()
        self._active = False

    def set_hotkey(self, text: str):
        self._hotkey = str(text or "").strip()
        self._active = False
        self._pressed.clear()

    def start(self):
        if self._listener is not None:
            return True
        try:
            from pynput import keyboard
        except Exception as exc:
            self.statusChanged.emit(f"Globaler Hotkey nicht verfügbar: {exc}")
            return False

        self._keyboard = keyboard
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,
        )
        self._listener.daemon = True
        self._listener.start()
        self.statusChanged.emit("Globaler Hotkey aktiv")
        return True

    def stop(self):
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

    def _token(self, key):
        k = self._keyboard.Key
        groups = (
            ((k.ctrl, k.ctrl_l, k.ctrl_r), "Ctrl"),
            ((k.alt, k.alt_l, k.alt_r), "Alt"),
            ((k.shift, k.shift_l, k.shift_r), "Shift"),
            ((k.cmd, k.cmd_l, k.cmd_r), "Meta"),
        )
        for keys, name in groups:
            if key in keys:
                return name
        if getattr(k, "alt_gr", None) is not None and key == k.alt_gr:
            return "AltGr"
        name = getattr(key, "name", None)
        if name:
            return name.upper() if name.startswith("f") and name[1:].isdigit() else name
        char = getattr(key, "char", None)
        if char:
            return char.upper()
        return ""

    def _wanted(self):
        return {part.strip() for part in self._hotkey.split("+") if part.strip()}

    def _on_press(self, key):
        token = self._token(key)
        if not token:
            return
        self._pressed.add(token)
        wanted = self._wanted()
        if wanted and wanted.issubset(self._pressed) and not self._active:
            self._active = True
            self.pressed.emit()

    def _on_release(self, key):
        token = self._token(key)
        if token:
            self._pressed.discard(token)
        if self._active and not self._wanted().issubset(self._pressed):
            self._active = False
            self.released.emit()
