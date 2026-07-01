"""
Compares a parsed BOMDocument against Emperor master data.

Each ComparisonRow carries:
  section, code, description, template_value, master_value, diff_$, diff_%
  status: "match" | "minor" | "major" | "missing"

Metal comparison logic:
  RmRt.RrSalRt is the rate factor (e.g. 0.585 for G14 = 58.5% purity factor).
  master_rate_per_gram = RrSalRt * (BOM_LME_per_troy_oz / 31.1035)
  master_value = master_rate_per_gram * weight_grams
"""

from dataclasses import dataclass
from typing import Optional

from app.models.bom import BOMDocument
from app.core.db import DBConnection, TROY_OZ_TO_GRAM

MINOR_THRESHOLD = 5.0    # yellow
MAJOR_THRESHOLD = 15.0   # red
MIN_COMPARE_VALUE = 1.0  # lines below this $ value are always "match" (avoids float noise on $0 items)


@dataclass
class ComparisonRow:
    section: str
    code: str
    description: str
    template_value: float
    master_value: Optional[float]
    diff_dollar: float = 0.0
    diff_pct: float = 0.0
    status: str = "match"   # "match" | "minor" | "major" | "missing"


def _pct(template: float, master: float) -> float:
    if template == 0:
        return 0.0
    return ((master - template) / template) * 100.0


def _stone_lookup_dim(s) -> float:
    """
    Return the dimension key used in RmRt (RrFrLn/RrToLn) for this stone line.
    Emperor uses two different pointer conventions:
      - Large/solitaire stones: pointer_value in carats (col 6 in BOM > 0)
      - Small melee stones: second dimension from the L1*L2*L3 string (in mm)
    Source confirmed from OrdRm.OrLn2 cross-reference.
    """
    if s.pointer_value > 0:
        return round(s.pointer_value, 4)
    parts = s.dimension.replace(" ", "").split("*")
    if len(parts) >= 2:
        try:
            return round(float(parts[1]), 4)
        except (ValueError, IndexError):
            pass
    return 0.0


def _classify(diff_pct: float, master_value: Optional[float],
              template_value: float = 0.0) -> str:
    if master_value is None:
        return "missing"
    if abs(template_value) < MIN_COMPARE_VALUE and abs(master_value) < MIN_COMPARE_VALUE:
        return "match"
    abs_pct = abs(diff_pct)
    if abs_pct <= MINOR_THRESHOLD:
        return "match"
    elif abs_pct <= MAJOR_THRESHOLD:
        return "minor"
    return "major"


def compare(doc: BOMDocument, db: DBConnection,
            company_code: str = "") -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []

    if not db.is_connected():
        return rows

    # ---- Metals ----
    # RmRt.RrSalRt = rate factor; master $/g = factor × (LME / TROY_OZ_TO_GRAM)
    rm_codes = list({m.rm_code for m in doc.metals if m.rm_code})
    metal_factors = db.get_metal_rates(rm_codes, company_code)

    stone_rm_codes = list({s.rm_code for s in doc.stones if s.rm_code})
    all_rm_codes = list(set(rm_codes + stone_rm_codes))
    rm_descriptions = db.get_rm_descriptions(all_rm_codes)

    for m in doc.metals:
        factor = metal_factors.get(m.rm_code)
        master_val: Optional[float] = None
        if factor is not None and m.lme_rate > 0 and m.weight > 0:
            master_rate_per_gram = factor * (m.lme_rate / TROY_OZ_TO_GRAM)
            master_val = round(master_rate_per_gram * m.weight, 2)
        template_val = m.value
        diff = round((master_val or 0.0) - template_val, 2)
        pct = _pct(template_val, master_val or 0.0) if master_val is not None else 0.0
        desc = rm_descriptions.get(m.rm_code) or f"{m.category} {m.sub_category}".strip()
        rows.append(ComparisonRow(
            section="Metal",
            code=m.rm_code,
            description=desc,
            template_value=template_val,
            master_value=master_val,
            diff_dollar=diff,
            diff_pct=round(pct, 2),
            status=_classify(pct, master_val, template_val),
        ))

    # ---- Stones ----
    # Large stones use pointer_value (carats); small melee use L2 from dimension string (mm).
    stone_lookups = list({(s.rm_code, _stone_lookup_dim(s))
                          for s in doc.stones if s.rm_code})
    stone_prices = db.get_stone_prices(stone_lookups, company_code)

    for s in doc.stones:
        key = (s.rm_code, _stone_lookup_dim(s))
        master_price = stone_prices.get(key)
        template_val = s.value
        master_val: Optional[float] = None
        if master_price is not None and s.weight > 0:
            master_val = round(master_price * s.weight, 2)
        diff = round((master_val or 0.0) - template_val, 2)
        pct = _pct(template_val, master_val or 0.0) if master_val is not None else 0.0
        desc = rm_descriptions.get(s.rm_code) or f"{s.shape} {s.dimension}".strip()
        rows.append(ComparisonRow(
            section="Stone",
            code=s.rm_code or s.set_code,
            description=desc,
            template_value=template_val,
            master_value=master_val,
            diff_dollar=diff,
            diff_pct=round(pct, 2),
            status=_classify(pct, master_val, template_val),
        ))

    # ---- Labour (Setting) ----
    # LabRt: LrMCd=pointer, LrSCd=sub_code; LrSalRt = rate per piece (Q) or per gram (W)
    metal_weight = sum(m.weight for m in doc.metals)
    setting_pairs = list({(l.pointer, l.sub_code)
                          for l in doc.labour_setting if l.pointer})
    setting_rates = db.get_labour_rates(setting_pairs, company_code, weight=metal_weight)

    for l in doc.labour_setting:
        key = (l.pointer, l.sub_code)
        rate_tuple = setting_rates.get(key)
        template_val = l.value
        master_val: Optional[float] = None
        if rate_tuple is not None:
            master_rate, lr_qw = rate_tuple
            multiplier = metal_weight if lr_qw == "W" else l.qty
            if multiplier > 0:
                master_val = round(master_rate * multiplier, 2)
        diff = round((master_val or 0.0) - template_val, 2)
        pct = _pct(template_val, master_val or 0.0) if master_val is not None else 0.0
        rows.append(ComparisonRow(
            section="Labour (Setting)",
            code=f"{l.pointer}/{l.sub_code}",
            description=l.sub_code,
            template_value=template_val,
            master_value=master_val,
            diff_dollar=diff,
            diff_pct=round(pct, 2),
            status=_classify(pct, master_val, template_val),
        ))

    # ---- Labour (Others) ----
    other_pairs = list({(l.pointer, l.sub_code)
                        for l in doc.labour_others if l.pointer})
    other_rates = db.get_labour_rates(other_pairs, company_code, weight=metal_weight)

    for l in doc.labour_others:
        key = (l.pointer, l.sub_code)
        rate_tuple = other_rates.get(key)
        template_val = l.value
        master_val: Optional[float] = None
        if rate_tuple is not None:
            master_rate, lr_qw = rate_tuple
            multiplier = metal_weight if lr_qw == "W" else l.qty
            if multiplier > 0:
                master_val = round(master_rate * multiplier, 2)
        diff = round((master_val or 0.0) - template_val, 2)
        pct = _pct(template_val, master_val or 0.0) if master_val is not None else 0.0
        rows.append(ComparisonRow(
            section="Labour (Others)",
            code=f"{l.pointer}/{l.sub_code}",
            description=l.sub_code,
            template_value=template_val,
            master_value=master_val,
            diff_dollar=diff,
            diff_pct=round(pct, 2),
            status=_classify(pct, master_val, template_val),
        ))

    # ---- Findings ----
    finding_pairs = list({(f.pointer, f.sub_code)
                          for f in doc.findings if f.pointer})
    finding_rates = db.get_labour_rates(finding_pairs, company_code, weight=metal_weight)

    for f in doc.findings:
        key = (f.pointer, f.sub_code)
        rate_tuple = finding_rates.get(key)
        template_val = f.value
        master_val: Optional[float] = None
        if rate_tuple is not None:
            master_rate, lr_qw = rate_tuple
            multiplier = metal_weight if lr_qw == "W" else f.qty
            if multiplier > 0:
                master_val = round(master_rate * multiplier, 2)
        diff = round((master_val or 0.0) - template_val, 2)
        pct = _pct(template_val, master_val or 0.0) if master_val is not None else 0.0
        rows.append(ComparisonRow(
            section="Findings",
            code=f"{f.pointer}/{f.sub_code}",
            description=f.sub_code,
            template_value=template_val,
            master_value=master_val,
            diff_dollar=diff,
            diff_pct=round(pct, 2),
            status=_classify(pct, master_val, template_val),
        ))

    return rows


def summary_stats(rows: list[ComparisonRow]) -> dict:
    total_template = sum(r.template_value for r in rows)
    total_master = sum(r.master_value for r in rows if r.master_value is not None)
    total_diff = round(total_master - total_template, 2)
    total_pct = round(_pct(total_template, total_master), 2) if total_template else 0.0
    counts: dict[str, int] = {"match": 0, "minor": 0, "major": 0, "missing": 0}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {
        "total_template": round(total_template, 2),
        "total_master": round(total_master, 2),
        "total_diff": total_diff,
        "total_pct": total_pct,
        "counts": counts,
    }
