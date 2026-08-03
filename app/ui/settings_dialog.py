from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QDialogButtonBox, QGroupBox, QSpinBox, QDoubleSpinBox, QInputDialog,
)
from PySide6.QtCore import Qt

from app.core.db import (
    load_config, save_config, db, build_connection_string, DEFAULT_METAL_LOSS_PCT,
)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Database Connection Settings")
        self.setMinimumWidth(480)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        group = QGroupBox("Emperor SQL Server Connection")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText(r"e.g.  192.168.1.10\EMRSQL  or  .\EMRSQL")
        form.addRow("Server:", self.server_edit)

        db_row = QHBoxLayout()
        self.database_edit = QLineEdit()
        self.database_edit.setPlaceholderText("e.g.  EmrDaily")
        browse_btn = QPushButton("Browse…")
        browse_btn.setObjectName("outlineBtn")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_databases)
        db_row.addWidget(self.database_edit)
        db_row.addWidget(browse_btn)
        form.addRow("Database:", db_row)

        self.auth_combo = QComboBox()
        self.auth_combo.addItems(["SQL Server Authentication", "Windows Authentication"])
        self.auth_combo.currentIndexChanged.connect(self._on_auth_changed)
        form.addRow("Auth type:", self.auth_combo)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("SQL login username")
        form.addRow("Username:", self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("SQL login password")
        form.addRow("Password:", self.pass_edit)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(3, 120)
        self.timeout_spin.setValue(10)
        self.timeout_spin.setSuffix(" seconds")
        form.addRow("Timeout:", self.timeout_spin)

        layout.addWidget(group)

        # ---- Costing settings ----
        costing = QGroupBox("Costing")
        cform = QFormLayout(costing)
        cform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        cform.setSpacing(8)

        self.company_edit = QLineEdit()
        self.company_edit.setPlaceholderText("e.g.  OM-LGD   (blank = detect from BOM customer)")
        cform.addRow("Company code:", self.company_edit)

        self.loss_spin = QDoubleSpinBox()
        self.loss_spin.setRange(0.0, 100.0)
        self.loss_spin.setDecimals(2)
        self.loss_spin.setSingleStep(0.5)
        self.loss_spin.setValue(DEFAULT_METAL_LOSS_PCT)
        self.loss_spin.setSuffix(" %")
        cform.addRow("Metal loss %:", self.loss_spin)

        loss_hint = QLabel(
            "Wastage uplift on the fine metal rate. Emperor's own value "
            "(CustMst → LossMst) is used when present; this is the fallback."
        )
        loss_hint.setWordWrap(True)
        loss_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        cform.addRow("", loss_hint)

        layout.addWidget(costing)

        # Test connection row
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._test)
        self.test_label = QLabel("")
        self.test_label.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_label, 1)
        layout.addLayout(test_row)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_auth_changed(self, index: int):
        sql_auth = index == 0
        self.user_edit.setEnabled(sql_auth)
        self.pass_edit.setEnabled(sql_auth)

    def _load(self):
        cfg = load_config()
        self.server_edit.setText(cfg.get("server", r".\EMRSQL"))
        self.database_edit.setText(cfg.get("database", "EmrDaily"))
        auth = cfg.get("auth", "sql")
        self.auth_combo.setCurrentIndex(0 if auth == "sql" else 1)
        self.user_edit.setText(cfg.get("username", "sa"))
        self.pass_edit.setText(cfg.get("password", ""))
        self.timeout_spin.setValue(cfg.get("timeout", 10))
        self.company_edit.setText(cfg.get("company_code", ""))
        self.loss_spin.setValue(float(cfg.get("metal_loss_pct", DEFAULT_METAL_LOSS_PCT)))
        self._on_auth_changed(self.auth_combo.currentIndex())

    def _build_config(self) -> dict:
        auth = "sql" if self.auth_combo.currentIndex() == 0 else "windows"
        return {
            "server": self.server_edit.text().strip(),
            "database": self.database_edit.text().strip(),
            "auth": auth,
            "username": self.user_edit.text().strip(),
            "password": self.pass_edit.text(),
            "timeout": self.timeout_spin.value(),
            "company_code": self.company_edit.text().strip(),
            "metal_loss_pct": self.loss_spin.value(),
        }

    def _browse_databases(self):
        cfg = self._build_config()
        try:
            import pyodbc
            conn_str = build_connection_string({**cfg, "database": "master"})
            conn = pyodbc.connect(conn_str, timeout=5)
            rows = conn.cursor().execute(
                "SELECT name FROM sys.databases WHERE state_desc='ONLINE' ORDER BY name"
            ).fetchall()
            conn.close()
            names = [r[0] for r in rows]
        except Exception as e:
            self.test_label.setText(f"Browse failed: {e}")
            self.test_label.setStyleSheet("color: #e74c3c;")
            return
        current = self.database_edit.text().strip()
        start = names.index(current) if current in names else 0
        name, ok = QInputDialog.getItem(
            self, "Select Database", "Available databases:", names, start, editable=False
        )
        if ok and name:
            self.database_edit.setText(name)

    def _test(self):
        self.test_label.setText("Testing…")
        self.test_label.setStyleSheet("")
        self.repaint()
        cfg = self._build_config()
        ok, msg = db.test_connection(cfg)
        color = "#2ecc71" if ok else "#e74c3c"
        self.test_label.setText(msg)
        self.test_label.setStyleSheet(f"color: {color};")

    def _save_and_accept(self):
        cfg = self._build_config()
        save_config(cfg)
        self.accept()
