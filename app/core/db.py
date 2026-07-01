"""
SQL Server connection manager for Emperor ERP database.

Real table/column names verified against EmrDaily (restored 2026-06):
  RmRt   = Raw Material Rate (RrCd, RrCmCd, RrTcTyp, RrFrLn, RrToLn, RrSalRt)
  LabRt  = Labour Rate (LrMCd, LrSCd, LrCmCd, LrSalRt, LrQw, LrFrWt, LrToWt)
  RmMst  = Raw Material Master (RmCd, RmCtg, RmSCtg, RmDesc)
  CustMst = Customer Master (CmCd, CmName)

Config stored at ~/.emr_reporter/config.json.
"""

import json
from pathlib import Path
from typing import Optional

try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False


CONFIG_PATH = Path.home() / ".emr_reporter" / "config.json"

DEFAULT_CONFIG = {
    "server": r".\EMRSQL",
    "database": "EmrDaily",
    "auth": "sql",
    "username": "sa",
    "password": "",
    "timeout": 10,
    "company_code": "",   # Emperor customer company code, e.g. "OM-LGD"
}

TROY_OZ_TO_GRAM = 31.1035


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
                saved = json.load(f)
            config = DEFAULT_CONFIG.copy()
            config.update(saved)
            return config
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def build_connection_string(config: dict) -> str:
    if not PYODBC_AVAILABLE:
        raise RuntimeError("pyodbc is not installed.")
    available = [d for d in pyodbc.drivers() if "SQL Server" in d]
    driver = "{SQL Server}"
    for pref in ["ODBC Driver 17 for SQL Server",
                 "ODBC Driver 18 for SQL Server",
                 "SQL Server"]:
        if pref in available:
            driver = "{" + pref + "}"
            break

    base = (
        f"DRIVER={driver};"
        f"SERVER={config['server']};"
        f"DATABASE={config['database']};"
        f"Connection Timeout={config.get('timeout', 10)};"
    )
    if config.get("auth") == "windows":
        return base + "Trusted_Connection=yes;"
    return base + f"UID={config['username']};PWD={config['password']};"


class DBConnection:
    def __init__(self):
        self._conn: Optional[object] = None
        self._config: dict = {}

    def connect(self, config: Optional[dict] = None) -> None:
        if not PYODBC_AVAILABLE:
            raise RuntimeError("pyodbc is not installed.")
        cfg = config or load_config()
        self._config = cfg
        conn_str = build_connection_string(cfg)
        self._conn = pyodbc.connect(conn_str, autocommit=True)

    def test_connection(self, config: dict) -> tuple[bool, str]:
        if not PYODBC_AVAILABLE:
            return False, "pyodbc not installed."
        try:
            conn_str = build_connection_string(config)
            conn = pyodbc.connect(conn_str, timeout=5)
            cursor = conn.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()[0].split("\n")[0]
            conn.close()
            return True, f"Connected: {version}"
        except Exception as e:
            return False, str(e)

    def is_connected(self) -> bool:
        return self._conn is not None

    def disconnect(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _execute(self, sql: str, params=()) -> list[dict]:
        if not self._conn:
            raise RuntimeError("Not connected to database.")
        cursor = self._conn.cursor()
        cursor.execute(sql, params)
        if cursor.description is None:
            return []
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Metal rates
    # RmRt: RrCd=metal_code, RrCmCd=company, RrTcTyp='RM', RrSalRt=factor
    # Actual rate per gram = RrSalRt * (LME_per_troy_oz / 31.1035)
    # For metals, RrFrLn/RrToLn are typically 0/9999 (any weight).
    # ------------------------------------------------------------------
    def get_metal_rates(self, rm_codes: list[str], company_code: str) -> dict[str, float]:
        """
        Returns {rm_code: RrSalRt purity_factor}.
        Master rate per gram = purity_factor × (LME_per_troy_oz / 31.1035).
        Strategy:
          1. Try customer-specific RM-type rate (RrTcTyp='RM', RrCmCd=company_code)
          2. Fall back to CRP-type purity factor (applies to all customers uniformly)
        """
        if not rm_codes:
            return {}
        placeholders = ",".join("?" * len(rm_codes))
        result: dict[str, float] = {}

        if company_code:
            sql = f"""
                SELECT RrCd, RrSalRt FROM RmRt
                WHERE RrCd IN ({placeholders}) AND RrCmCd = ? AND RrTcTyp = 'RM'
                ORDER BY RrToLn DESC
            """
            try:
                for r in self._execute(sql, list(rm_codes) + [company_code]):
                    code = r["RrCd"]
                    if code not in result:
                        result[code] = float(r["RrSalRt"] or 0)
            except Exception:
                pass

        # Fall back to CRP (standard purity factor) for any codes still missing
        missing = [c for c in rm_codes if c not in result]
        if missing:
            placeholders2 = ",".join("?" * len(missing))
            sql2 = f"""
                SELECT TOP 1 RrCd, RrSalRt FROM RmRt
                WHERE RrCd IN ({placeholders2}) AND RrTcTyp = 'CRP'
                ORDER BY RrCd
            """
            try:
                for r in self._execute(sql2, missing):
                    code = r["RrCd"]
                    if code not in result:
                        result[code] = float(r["RrSalRt"] or 0)
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------
    # Stone rates
    # RmRt: RrCd=stone_code, RrCmCd=company, RrFrLn<=pointer<=RrToLn
    # RrSalRt = price per carat
    # ------------------------------------------------------------------
    def get_stone_prices(
        self,
        lookups: list[tuple[str, float]],   # [(rm_code, pointer_value), ...]
        company_code: str,
    ) -> dict[tuple[str, float], float]:
        """
        Returns {(rm_code, pointer_value): RrSalRt_per_carat}.
        Uses RrFrLn <= pointer_value <= RrToLn for range-based pricing.
        """
        if not lookups or not company_code:
            return {}
        result: dict[tuple[str, float], float] = {}
        for rm_code, pointer_val in lookups:
            if not rm_code:
                continue
            sql = """
                SELECT TOP 1 RrSalRt
                FROM RmRt
                WHERE RrCd = ?
                  AND RrCmCd = ?
                  AND RrTcTyp = 'RM'
                  AND RrFrLn <= ?
                  AND RrToLn >= ?
                ORDER BY ABS(RrToLn - ?) ASC
            """
            try:
                rows = self._execute(sql, (rm_code, company_code,
                                           pointer_val, pointer_val, pointer_val))
                if rows:
                    result[(rm_code, pointer_val)] = float(rows[0]["RrSalRt"] or 0)
            except Exception:
                pass
        return result

    # ------------------------------------------------------------------
    # Labour rates
    # LabRt: LrMCd=main_code, LrSCd=sub_code, LrCmCd=company, LrSalRt=rate
    # LrQw: Q=qty-based, W=weight-based
    # LrFrWt/LrToWt: weight range (for weight-based labour tiers)
    # ------------------------------------------------------------------
    def get_labour_rates(
        self,
        pairs: list[tuple[str, str]],   # [(main_code, sub_code), ...]
        company_code: str,
        weight: float = 0.0,
    ) -> dict[tuple[str, str], tuple[float, str]]:
        """
        Returns {(main_code, sub_code): (LrSalRt, LrQw)}.
        LrQw='Q' → rate per piece; LrQw='W' → rate per gram of metal.
        Pass piece weight so the correct tier row is selected.
        """
        if not pairs or not company_code:
            return {}
        result: dict[tuple[str, str], tuple[float, str]] = {}
        for main_code, sub_code in pairs:
            if not main_code:
                continue
            sql = """
                SELECT TOP 1 LrSalRt, LrQw
                FROM LabRt
                WHERE LrMCd = ?
                  AND LrSCd = ?
                  AND LrCmCd = ?
                  AND (LrQw = 'Q' OR (LrFrWt <= ? AND LrToWt >= ?))
                ORDER BY LrToWt ASC
            """
            try:
                rows = self._execute(sql, (main_code, sub_code, company_code,
                                           weight, weight))
                if rows:
                    result[(main_code, sub_code)] = (
                        float(rows[0]["LrSalRt"] or 0),
                        (rows[0]["LrQw"] or "Q").strip(),
                    )
            except Exception:
                pass
        return result

    # ------------------------------------------------------------------
    # RM descriptions (RmMst.RmDesc)
    # ------------------------------------------------------------------
    def get_rm_descriptions(self, rm_codes: list[str]) -> dict[str, str]:
        """Returns {rm_code: RmDesc} for the given codes."""
        if not rm_codes:
            return {}
        placeholders = ",".join("?" * len(rm_codes))
        result: dict[str, str] = {}
        try:
            rows = self._execute(
                f"SELECT RmCd, RmDesc FROM RmMst WHERE RmCd IN ({placeholders})",
                list(rm_codes),
            )
            for r in rows:
                result[r["RmCd"]] = (r.get("RmDesc") or "").strip()
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    # Customer lookup
    # ------------------------------------------------------------------
    def get_customers(self) -> list[tuple[str, str]]:
        """Returns [(CmCd, CmName)] sorted by code."""
        try:
            rows = self._execute(
                "SELECT CmCd, CmName FROM CustMst WHERE CmValidYN='Y' ORDER BY CmCd"
            )
            return [(r["CmCd"], r.get("CmName", r["CmCd"])) for r in rows]
        except Exception:
            return []

    def find_company_code(self, customer_name: str) -> str:
        """Try to match BOM customer name to a CustMst entry."""
        if not customer_name:
            return ""
        try:
            rows = self._execute(
                "SELECT TOP 1 CmCd FROM CustMst WHERE CmName LIKE ?",
                (f"%{customer_name.strip()[:20]}%",)
            )
            return rows[0]["CmCd"] if rows else ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Customer Rate Card
    # ------------------------------------------------------------------
    def get_all_material_rates(self, company_code: str) -> list[dict]:
        """All RmRt rows for a customer with description join from RmMst."""
        try:
            rows = self._execute(
                """
                SELECT r.RrCd,
                       ISNULL(m.RmDesc, '') AS RmDesc,
                       ISNULL(m.RmCtg, '')  AS RmCtg,
                       r.RrTcTyp,
                       r.RrFrLn, r.RrToLn, r.RrSalRt
                FROM RmRt r
                LEFT JOIN RmMst m ON m.RmCd = r.RrCd
                WHERE r.RrCmCd = ?
                ORDER BY ISNULL(m.RmCtg,''), r.RrCd, r.RrFrLn
                """,
                (company_code,),
            )
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_all_labour_rates(self, company_code: str) -> list[dict]:
        """All LabRt rows for a customer."""
        try:
            rows = self._execute(
                """
                SELECT LrMCd, LrSCd, LrSalRt, LrQw, LrFrWt, LrToWt
                FROM LabRt
                WHERE LrCmCd = ?
                ORDER BY LrMCd, LrSCd, LrFrWt
                """,
                (company_code,),
            )
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Order Pipeline
    # ------------------------------------------------------------------
    def get_order_pipeline(
        self,
        customer_filter: str = "",
        tc_types: list | None = None,
        show_delivered: bool = False,
    ) -> list[dict]:
        """Returns up to 500 recent orders from OrdMst."""
        conditions: list[str] = []
        params: list = []

        if tc_types:
            placeholders = ",".join("?" * len(tc_types))
            conditions.append(f"o.OmTc IN ({placeholders})")
            params.extend(tc_types)

        if customer_filter:
            conditions.append("(c.CmName LIKE ? OR o.OmCmCd LIKE ?)")
            params.extend([f"%{customer_filter}%", f"%{customer_filter}%"])

        if not show_delivered:
            conditions.append("CONVERT(date, o.OmDelDt) = '1980-01-01'")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        sql = f"""
            SELECT TOP 500
                o.OmTc, o.OmYy, o.OmChr, o.OmNo,
                o.OmCmCd,
                ISNULL(c.CmName, o.OmCmCd) AS CmName,
                o.OmDt, o.OmExpDelDt, o.OmDelDt,
                ISNULL(o.OmPoNo, '')        AS OmPoNo,
                ISNULL(o.OmLmgSal, 0)       AS SaleVal,
                o.OmCoCd
            FROM OrdMst o
            LEFT JOIN CustMst c ON c.CmCd = o.OmCmCd
            {where}
            ORDER BY o.OmDt DESC
        """
        try:
            rows = self._execute(sql, params)
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Schema discovery helpers
    # ------------------------------------------------------------------
    def list_tables(self) -> list[str]:
        rows = self._execute(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
        )
        return [r["TABLE_NAME"] for r in rows]

    def list_columns(self, table: str) -> list[dict]:
        return self._execute(
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION",
            (table,)
        )


# Module-level singleton
db = DBConnection()
