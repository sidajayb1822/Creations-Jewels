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
import re
import threading
from pathlib import Path
from typing import Optional

# SQL identifier whitelist for the generic custom-variable resolver: only
# letters, digits and underscore may appear in a table/column name, and only
# these comparison operators are allowed. Everything else is rejected before a
# query is built, so user-defined lookups carry no injection surface.
_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
_SAFE_OPS = {"=", "<=", ">=", "<", ">"}

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
    "query_timeout": 30,  # seconds a single query may run before it aborts
    "company_code": "",   # Emperor customer company code, e.g. "OM-LGD"
    "base_company_code": "",  # fallback rate chart when the customer has no entry, e.g. "ZSELF"
    "metal_loss_pct": 10.0,   # fallback when LossMst has no matching row
}

TROY_OZ_TO_GRAM = 31.1035

# Wastage/handling uplift applied on top of the fine metal rate. Emperor stores
# this in LossMst (keyed via CustMst.CmLkUpMetLs), but that table is empty in the
# EmrDaily restore and CmLkUpMetLs is blank for most customers, so this default
# stands in. 10% reproduces the CJE-QT-26-A-382 quotation to within 0.0003 $/g.
DEFAULT_METAL_LOSS_PCT = 10.0


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
        # The whole app shares ONE pyodbc connection, which is not safe for
        # concurrent cursors. Every query goes through this lock so overlapping
        # tab loads can't trigger "Connection is busy with results for another
        # command" or corrupt each other.
        self._lock = threading.RLock()

    def connect(self, config: Optional[dict] = None) -> None:
        if not PYODBC_AVAILABLE:
            raise RuntimeError("pyodbc is not installed.")
        cfg = config or load_config()
        self._config = cfg
        conn_str = build_connection_string(cfg)
        conn = pyodbc.connect(conn_str, autocommit=True)
        # Per-query timeout so a slow query aborts with an error instead of
        # hanging a tab forever.
        try:
            conn.timeout = int(cfg.get("query_timeout", 30))
        except Exception:
            pass
        self._conn = conn

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
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(sql, params)
                if cursor.description is None:
                    return []
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
            finally:
                cursor.close()

    # ------------------------------------------------------------------
    # Metal rates
    # RmRt: RrCd=metal_code, RrCmCd=company, RrTcTyp='RM', RrSalRt=factor
    # Actual rate per gram = RrSalRt * (LME_per_troy_oz / 31.1035)
    # For metals, RrFrLn/RrToLn are typically 0/9999 (any weight).
    # ------------------------------------------------------------------
    def get_metal_rates(self, rm_codes: list[str], company_code: str,
                        include_crp: bool = True) -> dict[str, float]:
        """
        Returns {rm_code: RrSalRt purity_factor}.
        Master rate per gram = purity_factor × (LME_per_troy_oz / 31.1035).
        Strategy:
          1. Try customer-specific RM-type rate (RrTcTyp='RM', RrCmCd=company_code)
          2. Fall back to CRP-type purity factor (applies to all customers uniformly)
        When include_crp=False, only step 1 is returned (customer-specific factors
        only) so callers can layer their own fallbacks (e.g. a base chart) between
        the customer rate and CRP.
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
        missing = [c for c in rm_codes if c not in result] if include_crp else []
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
    # Metal purity  (RmMst.RmPurityRt)
    # This is the authoritative purity factor per the client's costing
    # reference (CJ DB ref.xlsx) — G14 = 0.5833, i.e. 14/24. Prefer it over
    # the RmRt 'CRP' factor (0.585), which does not reproduce the quotation.
    # ------------------------------------------------------------------
    def get_metal_purity(self, rm_codes: list[str]) -> dict[str, float]:
        """Returns {rm_code: RmPurityRt}. Skips rows with no/zero purity."""
        if not rm_codes:
            return {}
        placeholders = ",".join("?" * len(rm_codes))
        result: dict[str, float] = {}
        try:
            rows = self._execute(
                f"SELECT RmCd, RmPurityRt FROM RmMst WHERE RmCd IN ({placeholders})",
                list(rm_codes),
            )
            for r in rows:
                purity = float(r["RmPurityRt"] or 0)
                if purity > 0:
                    result[r["RmCd"]] = purity
        except Exception:
            pass
        return result

    def get_crp_factor(self, rm_codes: list[str]) -> dict[str, float]:
        """
        Returns {rm_code: CRP purity factor} — the RmRt row with RrTcTyp='CRP'
        (e.g. G14 = 0.585). This is the universal fallback factor; exposed so it
        can be referenced explicitly in a formula.
        """
        if not rm_codes:
            return {}
        placeholders = ",".join("?" * len(rm_codes))
        result: dict[str, float] = {}
        try:
            rows = self._execute(
                f"SELECT RrCd, RrSalRt FROM RmRt "
                f"WHERE RrCd IN ({placeholders}) AND RrTcTyp = 'CRP'",
                list(rm_codes),
            )
            for r in rows:
                code = r["RrCd"]
                if code not in result:
                    result[code] = float(r["RrSalRt"] or 0)
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    # Metal loss %  (wastage uplift on the fine rate)
    # ------------------------------------------------------------------
    def get_metal_loss_pct(self, company_code: str) -> Optional[float]:
        """
        Returns the loss % for this customer, or None if Emperor has none
        configured (caller then falls back to the configured default).

        CustMst.CmLkUpMetLs names a loss group that should resolve into
        LossMst.LmLossPer. LossMst is empty in the EmrDaily restore and
        CmLkUpMetLs is blank for most customers, so the exact join column is
        UNVERIFIED — confirm with the client before relying on this path.
        """
        if not company_code:
            return None
        try:
            rows = self._execute(
                "SELECT CmLkUpMetLs FROM CustMst WHERE CmCd = ?", (company_code,)
            )
            if not rows:
                return None
            group = (rows[0].get("CmLkUpMetLs") or "").strip()
            if not group:
                return None
            loss = self._execute(
                "SELECT TOP 1 LmLossPer FROM LossMst "
                "WHERE LmCoCd = ? AND ISNULL(LmValidYn,'Y') <> 'N'",
                (group,),
            )
            if loss and loss[0]["LmLossPer"] is not None:
                return float(loss[0]["LmLossPer"])
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Customer multiplier  (CustMst.CmMulBy)
    # Applied to the TOTAL calculated price, not to individual lines.
    # ------------------------------------------------------------------
    def get_customer_multiplier(self, company_code: str) -> float:
        """Returns CmMulBy for the customer; 1.0 when absent or zero."""
        if not company_code:
            return 1.0
        try:
            rows = self._execute(
                "SELECT CmMulBy FROM CustMst WHERE CmCd = ?", (company_code,)
            )
            if rows and rows[0]["CmMulBy"]:
                return float(rows[0]["CmMulBy"])
        except Exception:
            pass
        return 1.0

    # ------------------------------------------------------------------
    # Stone rates
    # RmRt: RrCd=stone_code, RrCmCd=company, RrFrLn<=pointer<=RrToLn
    # RrSalRt = price per carat
    # ------------------------------------------------------------------
    def get_stone_prices(
        self,
        lookups: list[tuple[str, tuple]],   # [(rm_code, (pointer, L1, L2, L3)), ...]
        company_code: str,
    ) -> dict[tuple[str, tuple], float]:
        """
        Returns {(rm_code, candidates): RrSalRt_per_carat}.

        `candidates` is (pointer_carats, L1, L2, L3). A stone's rate table may be
        banded either by carat (large solitaires) or by millimetre size (melee /
        baguettes), and a small melee stone can carry BOTH a tiny carat value and
        an mm size — so we pick the dimension that actually lands in one of the
        stone's own rate bands:
          1. the carat pointer if it falls in a band (solitaire case), else
          2. the LARGEST millimetre dimension that falls in a band (melee case).
        Zeros in `candidates` are placeholders and are never matched.
        """
        if not lookups or not company_code:
            return {}
        result: dict[tuple[str, tuple], float] = {}
        for rm_code, candidates in lookups:
            if not rm_code:
                continue
            try:
                bands = self._execute(
                    "SELECT RrFrLn, RrToLn, RrSalRt FROM RmRt "
                    "WHERE RrCd = ? AND RrCmCd = ? AND RrTcTyp = 'RM'",
                    (rm_code, company_code),
                )
            except Exception:
                continue
            if not bands:
                continue

            def _rate_for(dim: float):
                """Rate of the tightest band containing dim, or None."""
                if not dim or dim <= 0:
                    return None
                best, best_span = None, None
                for b in bands:
                    fr, to = float(b["RrFrLn"] or 0), float(b["RrToLn"] or 0)
                    if fr <= dim <= to:
                        span = to - fr
                        if best_span is None or span < best_span:
                            best, best_span = float(b["RrSalRt"] or 0), span
                return best

            pointer = candidates[0] if candidates else 0.0
            mm_dims = sorted((d for d in candidates[1:] if d and d > 0), reverse=True)

            rate = _rate_for(pointer)          # carat pointer first
            if rate is None:
                for dim in mm_dims:            # else largest mm dim in a band
                    rate = _rate_for(dim)
                    if rate is not None:
                        break
            if rate is not None:
                result[(rm_code, candidates)] = rate
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
    ) -> dict[tuple[str, str], tuple[float, str, float]]:
        """
        Returns {(main_code, sub_code): (LrSalRt, LrQw, LrSalMin)}.
        LrQw='Q' → rate per piece; LrQw='W' → rate per gram of metal.
        LrSalMin = minimum charge for this labour (0 when not set); Emperor
        bills max(rate × basis, LrSalMin).
        Pass piece weight so the correct tier row is selected.
        """
        if not pairs or not company_code:
            return {}
        result: dict[tuple[str, str], tuple[float, str, float]] = {}
        for main_code, sub_code in pairs:
            if not main_code:
                continue
            # Pick the weight band that CONTAINS the piece weight. This applies
            # to per-piece ('Q') rows too — many CFP/RNG-style rates are tiered
            # by weight even when charged per piece, so we must NOT bypass the
            # band filter for 'Q' (the old code did, and always returned the
            # lowest tier). Ordering:
            #   1) bands containing the weight sort first;
            #   2) among containing bands, the tightest (smallest LrToWt) wins;
            #      among non-containing bands (weight heavier than every band)
            #      the largest band wins, so an overweight piece falls back to
            #      the top tier instead of returning nothing.
            # Flat rows (a single 0-99 / 0-9999 band) match and are unaffected.
            sql = """
                SELECT TOP 1 LrSalRt, LrQw, LrSalMin
                FROM LabRt
                WHERE LrMCd = ?
                  AND LrSCd = ?
                  AND LrCmCd = ?
                ORDER BY
                  CASE WHEN LrFrWt <= ? AND LrToWt >= ? THEN 0 ELSE 1 END,
                  CASE WHEN LrFrWt <= ? AND LrToWt >= ? THEN LrToWt
                       ELSE (1000000 - LrToWt) END
            """
            try:
                rows = self._execute(sql, (main_code, sub_code, company_code,
                                           weight, weight, weight, weight))
                if rows:
                    result[(main_code, sub_code)] = (
                        float(rows[0]["LrSalRt"] or 0),
                        (rows[0]["LrQw"] or "Q").strip(),
                        float(rows[0]["LrSalMin"] or 0),
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
        """
        Match a BOM customer name to a CustMst code, preferring the most precise
        match so a decorated lookalike can't win by accident:
          1. exact name (case-insensitive) — e.g. "OM JEWELRY INC" → OMJEWLRY,
             not "OM JEWELRY INC (LGD)" (OM-LGD);
          2. else "starts with", shortest (closest) name first;
          3. else "contains", shortest name first (last-resort, = old behaviour).
        """
        name = (customer_name or "").strip()
        if not name:
            return ""
        try:
            for sql, param in (
                ("SELECT TOP 1 CmCd FROM CustMst WHERE CmName = ? ORDER BY LEN(CmName)",
                 name),
                ("SELECT TOP 1 CmCd FROM CustMst WHERE CmName LIKE ? ORDER BY LEN(CmName)",
                 name + "%"),
                ("SELECT TOP 1 CmCd FROM CustMst WHERE CmName LIKE ? ORDER BY LEN(CmName)",
                 f"%{name[:20]}%"),
            ):
                rows = self._execute(sql, (param,))
                if rows:
                    return rows[0]["CmCd"]
            return ""
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
            # Undelivered orders carry the 1980-01-01 sentinel delivery date.
            # Use a sargable range (no CONVERT on every row) so this can use an
            # index instead of scanning + converting the whole table.
            conditions.append("o.OmDelDt < '1980-01-02'")

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
    # Generic custom-variable resolver
    # Powers user-defined variables (app.core.custom_var) against ANY table.
    # Identifiers are strictly whitelisted (letters/digits/underscore only) and
    # bracket-quoted; only values are parameterised — so a new master can be
    # wired from the UI with no SQL-injection surface.
    # ------------------------------------------------------------------
    def resolve_custom_value(
        self,
        table: str,
        value_column: str,
        aggregate: str,
        conditions: list[tuple[str, str, object]],
    ) -> Optional[float]:
        if not (_IDENT_RE.match(table or "") and _IDENT_RE.match(value_column or "")):
            return None
        agg = (aggregate or "TOP1").upper()
        where_parts: list[str] = []
        params: list = []
        for col, op, val in conditions:
            if not _IDENT_RE.match(col or "") or op not in _SAFE_OPS:
                return None
            where_parts.append(f"[{col}] {op} ?")
            params.append(val)
        where = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
        if agg == "TOP1":
            sql = f"SELECT TOP 1 [{value_column}] AS v FROM [{table}]{where}"
        elif agg in ("MIN", "MAX", "SUM", "AVG"):
            sql = f"SELECT {agg}([{value_column}]) AS v FROM [{table}]{where}"
        else:
            return None
        try:
            rows = self._execute(sql, params)
            if rows and rows[0]["v"] is not None:
                return float(rows[0]["v"])
        except Exception:
            pass
        return None

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
