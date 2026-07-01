from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QTabWidget,
)
from PySide6.QtCore import Qt, QThread, Signal

from app.core.db import db


class _LoadWorker(QThread):
    done = Signal(list, list)
    error = Signal(str)

    def __init__(self, company_code: str):
        super().__init__()
        self._cc = company_code

    def run(self):
        try:
            mats = db.get_all_material_rates(self._cc)
            labs = db.get_all_labour_rates(self._cc)
            self.done.emit(mats, labs)
        except Exception as e:
            self.error.emit(str(e))


class CustomerRatesWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Customer:"))
        self._customer_combo = QComboBox()
        self._customer_combo.setMinimumWidth(320)
        self._customer_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        hdr.addWidget(self._customer_combo)

        self._load_btn = QPushButton("Load Rate Card")
        self._load_btn.clicked.connect(self._load)
        hdr.addWidget(self._load_btn)

        self._status = QLabel("")
        hdr.addWidget(self._status, 1)
        layout.addLayout(hdr)

        self._tabs = QTabWidget()

        self._mat_table = self._make_table(
            ["Code", "Description", "Category", "Type", "From", "To", "Rate"]
        )
        self._tabs.addTab(self._mat_table, "Materials")

        self._lab_table = self._make_table(
            ["Main Code", "Sub Code", "Rate", "Q / W", "From Wt", "To Wt"]
        )
        self._tabs.addTab(self._lab_table, "Labour")

        layout.addWidget(self._tabs, 1)

    def _make_table(self, headers: list[str]) -> QTableWidget:
        t = QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.horizontalHeader().setStretchLastSection(True)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return t

    def showEvent(self, event):
        super().showEvent(event)
        if self._customer_combo.count() == 0:
            self._refresh_customers()

    def _refresh_customers(self):
        if not db.is_connected():
            self._status.setText("Not connected to database.")
            return
        customers = db.get_customers()
        self._customer_combo.clear()
        for code, name in customers:
            self._customer_combo.addItem(f"{code}  —  {name}", userData=code)

    def _load(self):
        if not db.is_connected():
            self._status.setText("Not connected.")
            return
        idx = self._customer_combo.currentIndex()
        if idx < 0:
            return
        company_code = self._customer_combo.itemData(idx)
        if not company_code:
            return
        self._status.setText("Loading…")
        self._load_btn.setEnabled(False)
        self._worker = _LoadWorker(company_code)
        self._worker.done.connect(self._on_loaded)
        self._worker.error.connect(lambda msg: self._status.setText(f"Error: {msg}"))
        self._worker.finished.connect(lambda: self._load_btn.setEnabled(True))
        self._worker.start()

    def _on_loaded(self, mats: list, labs: list):
        self._populate_materials(mats)
        self._populate_labour(labs)
        m_count = len(mats)
        l_count = len(labs)
        self._status.setText(f"{m_count} material rate(s)   ·   {l_count} labour rate(s)")

    def _populate_materials(self, rows: list):
        t = self._mat_table
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            t.setItem(i, 0, QTableWidgetItem(str(r.get("RrCd", ""))))
            t.setItem(i, 1, QTableWidgetItem(str(r.get("RmDesc", ""))))
            t.setItem(i, 2, QTableWidgetItem(str(r.get("RmCtg", ""))))
            t.setItem(i, 3, QTableWidgetItem(str(r.get("RrTcTyp", ""))))
            t.setItem(i, 4, _num_item(r.get("RrFrLn")))
            t.setItem(i, 5, _num_item(r.get("RrToLn")))
            t.setItem(i, 6, _num_item(r.get("RrSalRt"), decimals=4))
        t.resizeColumnsToContents()

    def _populate_labour(self, rows: list):
        t = self._lab_table
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            t.setItem(i, 0, QTableWidgetItem(str(r.get("LrMCd", ""))))
            t.setItem(i, 1, QTableWidgetItem(str(r.get("LrSCd", ""))))
            t.setItem(i, 2, _num_item(r.get("LrSalRt")))
            t.setItem(i, 3, QTableWidgetItem(str(r.get("LrQw", "Q"))))
            t.setItem(i, 4, _num_item(r.get("LrFrWt")))
            t.setItem(i, 5, _num_item(r.get("LrToWt")))
        t.resizeColumnsToContents()


def _num_item(val, decimals: int = 2) -> QTableWidgetItem:
    try:
        item = QTableWidgetItem(f"{float(val):.{decimals}f}")
    except (TypeError, ValueError):
        item = QTableWidgetItem("")
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item
