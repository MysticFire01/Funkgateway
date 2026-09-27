"""Theme support for FunkGateway UI 0.6.x."""
from PySide6.QtGui import QPalette

SCHEMES = {
    "Funk Blau": {"accent": "#2F80ED"},
    "Radio Grün": {"accent": "#2E9D57"},
    "Graphit": {"accent": "#708090"},
    "Nachtfunk": {"accent": "#27C2C2", "dark_bg": "#0D1518", "dark_panel": "#142126", "dark_panel_alt": "#1A2A30"},
    "Bernstein": {"accent": "#D99018"},
    "Kontrast": {"accent": "#FFD400", "contrast": True},
}

MODE_COLORS = {
    "pc": "#2F80ED",
    "gateway": "#2E9D57",
    "radio_parrot": "#F2994A",
    "voip_parrot": "#9B51E0",
}


def _rgb(value):
    value=value.lstrip('#')
    return tuple(int(value[i:i+2],16) for i in (0,2,4))


def contrast_text(background):
    r,g,b=_rgb(background)
    lum=(0.299*r + 0.587*g + 0.114*b)
    return "#111111" if lum >= 155 else "#FFFFFF"


def system_is_dark(app):
    try:
        return app.palette().color(QPalette.Window).lightness() < 128
    except Exception:
        return False


def palette_for(app, theme_mode="System", scheme_name="Funk Blau"):
    scheme=SCHEMES.get(scheme_name,SCHEMES["Funk Blau"])
    mode=str(theme_mode or "System")
    dark=(mode=="Dunkel") or (mode=="System" and system_is_dark(app))
    if scheme.get("contrast"):
        if dark:
            p={"bg":"#000000","panel":"#080808","panel_alt":"#151515","text":"#FFFFFF","muted":"#E6E6E6","border":"#FFFFFF"}
        else:
            p={"bg":"#FFFFFF","panel":"#FFFFFF","panel_alt":"#F2F2F2","text":"#000000","muted":"#202020","border":"#000000"}
    elif dark:
        p={
            "bg":scheme.get("dark_bg","#1B1F24"),
            "panel":scheme.get("dark_panel","#242A31"),
            "panel_alt":scheme.get("dark_panel_alt","#2D343D"),
            "text":"#F3F6F8","muted":"#B8C0C8","border":"#47515D",
        }
    else:
        p={"bg":"#F4F6F8","panel":"#FFFFFF","panel_alt":"#EAF0F5","text":"#18212A","muted":"#5B6570","border":"#C7D0D9"}
    p["accent"]=scheme["accent"]
    p["accent_text"]=contrast_text(p["accent"])
    p["dark"]=dark
    return p


def stylesheet(p):
    return f"""
QWidget {{ background-color: {p['bg']}; color: {p['text']}; }}
QMainWindow, QDialog, QWizard {{ background-color: {p['bg']}; }}
QLabel {{ color: {p['text']}; background: transparent; }}
QGroupBox {{
    background-color: {p['panel']}; border: 1px solid {p['border']}; border-radius: 9px;
    margin-top: 13px; padding: 10px 8px 8px 8px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; color: {p['text']}; }}
QPushButton {{
    background-color: {p['panel_alt']}; color: {p['text']}; border: 1px solid {p['border']};
    border-radius: 7px; padding: 6px 10px;
}}
QPushButton:hover {{ border: 1px solid {p['accent']}; }}
QPushButton:pressed {{ background-color: {p['accent']}; color: {p['accent_text']}; }}
QPushButton:disabled {{ color: {p['muted']}; background-color: {p['panel']}; }}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {p['panel']}; color: {p['text']}; border: 1px solid {p['border']};
    border-radius: 6px; padding: 4px;
}}
QComboBox::drop-down {{ border: 0px; width: 24px; }}
QCheckBox {{ spacing: 7px; }}
QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 7px; background: {p['panel']}; }}
QTabBar::tab {{ background: {p['panel_alt']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 7px 11px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {p['accent']}; color: {p['accent_text']}; border-color: {p['accent']}; }}
QProgressBar {{ border: 1px solid {p['border']}; border-radius: 5px; text-align: center; background: {p['panel']}; color: {p['text']}; }}
QProgressBar::chunk {{ background-color: {p['accent']}; border-radius: 4px; }}
QScrollArea {{ border: 0px; background: {p['bg']}; }}
QScrollBar:vertical {{ background: {p['panel']}; width: 14px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {p['border']}; min-height: 28px; border-radius: 6px; }}
QToolTip {{ background-color: {p['panel_alt']}; color: {p['text']}; border: 1px solid {p['accent']}; }}
"""


def apply_theme(app, theme_mode="System", scheme_name="Funk Blau"):
    p=palette_for(app,theme_mode,scheme_name)
    app.setStyleSheet(stylesheet(p))
    return p
