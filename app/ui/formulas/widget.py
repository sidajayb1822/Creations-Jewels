"""
FormulasWidget — the sidebar "Formulas" page: full CRUD over the local pricing
formulas (app.core.formula_store). Create / edit / delete / reset-to-default.
All changes are local; the Emperor database is never written to.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QDialog, QFormLayout, QDialogButtonBox, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt

from app.core.formula import FormulaDef, COMPONENTS, COMPONENT_LABELS
from app.core.formula_store import formula_store, SEED_DEFAULTS
from app.core.custom_var import custom_var_store
from app.ui.formulas.editor import FormulaEditorDialog
from app.ui.formulas.custom_var_dialog import CustomVarDialog

_HEADERS = ["Component", "Customer", "Expression", "Enabled", "Notes"]
_CV_HEADERS = ["Name", "Table", "Value column", "Match keys", "Source"]


class _NewFormulaDialog(QDialog):
    """Pick a component + optional customer before opening the editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Formula")
        self.setMinimumWidth(380)
        form = QFormLayout(self)

        self.comp_combo = QComboBox()
        for c in COMPONENTS:
            self.comp_combo.addItem(COMPONENT_LABELS.get(c, c), c)
        form.addRow("Component:", self.comp_combo)

        self.cust_edit = QLineEdit()
        self.cust_edit.setPlaceholderText("blank = default (all customers)")
        form.addRow("Customer code:", self.cust_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @property
    def component(self) -> str:
        return self.comp_combo.currentData()

    @property
    def customer_code(self) -> str:
        return self.cust_edit.text().strip()


class FormulasWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.reload()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel(
            "Pricing formulas used by the BOM comparison. Defaults apply to all "
            "customers; add an override for a specific customer code. Stored "
            "locally — the Emperor database is never modified."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #64748b;")
        layout.addWidget(intro)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda _: self._edit())
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        for text, slot in [
            ("New…", self._new),
            ("Edit…", self._edit),
            ("Delete", self._delete),
            ("Reset to default", self._reset),
            ("Refresh", self.reload),
        ]:
            b = QPushButton(text)
            if text in ("Edit…", "Delete", "Reset to default"):
                b.setObjectName("outlineBtn")
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ---- Custom variables ----
        cv_intro = QLabel(
            "Custom variables — your own DB lookups (any table + column + match "
            "keys). Once saved they become selectable in every formula dropdown, "
            "so new Emperor masters can be used without a code change."
        )
        cv_intro.setWordWrap(True)
        cv_intro.setStyleSheet("color: #64748b; margin-top: 8px;")
        layout.addWidget(cv_intro)

        self.cv_table = QTableWidget(0, len(_CV_HEADERS))
        self.cv_table.setHorizontalHeaderLabels(_CV_HEADERS)
        self.cv_table.verticalHeader().setVisible(False)
        self.cv_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cv_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cv_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cv_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.cv_table.doubleClicked.connect(lambda _: self._edit_cv())
        layout.addWidget(self.cv_table, 1)

        cv_btn_row = QHBoxLayout()
        for text, slot in [
            ("New variable…", self._new_cv),
            ("Edit variable…", self._edit_cv),
            ("Delete variable", self._delete_cv),
        ]:
            b = QPushButton(text)
            if "Edit" in text or "Delete" in text:
                b.setObjectName("outlineBtn")
            b.clicked.connect(slot)
            cv_btn_row.addWidget(b)
        cv_btn_row.addStretch()
        layout.addLayout(cv_btn_row)

    # ---- data ----
    def reload(self):
        formula_store.reload()
        defs = formula_store.list_all()
        self.table.setRowCount(len(defs))
        for i, fd in enumerate(defs):
            cells = [
                COMPONENT_LABELS.get(fd.component, fd.component),
                fd.customer_code or "(default)",
                fd.expression,
                "Yes" if fd.enabled else "No",
                fd.notes,
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, fd)
                self.table.setItem(i, c, item)
        self.table.resizeRowsToContents()
        self._reload_custom_vars()

    def _reload_custom_vars(self):
        custom_var_store.reload()
        cvs = custom_var_store.list_all()
        self.cv_table.setRowCount(len(cvs))
        for i, cv in enumerate(cvs):
            match_desc = ", ".join(
                f"{mk.column}{mk.op}{mk.literal if mk.source == 'literal' else mk.source}"
                for mk in cv.match_keys) or "(none)"
            cells = [cv.name, cv.table, cv.value_column, match_desc, cv.source_ref()]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, cv)
                self.cv_table.setItem(i, c, item)
        self.cv_table.resizeRowsToContents()

    def _selected_cv(self):
        r = self.cv_table.currentRow()
        if r < 0:
            return None
        item = self.cv_table.item(r, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected(self) -> FormulaDef | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            r = self.table.currentRow()
            if r < 0:
                return None
            item = self.table.item(r, 0)
        else:
            item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # ---- actions ----
    def _new(self):
        picker = _NewFormulaDialog(self)
        if not picker.exec():
            return
        component = picker.component
        customer = picker.customer_code
        # Seed the editor with the existing default expression for that component.
        base = formula_store.get(component, "") or SEED_DEFAULTS.get(component)
        seed = FormulaDef(component=component, customer_code=customer,
                          expression=base.expression if base else "",
                          notes=base.notes if base else "")
        dlg = FormulaEditorDialog(seed, customer_code=customer, parent=self)
        if dlg.exec() and dlg.result_def is not None:
            formula_store.upsert(dlg.result_def)
            self.reload()

    def _edit(self):
        fd = self._selected()
        if fd is None:
            QMessageBox.information(self, "Edit", "Select a formula first.")
            return
        dlg = FormulaEditorDialog(fd, customer_code=fd.customer_code, parent=self)
        if dlg.exec() and dlg.result_def is not None:
            # If the scope changed the key, drop the old row.
            if dlg.result_def.key() != fd.key():
                formula_store.delete(fd.component, fd.customer_code)
            formula_store.upsert(dlg.result_def)
            self.reload()

    def _delete(self):
        fd = self._selected()
        if fd is None:
            QMessageBox.information(self, "Delete", "Select a formula first.")
            return
        scope = fd.customer_code or "default"
        msg = (f"Delete the {COMPONENT_LABELS.get(fd.component, fd.component)} "
               f"formula for {scope}?")
        if not fd.customer_code:
            msg += "\n\nThis is a default — it will be restored to the built-in seed."
        if QMessageBox.question(self, "Delete formula", msg) != QMessageBox.StandardButton.Yes:
            return
        formula_store.delete(fd.component, fd.customer_code)
        self.reload()

    def _reset(self):
        fd = self._selected()
        if fd is None:
            QMessageBox.information(self, "Reset", "Select a formula first.")
            return
        formula_store.reset_to_default(fd.component, fd.customer_code)
        self.reload()

    # ---- custom variable actions ----
    def _new_cv(self):
        dlg = CustomVarDialog(parent=self)
        if dlg.exec() and dlg.result_var is not None:
            custom_var_store.upsert(dlg.result_var)
            self._reload_custom_vars()

    def _edit_cv(self):
        cv = self._selected_cv()
        if cv is None:
            QMessageBox.information(self, "Edit variable", "Select a custom variable first.")
            return
        dlg = CustomVarDialog(cv, parent=self)
        if dlg.exec() and dlg.result_var is not None:
            # Name may have changed → drop the old entry.
            if dlg.result_var.name != cv.name:
                custom_var_store.delete(cv.name)
            custom_var_store.upsert(dlg.result_var)
            self._reload_custom_vars()

    def _delete_cv(self):
        cv = self._selected_cv()
        if cv is None:
            QMessageBox.information(self, "Delete variable", "Select a custom variable first.")
            return
        if QMessageBox.question(
            self, "Delete custom variable",
            f"Delete custom variable '{cv.name}'?\n\nFormulas that reference it will "
            f"then show those lines as 'missing' until edited."
        ) != QMessageBox.StandardButton.Yes:
            return
        custom_var_store.delete(cv.name)
        self._reload_custom_vars()
