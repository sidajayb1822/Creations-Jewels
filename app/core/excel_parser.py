"""
Parses Emperor Software BOM quotation Excel templates.

Exact column layouts (verified against CJE-QT-26-A-382.xlsx):

METALS (section header "METAL", data header row +1):
  Col: 1=Sr  2=Ctg  3=SubCtg  4=RmCode  5=Qty  6=Weight  7=Q/W  8=LME  9=Rate  10=Value

STONES (section header "STONES", data header row +1):
  Col: 1=Sr  2=Ctg(D/C)  3=SubCtg(shape)  4=RmCode  5=Dimension  6=Pointer
       7=Qty  8=Weight  9=Q/W  10=Rate  11=Value  12=SetCode  13=SetRate  14=SetValue

LABOR EXCEPT SETTING (section header "LABOR (EXCEPT"):
  Col: 1=Sr  2=MainCode  3=SubCode  4=Q/W  5=Qty  6=Rate  7=Value

LABOR OTHERS (section header "LABOR(OTHERS)"):
  Same column layout as above.

Section boundaries: detected by keyword in col 1, data starts at header_row+2.
"""

import os
from typing import Any, Optional
import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from app.models.bom import (
    BOMDocument, BOMHeader, BOMSummary,
    MetalLine, StoneLine, LabourLine, FindingLine,
)


def _val(cell) -> Any:
    v = cell.value
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip()
    return v


def _float(cell) -> float:
    v = _val(cell)
    if v is None or v == "" or v == "-":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _str(cell) -> str:
    v = _val(cell)
    return "" if v is None else str(v)


def _find_section_row(ws: Worksheet, keyword: str, max_row: int = 120) -> Optional[int]:
    """Return the row where col-1 starts with or contains keyword (case-insensitive)."""
    kw = keyword.upper().strip()
    for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=1):
        cell = row[0]
        v = cell.value
        if v and kw in str(v).upper():
            return cell.row
    return None


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

def _parse_header(ws: Worksheet) -> BOMHeader:
    h = BOMHeader()

    def scan_for_label(label: str):
        label_up = label.upper()
        for r in range(1, 20):
            for c in range(1, 20):
                cell = ws.cell(row=r, column=c)
                v = _val(cell)
                if v and label_up in str(v).upper():
                    for offset in range(1, 6):
                        nv = _val(ws.cell(row=r, column=c + offset))
                        if nv is not None and str(nv).strip() not in ("", "-"):
                            return nv
        return ""

    h.customer = str(scan_for_label("Cust Name") or scan_for_label("Customer") or "")
    h.order_no = str(scan_for_label("Order No") or scan_for_label("Order") or "")
    h.design_code = str(scan_for_label("Design Code") or scan_for_label("Design") or "")
    h.suffix = str(scan_for_label("Suffix") or "")
    h.size = str(scan_for_label("Size") or "")
    h.po_reference = str(scan_for_label("PO Ref") or scan_for_label("PO Reference") or "")

    qty_v = scan_for_label("Quantity") or scan_for_label("Qty")
    try:
        h.quantity = float(qty_v) if qty_v else 0.0
    except (TypeError, ValueError):
        h.quantity = 0.0

    return h


# ---------------------------------------------------------------------------
# Metals  —  col: 1=Sr 2=Ctg 3=SubCtg 4=RmCode 5=Qty 6=Wt 7=QW 8=LME 9=Rate 10=Val
# ---------------------------------------------------------------------------

def _parse_metals(ws: Worksheet) -> list[MetalLine]:
    lines = []
    section_row = _find_section_row(ws, "METAL")
    if section_row is None:
        return lines
    data_start = section_row + 2   # skip header keyword row + column-header row

    for r in range(data_start, data_start + 20):
        sr_val = _val(ws.cell(row=r, column=1))
        if sr_val is None or str(sr_val).strip() in ("", "Sr"):
            continue
        try:
            sr = int(sr_val)
        except (TypeError, ValueError):
            break

        line = MetalLine(
            sr=sr,
            category=_str(ws.cell(row=r, column=2)),
            sub_category=_str(ws.cell(row=r, column=3)),
            rm_code=_str(ws.cell(row=r, column=4)),
            qty=_float(ws.cell(row=r, column=5)),
            weight=_float(ws.cell(row=r, column=6)),
            calc_mode=_str(ws.cell(row=r, column=7)) or "W",
            lme_rate=_float(ws.cell(row=r, column=8)),
            rate=_float(ws.cell(row=r, column=9)),
            value=_float(ws.cell(row=r, column=10)),
        )
        if line.rm_code:
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Stones  —  col: 1=Sr 2=Ctg 3=Shape 4=RmCode 5=Dim 6=Ptr 7=Qty 8=Wt
#                  9=QW 10=Rate 11=Val 12=SetCode 13=SetRate 14=SetVal
# ---------------------------------------------------------------------------

def _parse_stones(ws: Worksheet) -> list[StoneLine]:
    lines = []
    section_row = _find_section_row(ws, "STONES")
    if section_row is None:
        return lines
    data_start = section_row + 2

    for r in range(data_start, data_start + 30):
        sr_val = _val(ws.cell(row=r, column=1))
        if sr_val is None or str(sr_val).strip() in ("", "Sr"):
            continue
        try:
            sr = int(sr_val)
        except (TypeError, ValueError):
            break

        line = StoneLine(
            sr=sr,
            shape=_str(ws.cell(row=r, column=3)),           # Sub Ctg = OVL / TAP / etc.
            rm_code=_str(ws.cell(row=r, column=4)),         # RM Code = stone lookup code
            set_code=_str(ws.cell(row=r, column=12)),       # Setting code
            description=_str(ws.cell(row=r, column=2)),     # Category D/C
            qty=_float(ws.cell(row=r, column=7)),
            dimension=_str(ws.cell(row=r, column=5)),       # "2.5 PTR" / "8x6" etc.
            pointer_value=_float(ws.cell(row=r, column=6)), # per-stone pointer size
            weight=_float(ws.cell(row=r, column=8)),        # total carat weight
            price=_float(ws.cell(row=r, column=10)),        # rate per carat from BOM
            value=_float(ws.cell(row=r, column=11)),
            sub_code=_str(ws.cell(row=r, column=3)),
            rate_each=_float(ws.cell(row=r, column=13)),    # setting rate per stone
            setting_total=_float(ws.cell(row=r, column=14)),
        )
        if line.rm_code or line.shape:
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Labour  —  col: 1=Sr 2=MainCode 3=SubCode 4=QW 5=Qty 6=Rate 7=Value
# ---------------------------------------------------------------------------

def _parse_labour(ws: Worksheet, keyword: str, section_label: str) -> list[LabourLine]:
    lines = []
    section_row = _find_section_row(ws, keyword)
    if section_row is None:
        return lines
    data_start = section_row + 2

    for r in range(data_start, data_start + 20):
        sr_val = _val(ws.cell(row=r, column=1))
        if sr_val is None or str(sr_val).strip() in ("", "Sr"):
            continue
        try:
            sr = int(sr_val)
        except (TypeError, ValueError):
            break

        line = LabourLine(
            sr=sr,
            section=section_label,
            pointer=_str(ws.cell(row=r, column=2)),         # Main Code
            set_code=_str(ws.cell(row=r, column=3)),        # Sub Code
            description=_str(ws.cell(row=r, column=2)),
            sub_code=_str(ws.cell(row=r, column=3)),
            qty=_float(ws.cell(row=r, column=5)),
            rate=_float(ws.cell(row=r, column=6)),
            value=_float(ws.cell(row=r, column=7)),
        )
        if line.pointer:
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Findings — not a separate section in all templates; omitted when absent
# ---------------------------------------------------------------------------

def _parse_findings(ws: Worksheet) -> list[FindingLine]:
    # Emperor BOM may embed findings inside labour sections or omit them.
    # Return empty list if no "FINDING" header found.
    section_row = _find_section_row(ws, "FINDING")
    if section_row is None:
        return []

    lines = []
    data_start = section_row + 2
    for r in range(data_start, data_start + 20):
        sr_val = _val(ws.cell(row=r, column=1))
        if sr_val is None or str(sr_val).strip() in ("", "Sr"):
            continue
        try:
            sr = int(sr_val)
        except (TypeError, ValueError):
            break
        line = FindingLine(
            sr=sr,
            pointer=_str(ws.cell(row=r, column=2)),
            set_code=_str(ws.cell(row=r, column=3)),
            description=_str(ws.cell(row=r, column=2)),
            sub_code=_str(ws.cell(row=r, column=3)),
            qty=_float(ws.cell(row=r, column=5)),
            rate=_float(ws.cell(row=r, column=6)),
            value=_float(ws.cell(row=r, column=7)),
        )
        if line.pointer:
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Summary — read from the SUMMARY block; fall back to summing lines
# ---------------------------------------------------------------------------

def _parse_summary(ws: Worksheet,
                   metals: list[MetalLine],
                   stones: list[StoneLine],
                   labour_setting: list[LabourLine],
                   labour_others: list[LabourLine],
                   findings: list[FindingLine]) -> BOMSummary:
    s = BOMSummary()

    summary_row = _find_section_row(ws, "SUMMARY")
    if summary_row:
        # Total is in col 10, a few rows below the SUMMARY header
        for r in range(summary_row, summary_row + 15):
            v = _float(ws.cell(row=r, column=10))
            if v > 0:
                s.total_value = v
                break

    s.metal_weight = sum(m.weight for m in metals)
    s.metal_value = sum(m.value for m in metals)
    s.stone_qty = sum(st.qty for st in stones)
    s.stone_weight = sum(_float_or_zero(st) for st in stones)
    s.stone_value = sum(st.value for st in stones)
    s.labour_setting_value = sum(l.value for l in labour_setting)
    s.labour_other_value = sum(l.value for l in labour_others)
    s.findings_value = sum(f.value for f in findings)

    if s.total_value == 0.0:
        s.total_value = (s.metal_value + s.stone_value +
                         s.labour_setting_value + s.labour_other_value +
                         s.findings_value)
    return s


def _float_or_zero(stone) -> float:
    try:
        return float(stone.qty) * 0  # placeholder — weight is on the stone object
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_bom(file_path: str) -> BOMDocument:
    """Parse an Emperor BOM Excel file and return a BOMDocument."""
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    header = _parse_header(ws)
    metals = _parse_metals(ws)
    stones = _parse_stones(ws)
    labour_setting = _parse_labour(ws, "LABOR (EXCEPT", "setting")
    labour_others = _parse_labour(ws, "LABOR(OTHERS)", "others")
    findings = _parse_findings(ws)
    summary = _parse_summary(ws, metals, stones, labour_setting, labour_others, findings)

    return BOMDocument(
        header=header,
        metals=metals,
        stones=stones,
        labour_setting=labour_setting,
        labour_others=labour_others,
        findings=findings,
        summary=summary,
        source_file=os.path.basename(file_path),
    )
