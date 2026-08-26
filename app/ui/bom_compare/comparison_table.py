from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QFont

from app.core.comparator import ComparisonRow

HEADERS = ["Section", "Code", "Description", "Template ($)", "Master ($)", "Diff ($)", "Diff (%)"]

STATUS_COLORS = {
    "match":   QColor("#d1fae5"),   # emerald-100
    "minor":   QColor("#fef3c7"),   # amber-100
    "major":   QColor("#fee2e2"),   # red-100
    "missing": QColor("#f1f5f9"),   # slate-100
}

TEXT_COLORS = {
    "match":   QColor("#065f46"),   # emerald-800
    "minor":   QColor("#92400e"),   # amber-800
    "major":   QColor("#991b1b"),   # red-800
    "missing": QColor("#475569"),   # slate-600
}


class ComparisonTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, len(HEADERS), parent)
        self.setHorizontalHeaderLabels(HEADERS)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(False)
        self.setSortingEnabled(True)

        hdr_font = QFont()
        hdr_font.setBold(True)
        self.horizontalHeader().setFont(hdr_font)

    def load(self, rows: list[ComparisonRow]):
        self.setSortingEnabled(False)
        self.setRowCount(0)
        self.setRowCount(len(rows))

        for r_idx, row in enumerate(rows):
            bg = STATUS_COLORS.get(row.status, QColor("white"))
            fg = TEXT_COLORS.get(row.status, QColor("#0f172a"))

            from_base = bool(getattr(row, "source_note", ""))
            master_text = (f"{row.master_value:,.2f}" if row.master_value is not None else "N/A")
            if from_base:
                master_text += " *"

            cells = [
                row.section,
                row.code,
                row.description,
                f"{row.template_value:,.2f}",
                master_text,
                f"{row.diff_dollar:+,.2f}" if row.master_value is not None else "—",
                f"{row.diff_pct:+.1f}%" if row.master_value is not None else "—",
            ]

            base_tip = (f"From base chart ({row.customer_code or 'fallback'} → "
                        f"{row.source_note}) — customer chart has no entry"
                        if from_base else "")
            for c_idx, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setBackground(QBrush(bg))
                item.setForeground(QBrush(fg))
                if c_idx >= 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if from_base:
                    item.setToolTip(base_tip)
                # Stash the source row on col 0 so clicks survive sorting.
                if c_idx == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row)
                self.setItem(r_idx, c_idx, item)

        self.setSortingEnabled(True)
        self.resizeRowsToContents()

    def row_at(self, table_row: int) -> "ComparisonRow | None":
        """Return the ComparisonRow shown at a visual row index (sort-safe)."""
        item = self.item(table_row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def clear_data(self):
        self.setRowCount(0)
