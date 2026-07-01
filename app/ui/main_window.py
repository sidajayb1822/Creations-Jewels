from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFrame,
    QLabel, QPushButton, QStatusBar, QStackedWidget,
)
from app.ui.bom_compare.widget import BOMCompareWidget
from app.ui.customer_rates.widget import CustomerRatesWidget
from app.ui.order_pipeline.widget import OrderPipelineWidget
from app.ui.settings_dialog import SettingsDialog
from app.core.db import db, load_config


_NAV_ITEMS = [
    ("📋", "BOM Comparison", 0),
    ("💰", "Customer Rates", 1),
    ("📦", "Order Pipeline", 2),
]
_PAGE_TITLES = ["BOM Comparison", "Customer Rate Card", "Order Pipeline"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EMR Reporter")
        self.resize(1380, 860)
        self._build_ui()
        self._try_autoconnect()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("rootWidget")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ─── Sidebar ─────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)

        # Logo block
        logo = QFrame()
        logo.setObjectName("sidebarLogo")
        lv = QVBoxLayout(logo)
        lv.setContentsMargins(20, 28, 20, 22)
        lv.setSpacing(3)
        lv.addWidget(_lbl("EMR Reporter", "appTitle"))
        lv.addWidget(_lbl("Emperor ERP Analytics", "appSub"))
        sv.addWidget(logo)

        # Section heading
        section_lbl = _lbl("NAVIGATION", "navSection")
        section_lbl.setContentsMargins(20, 8, 20, 4)
        sv.addWidget(section_lbl)

        # Nav buttons
        nav_frame = QFrame()
        nav_frame.setObjectName("navFrame")
        nv = QVBoxLayout(nav_frame)
        nv.setContentsMargins(10, 4, 10, 4)
        nv.setSpacing(2)
        self._nav_btns: list[QPushButton] = []
        for icon, label, idx in _NAV_ITEMS:
            btn = QPushButton(f"  {icon}   {label}")
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setFixedHeight(44)
            btn.clicked.connect(lambda _, i=idx: self._go(i))
            nv.addWidget(btn)
            self._nav_btns.append(btn)
        nv.addStretch()
        sv.addWidget(nav_frame, 1)

        # Bottom: settings + db indicator
        bottom = QFrame()
        bottom.setObjectName("sidebarBottom")
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(14, 10, 14, 20)
        bv.setSpacing(8)
        sep = QFrame()
        sep.setObjectName("sidebarSep")
        sep.setFrameShape(QFrame.Shape.HLine)
        bv.addWidget(sep)
        settings_btn = QPushButton("⚙   Database Settings")
        settings_btn.setObjectName("sidebarSettingsBtn")
        settings_btn.setFixedHeight(40)
        settings_btn.clicked.connect(self._open_settings)
        bv.addWidget(settings_btn)
        self._db_label = _lbl("● Not connected", "dbLabel")
        self._db_label.setProperty("connected", "false")
        bv.addWidget(self._db_label)
        sv.addWidget(bottom)

        h.addWidget(sidebar)

        # ─── Content area ────────────────────────────────────────
        content = QFrame()
        content.setObjectName("content")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        # Page header bar
        header = QFrame()
        header.setObjectName("headerBar")
        header.setFixedHeight(60)
        hh = QHBoxLayout(header)
        hh.setContentsMargins(28, 0, 28, 0)
        self._page_title = _lbl("BOM Comparison", "pageTitle")
        hh.addWidget(self._page_title)
        hh.addStretch()
        cv.addWidget(header)

        # Stacked pages
        self._stack = QStackedWidget()
        self._stack.setObjectName("mainStack")
        self.bom_tab = BOMCompareWidget()
        self._stack.addWidget(self.bom_tab)
        self.rates_tab = CustomerRatesWidget()
        self._stack.addWidget(self.rates_tab)
        self.pipeline_tab = OrderPipelineWidget()
        self._stack.addWidget(self.pipeline_tab)
        cv.addWidget(self._stack, 1)

        h.addWidget(content, 1)

        self._go(0)

        self.status = QStatusBar()
        self.status.setObjectName("mainStatus")
        self.setStatusBar(self.status)
        self.status.showMessage("Ready — drop an Emperor BOM Excel file to begin.")

    def _go(self, idx: int):
        self._stack.setCurrentIndex(idx)
        self._page_title.setText(_PAGE_TITLES[idx])
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)

    def _try_autoconnect(self):
        cfg = load_config()
        if cfg.get("server"):
            ok, _ = db.test_connection(cfg)
            if ok:
                try:
                    db.connect(cfg)
                    self._set_db_connected(True)
                    return
                except Exception:
                    pass
        self._set_db_connected(False)

    def _set_db_connected(self, connected: bool):
        if connected:
            cfg = load_config()
            self._db_label.setText(f"● {cfg.get('database', 'Connected')}")
            self._db_label.setProperty("connected", "true")
        else:
            self._db_label.setText("● Not connected")
            self._db_label.setProperty("connected", "false")
        self._db_label.style().unpolish(self._db_label)
        self._db_label.style().polish(self._db_label)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            db.disconnect()
            cfg = load_config()
            try:
                db.connect(cfg)
                self._set_db_connected(True)
                self.status.showMessage("Connected to Emperor database.")
            except Exception as e:
                self._set_db_connected(False)
                self.status.showMessage(f"Connection failed: {e}")


def _lbl(text: str, obj_name: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(obj_name)
    return lbl
