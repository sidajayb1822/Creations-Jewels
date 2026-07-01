import sys
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("EMR Reporter")
    app.setOrganizationName("CreationsJewellery")
    app.setStyle("Fusion")

    app.setStyleSheet("""
        /* ── Global ── */
        * {
            font-family: 'Segoe UI';
            font-size: 13px;
            outline: none;
        }
        QMainWindow { background: #f1f5f9; }
        QWidget      { background: transparent; color: #0f172a; }

        /* ── Sidebar ── */
        QFrame#sidebar     { background: #0f172a; }
        QFrame#sidebarLogo,
        QFrame#navFrame,
        QFrame#sidebarBottom { background: transparent; }

        QLabel#appTitle {
            color: #f8fafc;
            font-size: 16px;
            font-weight: bold;
        }
        QLabel#appSub {
            color: #475569;
            font-size: 11px;
        }
        QLabel#navSection {
            color: #334155;
            font-size: 10px;
            font-weight: bold;
        }

        QPushButton#navBtn {
            background: transparent;
            color: #94a3b8;
            border: none;
            border-radius: 8px;
            text-align: left;
            padding-left: 14px;
            font-size: 13px;
        }
        QPushButton#navBtn:hover {
            background: rgba(255,255,255,0.07);
            color: #e2e8f0;
        }
        QPushButton#navBtn:checked {
            background: #4f46e5;
            color: #ffffff;
            font-weight: bold;
        }

        QFrame#sidebarSep {
            background: #1e293b;
            color: #1e293b;
            max-height: 1px;
        }
        QPushButton#sidebarSettingsBtn {
            background: transparent;
            color: #475569;
            border: 1px solid #1e293b;
            border-radius: 8px;
            text-align: left;
            padding-left: 12px;
            font-size: 12px;
        }
        QPushButton#sidebarSettingsBtn:hover {
            background: rgba(255,255,255,0.07);
            color: #cbd5e1;
            border-color: #334155;
        }

        QLabel#dbLabel {
            color: #ef4444;
            font-size: 11px;
        }
        QLabel#dbLabel[connected="true"] {
            color: #10b981;
        }

        /* ── Content shell ── */
        QFrame#content    { background: #f1f5f9; }
        QStackedWidget#mainStack { background: #f1f5f9; }

        QFrame#headerBar {
            background: #ffffff;
            border-bottom: 1px solid #e2e8f0;
        }
        QLabel#pageTitle {
            color: #0f172a;
            font-size: 20px;
            font-weight: bold;
        }

        /* ── Cards / GroupBox ── */
        QGroupBox {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            margin-top: 20px;
            padding: 16px 12px 12px 12px;
            color: #64748b;
            font-weight: bold;
            font-size: 11px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
            color: #6366f1;
        }

        /* ── Buttons (primary) ── */
        QPushButton {
            background: #6366f1;
            color: #ffffff;
            border: none;
            border-radius: 8px;
            padding: 8px 18px;
            font-size: 13px;
            font-weight: 600;
        }
        QPushButton:hover   { background: #4f46e5; }
        QPushButton:pressed { background: #4338ca; }
        QPushButton:disabled {
            background: #e2e8f0;
            color: #94a3b8;
        }

        /* Secondary / outline buttons */
        QPushButton#outlineBtn {
            background: #ffffff;
            color: #4f46e5;
            border: 1px solid #e2e8f0;
        }
        QPushButton#outlineBtn:hover {
            background: #f5f3ff;
            border-color: #6366f1;
        }
        QPushButton#outlineBtn:disabled {
            background: #f8fafc;
            color: #94a3b8;
            border-color: #e2e8f0;
        }

        /* ── Inputs ── */
        QLineEdit, QSpinBox {
            background: #ffffff;
            border: 1.5px solid #e2e8f0;
            border-radius: 8px;
            padding: 8px 12px;
            color: #0f172a;
            selection-background-color: #6366f1;
            selection-color: #ffffff;
        }
        QLineEdit:focus, QSpinBox:focus {
            border: 1.5px solid #6366f1;
        }

        /* ── ComboBox ── */
        QComboBox {
            background: #ffffff;
            border: 1.5px solid #e2e8f0;
            border-radius: 8px;
            padding: 8px 12px;
            color: #0f172a;
        }
        QComboBox:focus { border: 1.5px solid #6366f1; }
        QComboBox::drop-down { border: none; width: 24px; }
        QComboBox QAbstractItemView {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            selection-background-color: #ede9fe;
            selection-color: #0f172a;
            outline: none;
        }

        /* ── Tables ── */
        QTableWidget {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            gridline-color: #f8fafc;
            font-size: 13px;
            selection-background-color: #ede9fe;
            selection-color: #0f172a;
            alternate-background-color: #f8fafc;
        }
        QTableWidget::item {
            padding: 6px 10px;
            border: none;
        }
        QHeaderView::section {
            background: #f8fafc;
            color: #64748b;
            border: none;
            border-bottom: 2px solid #e2e8f0;
            padding: 10px;
            font-weight: 700;
            font-size: 11px;
        }
        QHeaderView { background: #f8fafc; }

        /* ── Scrollbars ── */
        QScrollBar:vertical {
            background: #f1f5f9;
            width: 6px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #cbd5e1;
            border-radius: 3px;
            min-height: 24px;
        }
        QScrollBar::handle:vertical:hover { background: #6366f1; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal {
            background: #f1f5f9;
            height: 6px;
            margin: 0;
        }
        QScrollBar::handle:horizontal {
            background: #cbd5e1;
            border-radius: 3px;
            min-width: 24px;
        }
        QScrollBar::handle:horizontal:hover { background: #6366f1; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

        /* ── Status bar ── */
        QStatusBar {
            background: #ffffff;
            color: #64748b;
            border-top: 1px solid #e2e8f0;
            font-size: 12px;
        }

        /* ── CheckBox ── */
        QCheckBox { color: #0f172a; spacing: 6px; }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 1.5px solid #d1d5db;
            border-radius: 4px;
            background: #ffffff;
        }
        QCheckBox::indicator:checked {
            background: #6366f1;
            border-color: #6366f1;
        }

        /* ── Dialogs ── */
        QDialog { background: #f8fafc; }
        QDialogButtonBox QPushButton { min-width: 80px; }

        /* ── Sub-tabs inside panels (Customer Rates) ── */
        QTabWidget::pane { background: #f8fafc; border: none; }
        QTabBar           { background: transparent; }
        QTabBar::tab {
            background: transparent;
            color: #64748b;
            border: none;
            border-bottom: 2px solid transparent;
            padding: 10px 20px;
            margin-right: 4px;
            font-weight: 600;
        }
        QTabBar::tab:selected {
            color: #6366f1;
            border-bottom: 2px solid #6366f1;
        }
        QTabBar::tab:hover:!selected {
            color: #374151;
            border-bottom: 2px solid #d1d5db;
        }
    """)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
