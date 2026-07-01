from datetime import date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QLineEdit, QCheckBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor

from app.core.db import db

_SENTINEL = date(1980, 1, 1)


class _PipelineWorker(QThread):
    done = Signal(list)
    error = Signal(str)

    def __init__(self, customer_filter: str, tc_types: list | None, show_delivered: bool):
        super().__init__()
        self._cf = customer_filter
        self._types = tc_types
        self._show_del = show_delivered

    def run(self):
        try:
            rows = db.get_order_pipeline(
                customer_filter=self._cf,
                tc_types=self._types,
                show_delivered=self._show_del,
            )
            self.done.emit(rows)
        except Exception as e:
            self.error.emit(str(e))


class OrderPipelineWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Filter bar ──────────────────────────────────────────
        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("Customer:"))
        self._customer_edit = QLineEdit()
        self._customer_edit.setPlaceholderText("Search name or code…")
        self._customer_edit.setMaximumWidth(220)
        self._customer_edit.returnPressed.connect(self._refresh)
        filter_row.addWidget(self._customer_edit)

        filter_row.addSpacing(8)
        filter_row.addWidget(QLabel("Type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(["All", "QT — Quotations", "SO — Sales Orders"])
        filter_row.addWidget(self._type_combo)

        filter_row.addSpacing(8)
        self._delivered_chk = QCheckBox("Include delivered")
        filter_row.addWidget(self._delivered_chk)

        filter_row.addSpacing(8)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._refresh)
        filter_row.addWidget(self._refresh_btn)

        self._status = QLabel("")
        filter_row.addWidget(self._status, 1)
        layout.addLayout(filter_row)

        # ── Table ───────────────────────────────────────────────
        headers = [
            "Order No", "Customer", "PO No",
            "Order Date", "Exp. Delivery", "Del. Date",
            "Value (USD)", "Status",
        ]
        self._table = QTableWidget()
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if self._table.rowCount() == 0 and db.is_connected():
            self._refresh()

    def _refresh(self):
        if not db.is_connected():
            self._status.setText("Not connected to database.")
            return

        customer_filter = self._customer_edit.text().strip()
        idx = self._type_combo.currentIndex()
        tc_types = None
        if idx == 1:
            tc_types = ["QT"]
        elif idx == 2:
            tc_types = ["SO"]
        show_delivered = self._delivered_chk.isChecked()

        self._status.setText("Loading…")
        self._refresh_btn.setEnabled(False)
        self._worker = _PipelineWorker(customer_filter, tc_types, show_delivered)
        self._worker.done.connect(self._on_loaded)
        self._worker.error.connect(lambda msg: self._status.setText(f"Error: {msg}"))
        self._worker.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        self._worker.start()

    def _on_loaded(self, rows: list):
        today = date.today()
        self._table.setRowCount(len(rows))

        for i, r in enumerate(rows):
            tc = r.get("OmTc", "")
            order_no = f"{tc}\\{r.get('OmYy','')}\\{r.get('OmChr','')}\\{r.get('OmNo','')}"
            cust = r.get("CmName") or r.get("OmCmCd", "")
            po = r.get("OmPoNo", "") or "—"
            order_dt = _fmt_date(r.get("OmDt"))
            exp_del = _fmt_date(r.get("OmExpDelDt"))
            del_dt = _fmt_date(r.get("OmDelDt"))
            val = r.get("SaleVal", 0) or 0

            del_date = _to_date(r.get("OmDelDt"))
            exp_del_date = _to_date(r.get("OmExpDelDt"))

            if del_date and del_date != _SENTINEL:
                status = "Delivered"
                status_color = QColor("#48bb78")
            elif exp_del_date and exp_del_date != _SENTINEL and exp_del_date < today:
                status = "Overdue"
                status_color = QColor("#fc8181")
            else:
                status = "Open"
                status_color = QColor("#63b3ed")

            cells = [order_no, cust, po, order_dt, exp_del, del_dt,
                     f"${val:,.0f}", status]
            for j, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                if j in (0, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif j == 6:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if j == 7:
                    item.setForeground(status_color)
                self._table.setItem(i, j, item)

        self._table.resizeColumnsToContents()
        self._status.setText(f"{len(rows)} order(s)")


def _to_date(dt) -> date | None:
    if dt is None:
        return None
    return dt.date() if hasattr(dt, "date") else dt


def _fmt_date(dt) -> str:
    d = _to_date(dt)
    if d is None:
        return "—"
    if d == _SENTINEL:
        return "—"
    return d.strftime("%d %b %Y")
