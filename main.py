#!/usr/bin/env python3
"""FunkGateway 0.5.6.20 program entry point."""
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from funkgateway.constants import APP_NAME
from funkgateway.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Bind the running Qt application to funkgateway-ui.desktop so GNOME/Ubuntu
    # uses the same pinned dock icon instead of creating a second generic icon.
    app.setDesktopFileName("funkgateway-ui")
    icon_path = Path(__file__).resolve().parent / "funkgateway.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    if icon_path.exists():
        win.setWindowIcon(QIcon(str(icon_path)))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
