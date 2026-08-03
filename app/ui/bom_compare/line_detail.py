"""
LineDetailDialog — shows how one comparison line's master value was calculated
(the TraceStep breakdown), and lets the user open the formula editor for that
line's component/customer. On save the formula is persisted locally and the
dialog reports `changed=True` so the caller can re-run the comparison.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialogButtonBox, QFrame,
)
from PySide6.QtCore import Qt

from app.core.comparator import ComparisonRow
from app.core.formula import COMPONENT_LABELS
from app.core.formula_store import formula_store
from app.ui.formulas.editor import FormulaEditorDialog


class LineDetailDialog(QDialog):
    def __init__(self, row: ComparisonRow, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Line detail — {row.code}")
        self.setMinimumWidth(560)
        self._row = row
        self.changed = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        r = self._row
        comp_label = COMPONENT_LABELS.get(r.component, r.component or "—")
        header = QLabel(
            f"<b>{r.section}</b> · {r.code}<br>"
            f"<span style='color:#64748b'>{r.description}</span>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        # Value summary
        vals = QLabel(
            f"Template: <b>${r.template_value:,.2f}</b>   "
            + (f"Master: <b>${r.master_value:,.2f}</b>   "
               f"Diff: <b>{r.diff_pct:+.1f}%</b>"
               if r.master_value is not None else
               "Master: <b>—</b> (no rate / formula match)")
        )
        vals.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(vals)

        # Formula
        fd = formula_store.get(r.component, r.customer_code)
        scope = "default"
        if fd is not None and fd.customer_code:
            scope = f"override · {fd.customer_code}"
        expr = fd.expression if fd else "(no formula)"
        formula_lbl = QLabel(
            f"<span style='color:#64748b'>Formula ({comp_label}, {scope}):</span><br>"
            f"<code>{expr}</code>"
        )
        formula_lbl.setTextFormat(Qt.TextFormat.RichText)
        formula_lbl.setWordWrap(True)
        layout.addWidget(formula_lbl)

        # Trace table
        if r.trace:
            layout.addWidget(self._build_trace_table(r))
        else:
            note = QLabel("No calculation trace — this line had no master value "
                          "(missing rate, disabled or unmatched formula).")
            note.setWordWrap(True)
            note.setStyleSheet("color: #94a3b8; font-size: 11px;")
            layout.addWidget(note)

        # Buttons
        btn_row = QHBoxLayout()
        edit_btn = QPushButton("Edit formula…")
        edit_btn.clicked.connect(self._edit_formula)
        btn_row.addWidget(edit_btn)
        btn_row.addStretch()
        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        close_box.accepted.connect(self.accept)
        btn_row.addWidget(close_box)
        layout.addLayout(btn_row)

    def _build_trace_table(self, r: ComparisonRow) -> QTableWidget:
        headers = ["Step", "Source", "Op", "Operand", "Running total"]
        t = QTableWidget(len(r.trace), len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, s in enumerate(r.trace):
            cells = [s.label, s.source, s.operator,
                     f"{s.operand:,.4f}", f"{s.running_total:,.4f}"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c >= 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(i, c, item)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        return t

    def _edit_formula(self):
        fd = formula_store.get(self._row.component, self._row.customer_code)
        if fd is None:
            return
        dlg = FormulaEditorDialog(fd, customer_code=self._row.customer_code, parent=self)
        if dlg.exec() and dlg.result_def is not None:
            formula_store.upsert(dlg.result_def)
            self.changed = True
            self.accept()
