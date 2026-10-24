"""Application stylesheet (light, clean Windows 11 look matching the design mockups)."""
import sys
from pathlib import Path

_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
ICONS = (_BASE / "assets" / "icons").as_posix()

ACCENT = "#1a73e8"
ACCENT_DARK = "#155fc0"
GREEN = "#1f9d55"
GREEN_DARK = "#18864a"
SLATE = "#3b424d"        # dark segmented / selected controls
INK = "#1e293b"

QSS = f"""
* {{ font-family: "Segoe UI", "Segoe UI Variable", Arial, sans-serif; font-size: 10pt; color: {INK}; }}
QMainWindow, #Root {{ background: #f3f5f9; }}
QScrollArea, #LeftInner {{ background: transparent; border: none; }}
#PageScroll > QWidget {{ background: transparent; }}
#SheetScroll, #SheetScroll > QWidget, #SheetInner {{ background: transparent; }}

/* ---------- top navigation ---------- */
#NavBar {{ background: #ffffff; border-bottom: 1px solid #e3e8ef; }}
#NavBtn {{ background: transparent; border: none; border-bottom: 3px solid transparent; border-radius: 0px;
           padding: 13px 16px 11px 16px; font-size: 11pt; color: #334155; }}
#NavBtn:hover {{ background: #f4f7fb; }}
#NavBtn:pressed {{ background: #e9eef5; }}
#NavBtn[active="true"] {{ border-bottom: 3px solid {ACCENT}; color: #0f172a; font-weight: 600; }}
#NavSep {{ background: #e3e8ef; }}
#ZoomBox {{ border: 1px solid #d9e0ea; border-radius: 8px; padding: 7px 6px; font-size: 11pt; background: #ffffff; }}
QTabWidget::pane {{ border: 1px solid #e3e8ef; border-radius: 8px; top: -1px; background: #ffffff; }}
QTabBar::tab {{ padding: 8px 16px; border: 1px solid transparent; border-bottom: 2px solid transparent; color: #475569; }}
QTabBar::tab:selected {{ color: #0f172a; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
QHeaderView::section {{ background: #f6f8fb; border: none; border-bottom: 1px solid #e3e8ef; padding: 6px 8px;
                        font-weight: 600; color: #334155; }}
QTableWidget, QTableView, QListView, QTreeView {{ background: #ffffff; border: 1px solid #e3e8ef; border-radius: 8px;
    gridline-color: #eef2f7; selection-background-color: #e8f0fe; selection-color: #0f172a; }}

/* ---------- cards ---------- */
#Card {{ background: #ffffff; border: 1px solid #e3e8ef; border-radius: 12px; }}
#CardTitle {{ font-size: 13pt; font-weight: 600; color: #0f172a; }}
#Section {{ font-weight: 600; color: #334155; margin-top: 2px; }}
#FieldLabel {{ color: #334155; }}
#Hint {{ color: #64748b; font-size: 9pt; }}
#Warn {{ color: #b45309; font-size: 9pt; }}
#Good {{ color: #15803d; font-size: 9pt; }}
#FileName {{ font-size: 11pt; font-weight: 600; }}
#FileMeta {{ color: #475569; }}
#PaneTitle {{ font-size: 10.5pt; font-weight: 600; }}
#PaneInfo {{ color: #475569; }}
#Muted {{ color: #64748b; }}
#Badge {{ background: #eef4fe; color: {ACCENT_DARK}; border: 1px solid #cfe0fb; border-radius: 9px;
          padding: 2px 8px; font-size: 9pt; font-weight: 600; }}

#DropZone {{ border: 2px dashed #c9d2de; border-radius: 10px; background: #fbfcfe; }}
#DropZone[active="true"] {{ border-color: {ACCENT}; background: #eaf2fe; }}
#DropTitle {{ font-size: 11pt; font-weight: 600; color: #1e293b; }}
#FileCard {{ background: #f8fafc; border: 1px solid #e6ebf2; border-radius: 10px; }}

/* ---------- buttons ---------- */
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
#Choose {{ background: #f1f4f8; border: 1px solid #d9e0ea; font-size: 11pt; padding: 9px 18px; }}
#Choose:hover {{ background: #e6ebf2; }}
#Flat {{ background: transparent; border: none; padding: 4px 6px; color: #334155; }}
#Flat:hover {{ background: #eef2f7; }}
#LinkBtn {{ background: transparent; border: none; padding: 2px 4px; color: {ACCENT_DARK}; font-weight: 600; }}
#LinkBtn:hover {{ text-decoration: underline; }}
#IconBtn {{ background: transparent; border: none; padding: 4px; border-radius: 6px; }}
#IconBtn:hover {{ background: #eef2f7; }}
#Dark {{ background: #23272e; border: 1px solid #23272e; color: white; font-weight: 600; font-size: 11pt;
         padding: 10px 22px; }}
#Dark:hover {{ background: #343a44; }}
#Light {{ background: #f1f4f8; border: 1px solid #dfe5ed; color: #1e293b; font-weight: 600; font-size: 11pt;
          padding: 10px 22px; }}
#Light:hover {{ background: #e6ebf2; }}
#Go {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 700; font-size: 11.5pt;
       padding: 10px 24px; }}
#Go:hover {{ background: {ACCENT_DARK}; }}
#Go:disabled {{ background: #9dbff0; border-color: #9dbff0; color: #eef4fe; }}

#SegBtn {{ background: #f8fafc; border: 1px solid #d9e0ea; border-radius: 0px; padding: 10px 8px; font-size: 11pt; }}
#SegBtn:hover {{ background: #eef2f7; }}
#SegBtn:checked {{ background: {SLATE}; color: white; border-color: {SLATE}; }}
#LinkToggle {{ background: #f8fafc; border: 1px solid #d9e0ea; border-radius: 8px; }}
#LinkToggle:checked {{ background: {SLATE}; border-color: {SLATE}; }}

#PresetTile {{ background: #f8fafc; border: 1px solid #dfe5ed; border-radius: 8px; padding: 6px; }}
#PresetTile:hover {{ background: #eef2f7; }}
#PresetTile:checked {{ background: #ffffff; border: 2px solid {SLATE}; color: #1e293b; }}
#PresetName {{ font-weight: 600; color: #1e293b; background: transparent; }}
#PresetDims {{ color: #64748b; font-size: 8.5pt; background: transparent; }}

#Chip {{ background: #f1f4f8; border: 1px solid #dfe5ed; border-radius: 14px; padding: 5px 12px; }}
#Chip:hover {{ background: #e6ebf2; }}
#Chip:checked {{ background: {SLATE}; color: white; border-color: {SLATE}; }}
#ModeCard {{ background: #f8fafc; border: 1px solid #dfe5ed; border-radius: 10px; padding: 8px; text-align: left; }}
#ModeCard:hover {{ background: #eef2f7; }}
#ModeCard:checked {{ background: #ffffff; border: 2px solid {ACCENT}; color: {INK}; }}

#AIButton {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6d4aff, stop:1 #1a73e8);
             border: none; color: white; font-weight: 700; font-size: 11pt; padding: 10px 14px; }}
#AIButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5b37f0, stop:1 #155fc0); }}
#AIButton:disabled {{ background: #c7d2fe; color: #eef2ff; }}

/* ---------- download & share tiles ---------- */
#TileBlue, #TilePurple, #TileGreen, #TileWA {{ border-radius: 10px; font-size: 11.5pt; font-weight: 600;
    padding: 14px 8px 12px 8px; color: #1e293b; }}
#TileBlue {{ background: #eef4fe; border: 1px solid #cfe0fb; }}
#TileBlue:hover {{ background: #e2ecfd; }}
#TilePurple {{ background: #f3f0fe; border: 1px solid #ddd4fb; }}
#TilePurple:hover {{ background: #e9e3fd; }}
#TileGreen {{ background: #eef8f1; border: 1px solid #cdebd7; }}
#TileGreen:hover {{ background: #e2f3e8; }}
#TileWA {{ background: #ebf9f0; border: 1px solid #c4ecd3; }}
#TileWA:hover {{ background: #dcf4e5; }}
#TileMenu {{ background: transparent; border: none; padding: 2px; border-radius: 6px; }}
#TileMenu:hover {{ background: rgba(0,0,0,0.06); }}

/* ---------- dialogs ---------- */
#Sheet {{ background: #ffffff; border: 1px solid #dfe5ed; border-radius: 16px; }}
#SheetTitle {{ font-size: 15pt; font-weight: 700; color: #0f172a; }}
#SheetSub {{ color: #475569; font-size: 10.5pt; }}
#InfoBox {{ background: #f8fafc; border: 1px solid #e6ebf2; border-radius: 10px; }}
#InfoLabel {{ color: #475569; font-size: 9.5pt; }}
#InfoValue {{ font-size: 13pt; font-weight: 700; color: #0f172a; }}
#InfoAlt {{ color: #64748b; font-size: 9pt; }}
#WarnBox {{ background: #fff8e1; border: 1px solid #fde68a; border-radius: 10px; }}
#WarnText {{ font-weight: 700; color: #1e293b; font-size: 10.5pt; }}
#NoteBox {{ background: #fff8e6; border: 1px solid #fbe7b5; border-radius: 10px; }}
#NoteTitle {{ font-weight: 700; color: #1e293b; font-size: 10.5pt; }}
#Strip {{ background: #f8fafc; border: 1px solid #e6ebf2; border-radius: 10px; }}
#StripSep {{ background: #e2e8f0; }}
#Panel {{ background: #f6f8fb; border-radius: 10px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: #ffffff; border: 1px solid #cfd8e3; border-radius: 7px; padding: 5px 8px; min-height: 22px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QSpinBox, QDoubleSpinBox {{ padding-left: 8px; padding-right: 22px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border: none; border-left: 1px solid #e3e8ef; border-top-right-radius: 7px; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border: none; border-left: 1px solid #e3e8ef; border-bottom-right-radius: 7px; background: transparent; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: #eef2f7; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({ICONS}/up.svg); width: 11px; height: 11px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({ICONS}/down.svg); width: 11px; height: 11px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({ICONS}/down.svg); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid #cfd8e3; selection-background-color: #e8f0fe; selection-color: #0f172a; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 17px; height: 17px; }}

QSlider::groove:horizontal {{ height: 6px; background: #dfe6ef; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: #475569; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #475569; border: 3px solid white; width: 14px; height: 14px;
                              margin: -7px 0; border-radius: 10px; }}
#BlueSlider::sub-page:horizontal {{ background: {ACCENT}; }}
#BlueSlider::handle:horizontal {{ background: {ACCENT}; border: 3px solid white; width: 14px; height: 14px;
                                  margin: -7px 0; border-radius: 10px; }}

QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: #ffffff; border-top: 1px solid #e3e8ef; }}
QStatusBar QLabel {{ color: #475569; }}
QProgressBar {{ border: none; background: #e3e8ef; border-radius: 3px; height: 6px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QMenu {{ background: white; border: 1px solid #d9e0ea; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: #e8f0fe; }}
QMenu::separator {{ height: 1px; background: #e3e8ef; margin: 4px 8px; }}
QListWidget {{ background: white; border: 1px solid #cfd8e3; border-radius: 8px; }}
QToolTip {{ background: #0f172a; color: white; border: none; padding: 5px 8px; }}
"""
