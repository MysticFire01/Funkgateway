"""Compact emoji picker for chat input fields.

FRN uses protocol-safe ASCII emoticons; Mumble supports Unicode emoji.
"""
from PySide6.QtWidgets import QMenu, QPushButton

MUMBLE_EMOJI = ("😀", "😁", "😂", "🤣", "😊", "😉", "😍", "😎",
                "😢", "😮", "👍", "👎", "👏", "👋", "❤️", "🎉",
                "🎙️", "📻", "⚓", "🏴‍☠️")
FRN_EMOTICONS = (":)", ":D", ";)", ":P", ":(", ":O", "^^", "<3",
                 ":-)", ":-D", ";-)", ":-P")


def emoji_button(entry, protocol="mumble", parent=None):
    button = QPushButton("☺", parent)
    button.setToolTip("Emoji auswählen" if protocol == "mumble"
                      else "FRN-kompatiblen Smiley auswählen")
    button.setMinimumWidth(34)
    menu = QMenu(button)
    values = MUMBLE_EMOJI if protocol == "mumble" else FRN_EMOTICONS
    for value in values:
        action = menu.addAction(value)
        action.triggered.connect(lambda _checked=False, symbol=value: (
            entry.insert(symbol), entry.setFocus()
        ))
    button.setMenu(menu)
    return button
