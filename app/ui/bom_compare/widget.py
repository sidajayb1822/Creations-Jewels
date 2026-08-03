import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QMessageBox,
    QGroupBox, QGridLayout, QTabWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont

from app.ui.bom_compare.drop_zone import DropZone
from app.ui.bom_compare.comparison_table import ComparisonTable
from app.ui.bom_compare.line_detail import LineDetailDialog
from app.core.excel_parser import parse_workbook
from app.core.comparator import compare, summary_stats, ComparisonRow
from app.core.db import db, load_config, DEFAULT_METAL_LOSS_PCT


class _Worker(QObject):
    """Run parse + compare for every design in a workbook, off the UI thread."""
    done = Signal(list, str)   # [ {label, rows, stats}, ... ], order_info
    error = Signal(str)

    def __init__(self, file_path: str):
        super().__init__()
        self._path = file_path

    def run(self):
        try:
            docs = parse_workbook(self._path)

            # Company code + costing settings come from config / the first design.
            cfg = load_config()
            company_code = (cfg.get("company_code") or "").strip()
            customer = docs[0].header.customer if docs else ""
            if not company_code and customer and db.is_connected():
                company_code = db.find_company_code(customer)

            loss_pct = db.get_metal_loss_pct(company_code)
            loss_source = "Emperor"
            if loss_pct is None:
                loss_pct = float(cfg.get("metal_loss_pct", DEFAULT_METAL_LOSS_PCT))
                loss_source = "default"
            multiplier = db.get_customer_multiplier(company_code)

            results = []
            for d in docs:
                rows = compare(d, db, company_code=company_code, loss_pct=loss_pct)
                stats = summary_stats(rows, multiplier=multiplier)
                results.append({"label": d.design_label, "rows": rows, "stats": stats})

            order_no = docs[0].header.order_no if docs else ""
            order_info = (
                f"{order_no}  |  {customer}  |  {len(docs)} design(s)"
                + (f"  |  Co: {company_code}" if company_code else "")
                + f"  |  Loss: {loss_pct:g}% ({loss_source})"
                + (f"  |  ×{multiplier:g}" if multiplier != 1.0 else "")
            )
            self.done.emit(results, order_info)
        except Exception as e:
            self.error.emit(str(e))


class _DesignComparePanel(QWidget):
    """One design's comparison table + summary bar. Reused per sub-tab."""

    def __init__(self, on_edit_formula=None, parent=None):
        super().__init__(parent)
        self._rows: list[ComparisonRow] = []
        self._on_edit_formula = on_edit_formula

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.table = ComparisonTable()
        self.table.cellDoubleClicked.connect(self._open_line_detail)
        layout.addWidget(self.table, 1)

        layout.addWidget(self._build_summary_bar())

        hint = QLabel("Double-click a line to see how it is calculated and edit its formula.")
        hint.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(hint)

    def _build_summary_bar(self) -> QGroupBox:
        group = QGroupBox("Summary")
        grid = QGridLayout(group)
        grid.setSpacing(14)

        def _stat(label: str, col: int) -> QLabel:
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #64748b; font-size: 11px;")
            val = QLabel("—")
            val.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            grid.addWidget(lbl, 0, col)
            grid.addWidget(val, 1, col)
            return val

        self._sum_template = _stat("Template Total ($)", 0)
        self._sum_master = _stat("Master Total ($)", 1)
        self._sum_diff = _stat("Difference ($)", 2)
        self._sum_pct = _stat("Difference (%)", 3)
        self._sum_ok = _stat("OK", 4)
        self._sum_warn = _stat("Warning", 5)
        self._sum_err = _stat("Over Threshold", 6)
        self._sum_miss = _stat("Missing", 7)
        return group

    def load(self, rows: list[ComparisonRow], stats: dict):
        self._rows = rows
        self.table.load(rows)
        c = stats["counts"]
        self._sum_template.setText(f"$ {stats['total_template']:,.2f}")
        self._sum_master.setText(f"$ {stats['total_master']:,.2f}")
        diff, pct = stats["total_diff"], stats["total_pct"]
        color = "#10b981" if abs(pct) <= 5 else ("#d97706" if abs(pct) <= 15 else "#dc2626")
        self._sum_diff.setText(f"$ {diff:+,.2f}")
        self._sum_diff.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")
        self._sum_pct.setText(f"{pct:+.1f}%")
        self._sum_pct.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")
        self._sum_ok.setText(str(c.get("match", 0)))
        self._sum_warn.setText(str(c.get("minor", 0)))
        self._sum_err.setText(str(c.get("major", 0)))
        self._sum_miss.setText(str(c.get("missing", 0)))

    def rows(self) -> list[ComparisonRow]:
        return self._rows

    def _open_line_detail(self, table_row: int, _col: int):
        row = self.table.row_at(table_row)
        if row is None:
            return
        dlg = LineDetailDialog(row, self)
        dlg.exec()
        if dlg.changed and self._on_edit_formula:
            self._on_edit_formula()


class BOMCompareWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._last_path: str = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

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

        self.order_label = QLabel("No file loaded")
        self.order_label.setStyleSheet("color: #64748b; font-style: italic;")
        layout.addWidget(self.order_label)

        # One sub-tab per design.
        self.tabs = QTabWidget()
        self.tabs.setObjectName("designTabs")
        layout.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout()
        self.export_btn = QPushButton("Export Active Design to Excel")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        btn_row.addStretch()
        btn_row.addWidget(self.export_btn)
        layout.addLayout(btn_row)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Emperor BOM File", "", "Excel Files (*.xlsx)"
        )
        if path:
            self._on_file(path)

    def _on_file(self, path: str):
        self._last_path = path
        self.order_label.setText(f"Loading  {os.path.basename(path)} …")
        self.export_btn.setEnabled(False)
        self.tabs.clear()

        self._thread = QThread()
        self._worker = _Worker(path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.done.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, results: list, order_info: str):
        self.order_label.setText(order_info)
        self.tabs.clear()
        for res in results:
            panel = _DesignComparePanel(on_edit_formula=self._reload)
            panel.load(res["rows"], res["stats"])
            self.tabs.addTab(panel, res["label"])
        self.export_btn.setEnabled(bool(results))

    def _on_error(self, msg: str):
        self.order_label.setText("Error loading file")
        QMessageBox.critical(self, "Parse Error", msg)

    def _reload(self):
        """Re-run the comparison after a formula edit so numbers update."""
        if self._last_path:
            self._on_file(self._last_path)

    def _export(self):
        # Gather every design tab so a multi-BOM file exports as one workbook,
        # one sheet per design.
        designs: list[tuple[str, list[ComparisonRow]]] = []
        for i in range(self.tabs.count()):
            panel = self.tabs.widget(i)
            if isinstance(panel, _DesignComparePanel) and panel.rows():
                designs.append((self.tabs.tabText(i), panel.rows()))
        if not designs:
            return
        default_name = (f"{designs[0][0]}-comparison.xlsx" if len(designs) == 1
                        else "order-comparison.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Comparison", default_name, "Excel Files (*.xlsx)"
        )
        if not path:
            return
        try:
            _export_to_excel(designs, path)
            sheets = "1 sheet" if len(designs) == 1 else f"{len(designs)} sheets"
            QMessageBox.information(self, "Exported", f"Saved {sheets} to:\n{path}")
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


_EXPORT_HEADERS = ["Section", "Code", "Description",
                   "Template ($)", "Master ($)", "Diff ($)", "Diff (%)"]


def _safe_sheet_name(name: str, used: set) -> str:
    """Excel sheet names: <=31 chars, none of []:*?/\\, and unique."""
    clean = "".join("_" if c in r"[]:*?/\\" else c for c in (name or "Design"))[:31]
    clean = clean.strip() or "Design"
    base, n = clean, 2
    while clean.lower() in used:
        suffix = f"_{n}"
        clean = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(clean.lower())
    return clean


def _write_design_sheet(ws, rows: list[ComparisonRow]):
    from openpyxl.styles import PatternFill, Font, Alignment

    ws.append(_EXPORT_HEADERS)
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
        fill = PatternFill("solid", fgColor=_STATUS_FILLS.get(row.status, "FFFFFFFF"))
        for cell in ws[ws.max_row]:
            cell.fill = fill

    for col, width in enumerate([18, 18, 40, 14, 14, 12, 12], start=1):
        ws.column_dimensions[ws.cell(1, col).column_letter].width = width

    for row in ws.iter_rows(min_row=2):
        for c_idx in [3, 4, 5]:
            row[c_idx].number_format = '#,##0.00'
        row[6].number_format = '+0.0%;-0.0%;0.0%'


def _export_to_excel(designs: list[tuple[str, list[ComparisonRow]]], path: str):
    """Write one sheet per design into a single workbook."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)   # drop the default empty sheet
    used: set = set()
    for name, rows in designs:
        ws = wb.create_sheet(_safe_sheet_name(name, used))
        _write_design_sheet(ws, rows)
    if not wb.sheetnames:      # safety: never save an empty workbook
        _write_design_sheet(wb.create_sheet("BOM Comparison"), [])
    wb.save(path)
