from __future__ import annotations

YOUTUBE_RED = "#ff0033"
BG = "#0f0f0f"
PANEL = "#181818"
PANEL_2 = "#212121"
BORDER = "#303030"
TEXT = "#f1f1f1"
MUTED = "#aaaaaa"
SUCCESS = "#2ba640"
WARNING = "#f5b400"

APP_STYLESHEET = """
QMainWindow, QWidget {
    background: #0f0f0f;
    color: #f1f1f1;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QFrame#TopBar {
    background: #181818;
    border-bottom: 1px solid #303030;
}
QLabel#AppBadge {
    background: #ff0033;
    color: white;
    border-radius: 7px;
    padding: 7px 10px;
    font-size: 12pt;
    font-weight: 800;
}
QLabel#AppTitle {
    font-size: 16pt;
    font-weight: 700;
    color: #ffffff;
}
QLabel#AppSubtitle, QLabel[muted="true"] {
    color: #aaaaaa;
}
QLabel#ChannelState {
    background: #212121;
    border: 1px solid #303030;
    border-radius: 9px;
    padding: 5px 10px;
    color: #d7d7d7;
}
QFrame#MetricCard {
    background: #151515;
    border: 0;
    border-radius: 10px;
}
QLabel#MetricValue {
    color: #ffffff;
    font-size: 18pt;
    font-weight: 700;
}
QLabel#MetricTitle {
    color: #aaaaaa;
    font-size: 9pt;
}
QPushButton {
    background: #272727;
    border: 1px solid #3a3a3a;
    border-radius: 7px;
    padding: 7px 12px;
    color: #f1f1f1;
    min-height: 20px;
}
QPushButton:hover {
    background: #333333;
    border-color: #555555;
}
QPushButton:pressed {
    background: #3b3b3b;
}
QPushButton[role="primary"] {
    background: #ff0033;
    border-color: #ff0033;
    color: white;
    font-weight: 600;
}
QPushButton[role="primary"]:hover {
    background: #e6002e;
}
QPushButton[role="success"] {
    background: #1f6f35;
    border-color: #2ba640;
    color: white;
}
QPushButton[role="chip"] {
    background: #1b1b1b;
    border: 1px solid #383838;
    border-radius: 12px;
    padding: 4px 10px;
    min-height: 18px;
    color: #d7d7d7;
}
QPushButton[role="chip"]:hover {
    background: #272727;
    border-color: #555555;
    color: #ffffff;
}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #212121;
    color: #f1f1f1;
    border: 1px solid #3a3a3a;
    border-radius: 7px;
    padding: 6px 8px;
    selection-background-color: #ff0033;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #ff0033;
}
QComboBox::drop-down {
    border: 0;
    width: 24px;
}
QTabWidget::pane {
    border: 0;
    top: -1px;
}
QTabBar::tab {
    background: #0f0f0f;
    color: #b7b7b7;
    padding: 11px 18px;
    border: 0;
    border-bottom: 3px solid transparent;
}
QTabBar::tab:hover {
    color: white;
    background: #181818;
}
QTabBar::tab:selected {
    color: white;
    font-weight: 600;
    border-bottom: 3px solid #ff0033;
}
QTableWidget, QTableView {
    background: #111111;
    alternate-background-color: #171717;
    border: 1px solid #2b2b2b;
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: #4a1822;
    selection-color: white;
}
QTableWidget::item, QTableView::item {
    padding: 7px 5px;
    border-bottom: 1px solid #222222;
}
QHeaderView::section {
    background: #212121;
    color: #d8d8d8;
    border: 0;
    border-right: 1px solid #303030;
    border-bottom: 1px solid #303030;
    padding: 8px 6px;
    font-weight: 600;
}
QScrollBar:vertical {
    background: #111111;
    width: 12px;
}
QScrollBar::handle:vertical {
    background: #444444;
    border-radius: 6px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 4px;
    border: 1px solid #555555;
    background: #212121;
}
QCheckBox::indicator:checked {
    background: #ff0033;
    border-color: #ff0033;
}

QFrame#SettingsChannelBar {
    background: #181818;
    border: 1px solid #2b2b2b;
    border-radius: 10px;
}
QTabWidget#SettingsSections::pane {
    background: #121212;
    border: 1px solid #2b2b2b;
    border-radius: 10px;
    top: -1px;
}
QTabWidget#SettingsSections QTabBar::tab {
    background: #141414;
    padding: 10px 18px;
    border-bottom: 2px solid transparent;
}
QTabWidget#SettingsSections QTabBar::tab:selected {
    background: #181818;
    border-bottom: 2px solid #ff0033;
}
QScrollArea#SettingsScroll {
    background: transparent;
    border: 0;
}
QScrollArea#SettingsScroll > QWidget > QWidget {
    background: transparent;
}
QFrame#SettingsCard {
    background: #181818;
    border: 1px solid #2b2b2b;
    border-radius: 10px;
}
QLabel#SettingsSectionTitle {
    color: #ffffff;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#SettingsHint {
    color: #a5a5a5;
    font-size: 9pt;
}
QLabel#QuotaSummary {
    background: #111111;
    border: 1px solid #303030;
    border-radius: 7px;
    padding: 9px 11px;
}
QLabel#SettingsVersion {
    font-size: 11pt;
    font-weight: 600;
}

QStatusBar {
    background: #181818;
    color: #a8a8a8;
    border-top: 1px solid #303030;
}
QDialog {
    background: #181818;
}
QMessageBox {
    background: #181818;
}

/* 0.4 dashboard / process visualization */
QFrame#ProcessStrip, QFrame#HealthStrip, QFrame#ContextCard,
QFrame#QueueCard, QFrame#ArchiveCard, QFrame#ActivityCard {
    background: #161616;
    border: 1px solid #242424;
    border-radius: 10px;
}
QFrame#NextActionCard {
    background: #171717;
    border: 1px solid #ff0033;
    border-radius: 12px;
}
QFrame#NextActionCard QPushButton[role="primary"] {
    font-size: 11pt;
    font-weight: 700;
    min-height: 28px;
}
QLabel#SectionTitle {
    color: #ffffff;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#SectionKicker {
    color: #8f8f8f;
    font-size: 8.5pt;
    font-weight: 600;
}
QLabel#StatusGood {
    background: #16371f;
    color: #7ee59a;
    border: 1px solid #275f37;
    border-radius: 9px;
    padding: 4px 9px;
    font-weight: 600;
}
QLabel#StatusWork {
    background: #142b3c;
    color: #7bc7ff;
    border: 1px solid #245270;
    border-radius: 9px;
    padding: 4px 9px;
    font-weight: 600;
}
QLabel#StatusWarn {
    background: #3b3012;
    color: #ffd76a;
    border: 1px solid #66531e;
    border-radius: 9px;
    padding: 4px 9px;
    font-weight: 600;
}
QLabel#StatusBad {
    background: #431821;
    color: #ff8ca1;
    border: 1px solid #732637;
    border-radius: 9px;
    padding: 4px 9px;
    font-weight: 600;
}
QProgressBar {
    background: #242424;
    border: 1px solid #343434;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: #4285f4;
    border-radius: 5px;
}
QProgressBar[role="success"]::chunk {
    background: #2ba640;
}
QProgressBar[role="warning"]::chunk {
    background: #f5b400;
}
QProgressBar[role="danger"]::chunk {
    background: #ff0033;
}
QListWidget#ActivityList {
    background: transparent;
    border: 0;
    outline: 0;
}
QListWidget#ActivityList::item {
    padding: 7px 4px;
    border-bottom: 1px solid #252525;
}
QToolButton {
    background: #272727;
    border: 1px solid #3a3a3a;
    border-radius: 7px;
    padding: 7px 12px;
    color: #f1f1f1;
    min-height: 20px;
}
QToolButton:hover {
    background: #333333;
}
QMenu {
    background: #1d1d1d;
    color: #f1f1f1;
    border: 1px solid #3a3a3a;
    padding: 6px;
}
QMenu::item {
    padding: 7px 22px 7px 12px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: #343434;
}
QLabel#StickyVideoTitle {
    color: white;
    font-size: 11pt;
    font-weight: 700;
}
QLabel#DeltaGood {
    color: #7ee59a;
    font-weight: 700;
}
QLabel#DeltaWarn {
    color: #ffd76a;
    font-weight: 700;
}

/* 0.6 guided workspace polish */
QFrame#ContextCard {
    background: #131313;
    border-top: 1px solid #242424;
    border-left: 0;
    border-right: 0;
    border-bottom: 0;
    border-radius: 0;
}
QLabel#MetricTitle {
    letter-spacing: 0.2px;
}
QPushButton[role="success"] {
    font-weight: 600;
}
QPushButton:disabled {
    background: #1b1b1b;
    border-color: #282828;
    color: #666666;
}

"""
