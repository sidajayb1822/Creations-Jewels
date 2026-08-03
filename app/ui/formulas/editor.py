"""
FormulaEditor — edit one pricing formula in two interchangeable ways:

  • Guided builder   — ordered steps (operator + operand), operands chosen from
                       a variable dropdown or typed as a number/sub-expression.
  • Editable expression — the raw formula text with Validate + a variable legend.

Both views drive one underlying expression string (the canonical form). Switching
views round-trips through app.core.formula.to_builder_steps / from_builder_steps.

FormulaEditorDialog wraps the editor with a scope choice (save as the default,
or as a per-customer override) and OK/Cancel. Nothing here touches the Emperor
database — saving goes through the local formula_store.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QPlainTextEdit, QCheckBox,
    QStackedWidget, QScrollArea, QFrame, QDialogButtonBox, QMessageBox,
)
from PySide6.QtCore import Qt

from app.core.formula import (
    FormulaDef, VARIABLES, CONSTANTS, COMPONENT_LABELS,
    validate, evaluate, to_builder_steps, from_builder_steps,
    BuilderStep, FormulaError, sample_context,
)
from app.core.custom_var import custom_var_store

_OPERATORS = ["+", "-", "*", "/", "**"]

# Column widths shared between the header row and every step row (keeps them aligned).
_COL_OP_W = 96
_COL_SRC_W = 180
_COL_DEL_W = 96

# Operand dropdown, grouped by where the value comes from.
OPERAND_GROUPS: list[tuple[str, list[str]]] = [
    ("BOM line", ["weight", "qty", "lme", "pointer", "line_value",
                  "setting_rate", "setting_qty"]),
    ("Totals", ["metal_weight", "diamond_weight", "colour_weight"]),
    ("Database tables", ["RmMst_RmPurityRt", "RmRt_CRP", "RmRt_rate", "LabRt_rate",
                         "CmMulBy", "LossMst_LmLossPer"]),
    ("Setting", ["loss_pct"]),
    ("Constant", ["TROY_OZ"]),
]


def _custom_var_sources() -> dict[str, str]:
    """{name: source_ref} for enabled custom variables."""
    return {cv.name: cv.source_ref() for cv in custom_var_store.list_all() if cv.enabled}


def _populate_operand(combo: QComboBox) -> None:
    """Fill an editable combo with grouped, greyed section headers + variables."""
    model = combo.model()

    def _add_group(title: str, names: list[str]):
        combo.addItem(f"—  {title}  —")
        model.item(combo.count() - 1).setFlags(Qt.ItemFlag.NoItemFlags)
        for n in names:
            combo.addItem(n)

    for group, names in OPERAND_GROUPS:
        _add_group(group, names)
    custom = list(_custom_var_sources().keys())
    if custom:
        _add_group("Custom (your tables)", custom)


class _StepRow(QWidget):
    """One builder step: [operator] [operand dropdown] [source] [Remove]."""

    def __init__(self, is_first: bool, on_remove, on_change):
        super().__init__()
        self._is_first = is_first
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.op_combo = QComboBox()
        if is_first:
            self.op_combo.addItem("start")
            self.op_combo.setEnabled(False)
        else:
            self.op_combo.addItems(_OPERATORS)
        self.op_combo.setFixedWidth(_COL_OP_W)
        self.op_combo.currentIndexChanged.connect(lambda _: on_change())
        lay.addWidget(self.op_combo)

        # Editable combo: pick a variable from the grouped list or type a number.
        self.operand = QComboBox()
        self.operand.setEditable(True)
        self.operand.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        _populate_operand(self.operand)
        self.operand.setCurrentText("")
        self.operand.currentTextChanged.connect(lambda _: on_change())
        lay.addWidget(self.operand, 1)

        self.src_lbl = QLabel("")
        self.src_lbl.setStyleSheet("color: #94a3b8; font-size: 10px;")
        self.src_lbl.setFixedWidth(_COL_SRC_W)
        lay.addWidget(self.src_lbl)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setObjectName("outlineBtn")
        # Override the global button padding so the label isn't clipped.
        self.remove_btn.setStyleSheet("padding: 6px 10px;")
        self.remove_btn.setFixedWidth(_COL_DEL_W)
        self.remove_btn.clicked.connect(lambda: on_remove(self))
        lay.addWidget(self.remove_btn)

        self.operand.currentTextChanged.connect(self._update_source)

    def _update_source(self, text: str):
        key = text.strip()
        info = VARIABLES.get(key)
        custom = _custom_var_sources()
        if info:
            self.src_lbl.setText(info.source_ref)
        elif key in custom:
            self.src_lbl.setText(custom[key])
        elif key in CONSTANTS:
            self.src_lbl.setText("constant")
        elif key:
            self.src_lbl.setText("number / expression")
        else:
            self.src_lbl.setText("")

    def set_values(self, operator: str, operand: str):
        if not self._is_first:
            i = self.op_combo.findText(operator)
            self.op_combo.setCurrentIndex(i if i >= 0 else 0)
        self.operand.setCurrentText(operand)
        self._update_source(operand)

    def to_step(self) -> BuilderStep:
        op = "start" if self._is_first else self.op_combo.currentText()
        return BuilderStep(op, self.operand.currentText().strip())


class FormulaEditor(QWidget):
    """Dual-view editor for a single FormulaDef's expression."""

    def __init__(self, fd: FormulaDef, parent=None):
        super().__init__(parent)
        self._component = fd.component
        self._expression = fd.expression
        self._step_rows: list[_StepRow] = []
        self._build_ui()
        self._load_expression(fd.expression)

    # ---- UI ----
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel(f"Formula — {COMPONENT_LABELS.get(self._component, self._component)}")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        root.addWidget(title)

        # View toggle
        toggle = QHBoxLayout()
        self.builder_btn = QPushButton("Guided builder")
        self.expr_btn = QPushButton("Editable expression")
        for b in (self.builder_btn, self.expr_btn):
            b.setCheckable(True)
            b.setObjectName("segBtn")
        self.builder_btn.setChecked(True)
        self.builder_btn.clicked.connect(lambda: self._switch(0))
        self.expr_btn.clicked.connect(lambda: self._switch(1))
        toggle.addWidget(self.builder_btn)
        toggle.addWidget(self.expr_btn)
        toggle.addStretch()
        root.addLayout(toggle)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_builder_view())
        self.stack.addWidget(self._build_expression_view())
        root.addWidget(self.stack, 1)

        # Live preview
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color: #475569; font-size: 11px;")
        root.addWidget(self.preview)

    def _build_builder_view(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        hint = QLabel("Each step applies an operator to an operand, top to bottom "
                      "(left-to-right evaluation). Pick a variable from the dropdown "
                      "or type a number.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8; font-size: 11px;")
        v.addWidget(hint)

        # Column headers (aligned with the step rows via matching fixed widths).
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(6)

        def _hdr(text: str, width: int | None):
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #475569; font-size: 10px; font-weight: bold;")
            if width is not None:
                lbl.setFixedWidth(width)
            return lbl

        header.addWidget(_hdr("OPERATOR", _COL_OP_W))
        header.addWidget(_hdr("OPERAND  (variable or number)", None), 1)
        header.addWidget(_hdr("SOURCE", _COL_SRC_W))
        header.addWidget(_hdr("", _COL_DEL_W))
        v.addLayout(header)

        self._steps_host = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_host)
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._steps_host)
        v.addWidget(scroll, 1)

        add_btn = QPushButton("+ Add step")
        add_btn.setObjectName("outlineBtn")
        add_btn.clicked.connect(self._add_empty_step)
        v.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        return w

    def _build_expression_view(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        self.expr_edit = QPlainTextEdit()
        self.expr_edit.setPlaceholderText("(lme / TROY_OZ) * RmMst_RmPurityRt * (1 + loss_pct / 100) * weight")
        self.expr_edit.setFixedHeight(80)
        self.expr_edit.textChanged.connect(self._refresh_preview)
        v.addWidget(self.expr_edit)

        row = QHBoxLayout()
        val_btn = QPushButton("Validate")
        val_btn.setObjectName("outlineBtn")
        val_btn.clicked.connect(self._on_validate)
        row.addWidget(val_btn)
        row.addStretch()
        v.addLayout(row)

        legend = QLabel(self._legend_text())
        legend.setWordWrap(True)
        legend.setStyleSheet("color: #64748b; font-size: 10px;")
        v.addWidget(legend)
        return w

    def _legend_text(self) -> str:
        parts = []
        for name, info in VARIABLES.items():
            parts.append(f"{name} = {info.label} ({info.source_ref})")
        parts.append("TROY_OZ = 31.1035")
        parts.append("Operators: + - * /  **   ·  functions: min, max, round, abs")
        return "Variables:  " + "   ·   ".join(parts)

    # ---- step management ----
    def _add_empty_step(self):
        self._add_step(len(self._step_rows) == 0)

    def _add_step(self, is_first: bool) -> _StepRow:
        row = _StepRow(is_first, self._remove_step, self._refresh_preview)
        self._step_rows.append(row)
        self._steps_layout.addWidget(row)
        return row

    def _remove_step(self, row: _StepRow):
        if row not in self._step_rows:
            return
        self._step_rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        if not self._step_rows:
            # Never leave the builder empty.
            self._add_step(True)
        else:
            # Rebuild so the top row is always the "start" row and the
            # expression stays valid regardless of which row was removed.
            self._rebuild_from_expression(self._current_builder_expression())
        self._refresh_preview()

    def _clear_steps(self):
        for row in self._step_rows:
            row.setParent(None)
            row.deleteLater()
        self._step_rows = []

    # ---- load / sync ----
    def _load_expression(self, expr: str):
        self._rebuild_from_expression(expr)
        self.expr_edit.setPlainText(expr)
        self._refresh_preview()

    def _rebuild_from_expression(self, expr: str):
        self._clear_steps()
        try:
            steps = to_builder_steps(expr) if expr.strip() else []
        except FormulaError:
            steps = []
        if not steps:
            self._add_step(True)
            return
        for i, s in enumerate(steps):
            row = self._add_step(i == 0)
            row.set_values(s.operator, s.operand)

    def _current_builder_expression(self) -> str:
        steps = [r.to_step() for r in self._step_rows if r.to_step().operand]
        if steps:
            steps[0] = BuilderStep("start", steps[0].operand)
        return from_builder_steps(steps)

    def _switch(self, index: int):
        if index == self.stack.currentIndex():
            self._sync_toggle(index)
            return
        if index == 1:
            # builder -> expression
            self.expr_edit.setPlainText(self._current_builder_expression())
        else:
            # expression -> builder
            expr = self.expr_edit.toPlainText().strip()
            ok, msg = validate(expr)
            if not ok:
                QMessageBox.warning(self, "Cannot switch to builder",
                                    f"Fix the expression first:\n{msg}")
                self._sync_toggle(1)
                return
            self._rebuild_from_expression(expr)
        self.stack.setCurrentIndex(index)
        self._sync_toggle(index)
        self._refresh_preview()

    def _sync_toggle(self, index: int):
        self.builder_btn.setChecked(index == 0)
        self.expr_btn.setChecked(index == 1)

    # ---- validate / preview ----
    def _on_validate(self):
        ok, msg = validate(self.expr_edit.toPlainText().strip())
        QMessageBox.information(self, "Validation",
                               "Formula is valid." if ok else f"Invalid:\n{msg}")

    def current_expression(self) -> str:
        if self.stack.currentIndex() == 0:
            return self._current_builder_expression()
        return self.expr_edit.toPlainText().strip()

    def _refresh_preview(self):
        expr = self.current_expression()
        if not expr:
            self.preview.setText("Empty formula.")
            return
        ok, msg = validate(expr)
        if not ok:
            self.preview.setText(f"⚠ {msg}")
            return
        # Include custom variables with a nominal sample value so preview works.
        ctx = sample_context()
        for name in _custom_var_sources():
            ctx.setdefault(name, 1.0)
        try:
            val, _ = evaluate(expr, ctx)
            self.preview.setText(f"✓ Valid.  Preview on sample values = {val:,.4f}")
        except FormulaError as e:
            self.preview.setText(f"⚠ {e}")


class FormulaEditorDialog(QDialog):
    """Modal wrapper: edit a formula and choose default vs per-customer scope."""

    def __init__(self, fd: FormulaDef, customer_code: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Formula")
        self.setMinimumWidth(620)
        self.result_def: FormulaDef | None = None
        self._component = fd.component
        self._customer_code = (customer_code or "").strip()

        layout = QVBoxLayout(self)
        self.editor = FormulaEditor(fd)
        layout.addWidget(self.editor, 1)

        # Scope
        scope_box = QFrame()
        scope_box.setObjectName("card")
        sform = QFormLayout(scope_box)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Save as DEFAULT (all customers)", "")
        if self._customer_code:
            self.scope_combo.addItem(
                f"Save as override for customer {self._customer_code}",
                self._customer_code)
            # default to the customer scope when editing from a specific line
            self.scope_combo.setCurrentIndex(1)
        sform.addRow("Scope:", self.scope_combo)

        self.enabled_chk = QCheckBox("Enabled")
        self.enabled_chk.setChecked(fd.enabled)
        sform.addRow("", self.enabled_chk)

        self.notes_edit = QLineEdit(fd.notes)
        self.notes_edit.setPlaceholderText("Optional note")
        sform.addRow("Notes:", self.notes_edit)
        layout.addWidget(scope_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self):
        expr = self.editor.current_expression()
        ok, msg = validate(expr)
        if not ok:
            QMessageBox.warning(self, "Invalid formula", msg)
            return
        self.result_def = FormulaDef(
            component=self._component,
            customer_code=self.scope_combo.currentData(),
            expression=expr,
            enabled=self.enabled_chk.isChecked(),
            notes=self.notes_edit.text().strip(),
        )
        self.accept()
