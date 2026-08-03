"""
CustomVarDialog — define/edit a custom variable: a live DB lookup against any
Emperor table, wired from the UI (table/column dropdowns come from live schema
discovery). No code change needed to price against a new master.
"""

from __future__ import annotations

import keyword

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QScrollArea, QFrame, QDialogButtonBox, QMessageBox,
    QWidget,
)
from PySide6.QtCore import Qt

from app.core.db import db
from app.core.custom_var import (
    CustomVar, MatchKey, MATCH_SOURCES, OPERATORS, AGGREGATES,
)
from app.core.formula import VARIABLES, CONSTANTS


class _MatchRow(QWidget):
    """One match condition: [column] [op] [source] [literal] [remove]."""

    def __init__(self, columns: list[str], on_remove):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.col = QComboBox()
        self.col.setEditable(True)
        self.col.addItems(columns)
        self.col.setCurrentText("")
        lay.addWidget(self.col, 2)

        self.op = QComboBox()
        self.op.addItems(OPERATORS)
        self.op.setFixedWidth(64)
        lay.addWidget(self.op)

        self.source = QComboBox()
        for key, lbl in MATCH_SOURCES.items():
            self.source.addItem(lbl, key)
        self.source.currentIndexChanged.connect(self._toggle_literal)
        lay.addWidget(self.source, 2)

        self.literal = QLineEdit()
        self.literal.setPlaceholderText("fixed value")
        self.literal.setEnabled(False)
        lay.addWidget(self.literal, 1)

        rm = QPushButton("Remove")
        rm.setObjectName("outlineBtn")
        rm.setStyleSheet("padding: 6px 10px;")
        rm.setFixedWidth(90)
        rm.clicked.connect(lambda: on_remove(self))
        lay.addWidget(rm)

    def _toggle_literal(self):
        self.literal.setEnabled(self.source.currentData() == "literal")

    def set_columns(self, columns: list[str]):
        cur = self.col.currentText()
        self.col.clear()
        self.col.addItems(columns)
        self.col.setCurrentText(cur)

    def load(self, mk: MatchKey):
        self.col.setCurrentText(mk.column)
        i = self.op.findText(mk.op)
        self.op.setCurrentIndex(i if i >= 0 else 0)
        si = self.source.findData(mk.source)
        self.source.setCurrentIndex(si if si >= 0 else 0)
        self.literal.setText(mk.literal)
        self._toggle_literal()

    def to_match_key(self) -> MatchKey | None:
        col = self.col.currentText().strip()
        if not col:
            return None
        return MatchKey(column=col, op=self.op.currentText(),
                        source=self.source.currentData(),
                        literal=self.literal.text().strip())


class CustomVarDialog(QDialog):
    def __init__(self, cv: CustomVar | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Variable")
        self.setMinimumWidth(680)
        self.result_var: CustomVar | None = None
        self._editing_name = cv.name if cv else None
        self._match_rows: list[_MatchRow] = []
        self._tables = self._load_tables()
        self._build_ui()
        if cv:
            self._load(cv)
        else:
            self._add_match_row()
        self._refresh_columns()

    # ---- schema helpers ----
    def _load_tables(self) -> list[str]:
        try:
            return db.list_tables() if db.is_connected() else []
        except Exception:
            return []

    def _columns_for(self, table: str) -> list[str]:
        if not table or not db.is_connected():
            return []
        try:
            return [c["COLUMN_NAME"] for c in db.list_columns(table)]
        except Exception:
            return []

    # ---- UI ----
    def _build_ui(self):
        layout = QVBoxLayout(self)

        if not db.is_connected():
            warn = QLabel("Not connected to Emperor — connect in Settings to pick "
                          "tables/columns from dropdowns. You can still type names.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #b45309;")
            layout.addWidget(warn)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. setting_master_rate  (letters/digits/underscore)")
        form.addRow("Variable name:", self.name_edit)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("optional friendly label")
        form.addRow("Label:", self.label_edit)

        self.table_combo = QComboBox()
        self.table_combo.setEditable(True)
        self.table_combo.addItems(self._tables)
        self.table_combo.setCurrentText("")
        self.table_combo.currentTextChanged.connect(lambda _: self._refresh_columns())
        form.addRow("Table:", self.table_combo)

        self.value_combo = QComboBox()
        self.value_combo.setEditable(True)
        form.addRow("Value column:", self.value_combo)

        self.agg_combo = QComboBox()
        self.agg_combo.addItems(AGGREGATES)
        form.addRow("Aggregate:", self.agg_combo)
        layout.addLayout(form)

        # Match keys
        mk_head = QLabel("Match conditions  (column  ·  operator  ·  source)")
        mk_head.setStyleSheet("font-weight: bold; color: #334155; margin-top: 6px;")
        layout.addWidget(mk_head)
        hint = QLabel("The lookup returns the value column from the row(s) where every "
                      "condition holds. Sources come from the BOM line being priced.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(hint)

        self._mk_host = QWidget()
        self._mk_layout = QVBoxLayout(self._mk_host)
        self._mk_layout.setContentsMargins(0, 0, 0, 0)
        self._mk_layout.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._mk_host)
        scroll.setMinimumHeight(140)
        layout.addWidget(scroll, 1)

        add_btn = QPushButton("+ Add match condition")
        add_btn.setObjectName("outlineBtn")
        add_btn.clicked.connect(self._add_match_row)
        layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("optional note")
        nform = QFormLayout()
        nform.addRow("Notes:", self.notes_edit)
        layout.addLayout(nform)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_match_row(self) -> _MatchRow:
        row = _MatchRow(self._columns_for(self.table_combo.currentText().strip()),
                        self._remove_match_row)
        self._match_rows.append(row)
        self._mk_layout.addWidget(row)
        return row

    def _remove_match_row(self, row: _MatchRow):
        if row in self._match_rows:
            self._match_rows.remove(row)
            row.setParent(None)
            row.deleteLater()

    def _refresh_columns(self):
        cols = self._columns_for(self.table_combo.currentText().strip())
        cur = self.value_combo.currentText()
        self.value_combo.clear()
        self.value_combo.addItems(cols)
        self.value_combo.setCurrentText(cur)
        for row in self._match_rows:
            row.set_columns(cols)

    def _load(self, cv: CustomVar):
        self.name_edit.setText(cv.name)
        self.label_edit.setText(cv.label)
        self.table_combo.setCurrentText(cv.table)
        self.value_combo.setCurrentText(cv.value_column)
        ai = self.agg_combo.findText(cv.aggregate)
        self.agg_combo.setCurrentIndex(ai if ai >= 0 else 0)
        self.notes_edit.setText(cv.notes)
        for mk in cv.match_keys:
            self._add_match_row().load(mk)
        if not cv.match_keys:
            self._add_match_row()

    def _on_save(self):
        name = self.name_edit.text().strip()
        if not name.isidentifier() or keyword.iskeyword(name):
            QMessageBox.warning(self, "Invalid name",
                                "Name must be a valid identifier (letters, digits, "
                                "underscore; not starting with a digit).")
            return
        if name in VARIABLES or name in CONSTANTS:
            QMessageBox.warning(self, "Name in use",
                                f"'{name}' is a built-in variable. Pick another name.")
            return
        table = self.table_combo.currentText().strip()
        value_column = self.value_combo.currentText().strip()
        if not table or not value_column:
            QMessageBox.warning(self, "Missing table/column",
                                "Choose a table and a value column.")
            return
        keys = [mk for mk in (r.to_match_key() for r in self._match_rows) if mk]
        self.result_var = CustomVar(
            name=name, table=table, value_column=value_column,
            aggregate=self.agg_combo.currentText(),
            label=self.label_edit.text().strip(),
            match_keys=keys, enabled=True,
            notes=self.notes_edit.text().strip(),
        )
        self.accept()
