"""Mumble channel description: rich text, HTML source and clickable links."""
import html
from PySide6.QtCore import Qt, QEvent, QUrl
from PySide6.QtGui import QTextCharFormat, QFont, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPlainTextEdit,
    QPushButton, QTabBar, QColorDialog, QInputDialog, QMessageBox, QStackedWidget,
)


class MumbleDescriptionEditor(QWidget):
    def __init__(self, markup="", parent=None):
        super().__init__(parent)
        self._loading = False
        self._original_markup = ""
        self._dirty = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.actions = []
        for caption, method in (("B", self.bold), ("I", self.italic), ("U", self.underline),
                                ("Farbe", self.color), ("Link", self.link)):
            button = QPushButton(caption)
            button.clicked.connect(method)
            button.setMaximumWidth(85)
            controls.addWidget(button)
            self.actions.append(button)
        controls.addStretch()
        layout.addLayout(controls)
        self.stack = QStackedWidget(self)
        self.rendered = QTextEdit()
        self.rendered.setAcceptRichText(True)
        self.rendered.setToolTip("Links mit Strg + Klick im Browser öffnen; normaler Klick bearbeitet den Text.")
        self.rendered.viewport().installEventFilter(self)
        self.source = QPlainTextEdit()
        self.stack.addWidget(self.rendered)
        self.stack.addWidget(self.source)
        self.stack.setMinimumHeight(100)
        layout.addWidget(self.stack, 1)
        self.mode = QTabBar()
        self.mode.addTab("Anzeige")
        self.mode.addTab("Quelltext")
        self.mode.currentChanged.connect(self._switch)
        layout.addWidget(self.mode)
        self.rendered.textChanged.connect(self._mark_dirty)
        self.source.textChanged.connect(self._mark_dirty)
        self.set_description(markup)

    def eventFilter(self, obj, event):
        if obj is self.rendered.viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                anchor = self.rendered.anchorAt(event.pos())
                if anchor:
                    url = QUrl(anchor)
                    if url.scheme().lower() in ("https", "http"):
                        QDesktopServices.openUrl(url)
                    else:
                        QMessageBox.warning(self, "Mumble", "Dieser Linktyp darf nicht geöffnet werden.")
                    return True
        return super().eventFilter(obj, event)

    def _mark_dirty(self):
        self._dirty = True

    def set_description(self, markup):
        markup = str(markup or "")
        self._original_markup = markup
        self.rendered.setHtml(markup)
        self.source.setPlainText(markup)
        self._dirty = False

    def set_loading(self, pending):
        self._loading = bool(pending)
        self.rendered.setReadOnly(pending)
        self.source.setReadOnly(pending)
        self.rendered.setPlaceholderText("Lade Beschreibung vom Mumble-Server …" if pending else "")
        for button in self.actions:
            button.setEnabled(not pending)

    def _switch(self, index):
        was_dirty = self._dirty
        if index == 1:
            if was_dirty:
                self.source.setPlainText(self.rendered.toHtml())
            else:
                self.source.setPlainText(self._original_markup)
        else:
            self.rendered.setHtml(self.source.toPlainText())
        self._dirty = was_dirty
        self.stack.setCurrentIndex(index)
        for button in self.actions:
            button.setVisible(index == 0 and not self._loading)

    def get_description(self):
        if not self._dirty:
            return self._original_markup
        return self.source.toPlainText() if self.mode.currentIndex() == 1 else self.rendered.toHtml()

    def _format(self, property_name, value):
        if self._loading:
            return
        fmt = QTextCharFormat()
        getattr(fmt, property_name)(value)
        self.rendered.textCursor().mergeCharFormat(fmt)
        self.rendered.mergeCurrentCharFormat(fmt)
        self.rendered.setFocus()

    def bold(self):
        weight = QFont.Weight.Normal if self.rendered.fontWeight() >= QFont.Weight.Bold else QFont.Weight.Bold
        self._format("setFontWeight", weight)

    def italic(self):
        self._format("setFontItalic", not self.rendered.fontItalic())

    def underline(self):
        self._format("setFontUnderline", not self.rendered.fontUnderline())

    def color(self):
        if self._loading:
            return
        chosen = QColorDialog.getColor(parent=self)
        if chosen.isValid():
            self._format("setForeground", chosen)

    def link(self):
        if self._loading:
            return
        url, ok = QInputDialog.getText(self, "Link einfügen", "Link-Adresse (https://…):")
        if not ok:
            return
        url = url.strip()
        parsed = QUrl(url)
        if parsed.scheme().lower() not in ("http", "https") or not parsed.host():
            QMessageBox.warning(self, "Mumble", "Bitte eine vollständige HTTP-/HTTPS-Adresse eingeben.")
            return
        cursor = self.rendered.textCursor()
        selected = cursor.selectedText() or url
        cursor.insertHtml('<a href="' + html.escape(url, quote=True) + '">' +
                          html.escape(selected) + '</a>')
