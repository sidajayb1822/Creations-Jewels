import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QMessageBox,
    QGroupBox, QGridLayout,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont

from app.ui.bom_compare.drop_zone import DropZone
from app.ui.bom_compare.comparison_table import ComparisonTable
from app.core.excel_parser import parse_bom
from app.core.comparator import compare, summary_stats, ComparisonRow
from app.core.db import db


class _Worker(QObject):
    """Run parse + compare off the UI thread."""
    done = Signal(list, dict, str)   # rows, stats, order_info
    error = Signal(str)

    def __init__(self, file_path: str):
        super().__init__()
        self._path = file_path

    def run(self):
        try:
            doc = parse_bom(self._path)

            # Auto-detect company code from the BOM customer name
            company_code = ""
            if doc.header.customer and db.is_connected():
                company_code = db.find_company_code(doc.header.customer)

            rows = compare(doc, db, company_code=company_code)
            stats = summary_stats(rows)
            order_info = (
                f"{doc.header.order_no}  |  {doc.header.design_code}  "
                f"|  {doc.header.customer}  |  Qty: {doc.header.quantity}"
                + (f"  |  Co: {company_code}" if company_code else "")
            )
            self.done.emit(rows, stats, order_info)
        except Exception as e:
            self.error.emit(str(e))


class BOMCompareWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._last_rows: list[ComparisonRow] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # Drop zone + browse button row
        drop_row = QHBoxLayout()
        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self._on_file)
        drop_row.addWidget(self.drop_zone)

        browse_btn = QPushButton("Browse…")
        browse_btn.setObjectName("outlineBtn")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse)
        drop_row.addWidget(browse_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(drop_row)

        # Order info bar
        self.order_label = QLabel("No file loaded")
        self.order_label.setStyleSheet("color: #64748b; font-style: italic;")
        layout.addWidget(self.order_label)

        # Comparison table
        self.table = ComparisonTable()
        layout.addWidget(self.table, 1)

        # Summary bar
        layout.addWidget(self._build_summary_bar())

        # Action buttons
        btn_row = QHBoxLayout()
        self.export_btn = QPushButton("Export Comparison to Excel")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        btn_row.addStretch()
        btn_row.addWidget(self.export_btn)
        layout.addLayout(btn_row)

    def _build_summary_bar(self) -> QGroupBox:
        group = QGroupBox("Summary")
        grid = QGridLayout(group)
        grid.setSpacing(16)

        def _stat(label: str, col: int) -> QLabel:
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #64748b; font-size: 11px;")
            val = QLabel("—")
            val.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            grid.addWidget(lbl, 0, col)
            grid.addWidget(val, 1, col)
            return val

        self._sum_template = _stat("Template Total ($)", 0)
        self._sum_master   = _stat("Master Total ($)",   1)
        self._sum_diff     = _stat("Difference ($)",     2)
        self._sum_pct      = _stat("Difference (%)",     3)
        self._sum_ok       = _stat("Lines OK",           4)
        self._sum_warn     = _stat("Lines Warning",      5)
        self._sum_err      = _stat("Lines Over Threshold", 6)
        self._sum_miss     = _stat("Missing in Master",  7)
        return group

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Emperor BOM File", "", "Excel Files (*.xlsx)"
        )
        if path:
            self._on_file(path)

    def _on_file(self, path: str):
        self.order_label.setText(f"Loading  {os.path.basename(path)} …")
        self.export_btn.setEnabled(False)
        self.table.clear_data()

        self._thread = QThread()
        self._worker = _Worker(path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.done.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, rows: list[ComparisonRow], stats: dict, order_info: str):
        self._last_rows = rows
        self.order_label.setText(order_info)
        self.table.load(rows)

        c = stats["counts"]
        self._sum_template.setText(f"$ {stats['total_template']:,.2f}")
        self._sum_master.setText(f"$ {stats['total_master']:,.2f}")

        diff = stats["total_diff"]
        pct  = stats["total_pct"]
        color = "#10b981" if abs(pct) <= 5 else ("#d97706" if abs(pct) <= 15 else "#dc2626")
        self._sum_diff.setText(f"$ {diff:+,.2f}")
        self._sum_diff.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")
        self._sum_pct.setText(f"{pct:+.1f}%")
        self._sum_pct.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")

        self._sum_ok.setText(str(c.get("match", 0)))
        self._sum_warn.setText(str(c.get("minor", 0)))
        self._sum_err.setText(str(c.get("major", 0)))
        self._sum_miss.setText(str(c.get("missing", 0)))

        self.export_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self.order_label.setText("Error loading file")
        QMessageBox.critical(self, "Parse Error", msg)

    def _export(self):
        if not self._last_rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Comparison", "", "Excel Files (*.xlsx)"
        )
        if not path:
            return
        try:
            _export_to_excel(self._last_rows, path)
            QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

_STATUS_FILLS = {
    "match":   "FFd4edda",
    "minor":   "FFfff3cd",
    "major":   "FFf8d7da",
    "missing": "FFe2e3e5",
}


def _export_to_excel(rows: list[ComparisonRow], path: str):
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "BOM Comparison"

    headers = ["Section", "Code", "Description",
               "Template ($)", "Master ($)", "Diff ($)", "Diff (%)"]
    ws.append(headers)

    hdr_font = Font(bold=True, color="FFFFFFFF")
    hdr_fill = PatternFill("solid", fgColor="FF3949AB")
    for cell in ws[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center")

    for row in rows:
        ws.append([
            row.section,
            row.code,
            row.description,
            row.template_value,
            row.master_value if row.master_value is not None else "N/A",
            row.diff_dollar if row.master_value is not None else None,
            row.diff_pct / 100 if row.master_value is not None else None,
        ])
        fill_color = _STATUS_FILLS.get(row.status, "FFFFFFFF")
        fill = PatternFill("solid", fgColor=fill_color)
        for cell in ws[ws.max_row]:
            cell.fill = fill

    # Column widths
    for col, width in enumerate([18, 18, 40, 14, 14, 12, 12], start=1):
        ws.column_dimensions[ws.cell(1, col).column_letter].width = width

    # Format numeric columns
    for row in ws.iter_rows(min_row=2):
        for c_idx in [4, 5, 6]:
            row[c_idx].number_format = '#,##0.00'
        row[6].number_format = '+0.0%;-0.0%;0.0%'

    wb.save(path)
