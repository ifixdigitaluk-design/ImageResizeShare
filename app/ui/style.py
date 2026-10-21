"""Application stylesheet (light, clean Windows 11 look)."""

ACCENT = "#1a73e8"
ACCENT_DARK = "#155fc0"
GREEN = "#1f9d55"
GREEN_DARK = "#18864a"

QSS = f"""
* {{ font-family: "Segoe UI", "Segoe UI Variable", Arial, sans-serif; font-size: 10pt; color: #1e293b; }}
QMainWindow, #Root {{ background: #f1f4f9; }}
QScrollArea, #LeftInner {{ background: transparent; border: none; }}

#Card {{ background: #ffffff; border: 1px solid #e3e8ef; border-radius: 12px; }}
#CardTitle {{ font-size: 11.5pt; font-weight: 600; color: #0f172a; }}
#Section {{ font-weight: 600; color: #334155; margin-top: 4px; }}
#Hint {{ color: #64748b; font-size: 9pt; }}
#Warn {{ color: #b45309; font-size: 9pt; }}
#Good {{ color: #15803d; font-size: 9pt; }}
#FileName {{ font-size: 11pt; font-weight: 600; }}
#PaneTitle {{ font-size: 10.5pt; font-weight: 600; }}
#PaneInfo {{ color: #475569; }}
#DropZone {{ border: 2px dashed #c7d2e0; border-radius: 10px; background: #f8fafc; }}
#DropZone[active="true"] {{ border-color: {ACCENT}; background: #eaf2fe; }}

QPushButton, QToolButton {{
    background: #eef2f7; border: 1px solid #d9e0ea; border-radius: 8px;
    padding: 7px 12px; min-height: 20px;
}}
QPushButton:hover, QToolButton:hover {{ background: #e3e9f2; }}
QPushButton:pressed, QToolButton:pressed {{ background: #d5deea; }}
QPushButton:disabled, QToolButton:disabled {{ color: #94a3b8; background: #f3f5f8; }}
QPushButton:checked, QToolButton:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}

#Primary {{ background: #e8f0fe; border: 1px solid #a9c5f5; color: {ACCENT_DARK}; font-weight: 600; }}
#Primary:hover {{ background: #dbe7fd; }}

#ModeBtn {{ background: #ffffff; border: 1px solid #e3e8ef; border-radius: 0px;
            padding: 12px 10px; font-size: 11pt; }}
#ModeBtn:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
#ModeLeft {{ border-top-left-radius: 10px; border-bottom-left-radius: 10px; }}
#ModeRight {{ border-top-right-radius: 10px; border-bottom-right-radius: 10px; }}

#Preset {{ background: #f1f4f8; padding: 8px 6px; }}
#Preset:checked {{ background: {ACCENT}; color: white; }}

#WhatsApp {{ background: {GREEN}; border: 1px solid {GREEN_DARK}; color: white;
             font-weight: 600; font-size: 11pt; text-align: left; padding: 10px 16px; }}
#WhatsApp:hover {{ background: {GREEN_DARK}; }}
#WhatsApp:disabled {{ background: #9fd3b4; color: #eefaf2; }}
#WhatsAppMenu {{ background: {GREEN}; border: 1px solid {GREEN_DARK}; }}
#WhatsAppMenu:hover {{ background: {GREEN_DARK}; }}
#BigBtn {{ font-size: 11pt; padding: 10px 16px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: #ffffff; border: 1px solid #cfd8e3; border-radius: 7px; padding: 5px 8px; min-height: 22px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid #cfd8e3; selection-background-color: #e8f0fe; selection-color: #0f172a; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 17px; height: 17px; }}

QSlider::groove:horizontal {{ height: 6px; background: #dfe6ef; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; border: 3px solid white; width: 14px; height: 14px;
                              margin: -6px 0; border-radius: 10px; }}

QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: #ffffff; border-top: 1px solid #e3e8ef; }}
QStatusBar QLabel {{ color: #475569; }}
QProgressBar {{ border: none; background: #e3e8ef; border-radius: 3px; height: 6px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QMenu {{ background: white; border: 1px solid #d9e0ea; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: #e8f0fe; }}
QListWidget {{ background: white; border: 1px solid #cfd8e3; border-radius: 8px; }}
QToolTip {{ background: #0f172a; color: white; border: none; padding: 5px 8px; }}
"""
