"""
Compares a parsed BOMDocument against Emperor master data.

Pricing is **formula-driven**: every line resolves a FormulaDef for its
component (metal, diamond, colour_stone, finding, labour_q, labour_w, cdw) and
customer via app.core.formula_store, then evaluates it against a per-line
variable context built from the BOM line + DB lookups + settings.

The built-in default formulas reproduce the previously hard-coded math exactly:
  metal        (LME / 31.1035) × RmMst.RmPurityRt × (1 + loss%) × weight
  diamond/CS   RmRt rate/ct × carat weight
  labour_q     LabRt rate × qty        labour_w  LabRt rate × total metal wt
  cdw          LabRt rate × total diamond wt      finding  LabRt rate (direct)

Each ComparisonRow carries the resolved value AND a TraceStep breakdown so the
UI can show (and let the user edit) exactly how the number was produced.

A line is "missing" (no master value) when its required DB lookup does not
resolve or its formula fails to evaluate — never a crash.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.models.bom import BOMDocument
from app.core.db import DBConnection, DEFAULT_METAL_LOSS_PCT
from app.core.formula import evaluate, FormulaError, TraceStep
from app.core.formula_store import formula_store
from app.core.custom_var import custom_var_store

MINOR_THRESHOLD = 5.0    # yellow
MAJOR_THRESHOLD = 15.0   # red
MIN_COMPARE_VALUE = 1.0  # lines below this $ value are always "match" (avoids float noise on $0 items)

# Labour heads charged per carat of diamond rather than per gram of metal.
# Reference: "CDW = D weight x Lbr Rate".
DIAMOND_WEIGHT_LABOUR_CODES = {"CDW"}


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
    component: str = ""     # formula component key (metal, diamond, labour_q, …)
    customer_code: str = ""  # company code the formula was resolved for
    trace: list[TraceStep] = field(default_factory=list)
    source_note: str = ""    # e.g. "base chart" when the rate came from the fallback chart


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


def _stone_candidates(s) -> tuple:
    """
    Ordered, hashable set of candidate lookup dimensions for a stone's rate
    lookup: (pointer_carats, L1, L2, L3). The DB matcher tries the carat pointer
    first (correct for large solitaires, whose bands are in carats) and otherwise
    the largest millimetre dimension that lands in a band (correct for melee /
    baguettes, whose bands are in mm even when the stone also carries a tiny carat
    value). Zeros are placeholders and are ignored by the matcher.
    """
    pointer = round(s.pointer_value, 4) if s.pointer_value and s.pointer_value > 0 else 0.0
    dims = []
    for part in s.dimension.replace(" ", "").split("*"):
        try:
            dims.append(round(float(part), 4))
        except (ValueError, IndexError):
            dims.append(0.0)
    dims = (dims + [0.0, 0.0, 0.0])[:3]   # pad to L1, L2, L3
    return (pointer, dims[0], dims[1], dims[2])


def _labour_component(main_code: str, lr_qw: str) -> str:
    """Route a labour line to the formula component that matches its rate basis."""
    if lr_qw == "W":
        if main_code.strip().upper() in DIAMOND_WEIGHT_LABOUR_CODES:
            return "cdw"
        return "labour_w"
    return "labour_q"


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


def _inject_custom_vars(ctx: dict, db: DBConnection, field_map: dict) -> None:
    """
    Resolve every enabled custom variable for this line and add it to ctx.
    A variable is skipped for a line when one of its match sources isn't
    available (e.g. a set_code lookup on a metal line) — so a formula that
    references it there simply evaluates to "missing", never an error.
    """
    for cv in custom_var_store.list_all():
        if not cv.enabled or not cv.table or not cv.value_column:
            continue
        conditions = []
        ok = True
        for mk in cv.match_keys:
            if mk.source == "literal":
                val: object = mk.literal
                try:
                    val = float(mk.literal)
                except (TypeError, ValueError):
                    pass
            else:
                if mk.source not in field_map:
                    ok = False
                    break
                val = field_map[mk.source]
                if val is None or val == "":
                    ok = False
                    break
            conditions.append((mk.column, mk.op, val))
        if not ok:
            continue
        value = db.resolve_custom_value(cv.table, cv.value_column,
                                        cv.aggregate, conditions)
        if value is not None:
            ctx[cv.name] = value


def _eval_component(component: str, company_code: str,
                    ctx: dict) -> tuple[Optional[float], list[TraceStep]]:
    """
    Resolve and evaluate the formula for (component, company_code) against ctx.
    Returns (rounded_value, trace), or (None, []) when the formula is disabled,
    missing, or references a value not present in ctx (fail-safe → "missing").
    """
    fd = formula_store.get(component, company_code)
    if fd is None or not fd.enabled or not fd.expression.strip():
        return None, []
    try:
        value, trace = evaluate(fd.expression, ctx)
    except FormulaError:
        return None, []
    return round(value, 2), trace


def _row(section: str, code: str, description: str, template_val: float,
         master_val: Optional[float], component: str, company_code: str,
         trace: list[TraceStep], source_note: str = "") -> ComparisonRow:
    diff = round((master_val or 0.0) - template_val, 2)
    pct = _pct(template_val, master_val or 0.0) if master_val is not None else 0.0
    return ComparisonRow(
        section=section,
        code=code,
        description=description,
        template_value=template_val,
        master_value=master_val,
        diff_dollar=diff,
        diff_pct=round(pct, 2),
        status=_classify(pct, master_val, template_val),
        component=component,
        customer_code=company_code,
        trace=trace,
        source_note=source_note,
    )


def _fill_from_base(primary: dict, lookup_fn, keys: list,
                    base_company_code: str) -> tuple[dict, set]:
    """
    For every key not resolved in `primary`, look it up under the base chart via
    lookup_fn(missing_keys, base_company_code) and merge the results in. Returns
    (merged_dict, base_sourced_keys). No-op (empty base set) when there is no
    base code or nothing is missing.
    """
    if not base_company_code:
        return primary, set()
    missing = [k for k in keys if k not in primary]
    if not missing:
        return primary, set()
    base_hits = lookup_fn(missing, base_company_code)
    merged = dict(primary)
    base_keys = set()
    for k, v in base_hits.items():
        if k not in merged:
            merged[k] = v
            base_keys.add(k)
    return merged, base_keys


def compare(doc: BOMDocument, db: DBConnection,
            company_code: str = "",
            loss_pct: Optional[float] = None,
            base_company_code: str = "") -> list[ComparisonRow]:
    """
    Compare a parsed BOM against Emperor master data.

    loss_pct: metal wastage uplift in percent. When None, Emperor's own value
    for the customer is used, falling back to DEFAULT_METAL_LOSS_PCT.

    base_company_code: a fallback rate chart (e.g. "ZSELF"). Any line whose rate
    is missing for `company_code` is filled from this chart instead of showing
    N/A, and flagged with source_note="base chart". Ignored when blank or equal
    to company_code. Never overrides a rate the customer's own chart provides.
    """
    rows: list[ComparisonRow] = []

    if not db.is_connected():
        return rows

    # Guard: no self-fallback, and treat blank as disabled.
    base_company_code = (base_company_code or "").strip()
    if base_company_code == (company_code or "").strip():
        base_company_code = ""

    # Doc-level fallback loss %. The authoritative loss is looked up per metal
    # category (RmRt 'LS' rows are keyed by company + RrCtg) inside the metal
    # loop below; this value is only used when a category has no LS row.
    default_loss = loss_pct if loss_pct is not None else DEFAULT_METAL_LOSS_PCT

    # Aggregates shared by every line's context.
    metal_weight = sum(m.weight for m in doc.metals)
    diamond_weight = sum(s.weight for s in doc.stones
                         if s.description.strip().upper().startswith("D"))
    colour_weight = sum(s.weight for s in doc.stones
                        if s.description.strip().upper().startswith("C"))
    base_ctx = {
        "loss_pct": default_loss,
        "metal_weight": metal_weight,
        "diamond_weight": diamond_weight,
        "colour_weight": colour_weight,
        "CmMulBy": db.get_customer_multiplier(company_code),
    }

    # ---- Metals ----
    # Purity precedence: RmMst (global) → customer RM factor → base-chart RM
    # factor → CRP (universal). Only the base-factor layer is flagged; the CRP
    # layer is a shared standard factor, not the base chart.
    rm_codes = list({m.rm_code for m in doc.metals if m.rm_code})
    metal_purity = db.get_metal_purity(rm_codes)
    cust_factors = db.get_metal_rates(rm_codes, company_code, include_crp=False)
    base_factors = (db.get_metal_rates(rm_codes, base_company_code, include_crp=False)
                    if base_company_code else {})
    crp_factors = db.get_crp_factor(rm_codes)

    stone_rm_codes = list({s.rm_code for s in doc.stones if s.rm_code})
    rm_descriptions = db.get_rm_descriptions(list(set(rm_codes + stone_rm_codes)))

    for m in doc.metals:
        purity = None
        note = ""
        if m.rm_code in metal_purity:
            purity = metal_purity[m.rm_code]
        elif m.rm_code in cust_factors:
            purity = cust_factors[m.rm_code]
        elif m.rm_code in base_factors:
            purity = base_factors[m.rm_code]
            note = "base chart"
        elif m.rm_code in crp_factors:
            purity = crp_factors[m.rm_code]
        ctx = {**base_ctx, "lme": m.lme_rate, "weight": m.weight,
               "qty": m.qty, "line_value": m.value}
        # Loss % for this metal's category (G/P/S); fall back to the doc default.
        cat_loss = db.get_metal_loss_pct(company_code, m.category)
        ctx["loss_pct"] = cat_loss if cat_loss is not None else default_loss
        if cat_loss is not None:
            ctx["LossMst_LmLossPer"] = cat_loss
        if purity is not None:
            ctx["RmMst_RmPurityRt"] = purity
        crp = crp_factors.get(m.rm_code)
        if crp is not None:
            ctx["RmRt_CRP"] = crp
        _inject_custom_vars(ctx, db, {"rm_code": m.rm_code, "customer": company_code,
                                      "weight": m.weight, "qty": m.qty})
        master_val, trace = _eval_component("metal", company_code, ctx)
        desc = rm_descriptions.get(m.rm_code) or f"{m.category} {m.sub_category}".strip()
        rows.append(_row("Metal", m.rm_code, desc, m.value,
                         master_val, "metal", company_code, trace, note))

    # ---- Stones (diamond / colour) ----
    stone_lookups = list({(s.rm_code, _stone_candidates(s))
                          for s in doc.stones if s.rm_code})
    stone_prices = db.get_stone_prices(stone_lookups, company_code)
    stone_prices, base_stone_keys = _fill_from_base(
        stone_prices, db.get_stone_prices, stone_lookups, base_company_code)

    for s in doc.stones:
        key = (s.rm_code, _stone_candidates(s))
        master_price = stone_prices.get(key)
        component = "colour_stone" if s.description.strip().upper().startswith("C") else "diamond"
        dim = _stone_lookup_dim(s)
        ctx = {**base_ctx, "weight": s.weight, "qty": s.qty,
               "pointer": dim, "line_value": s.value,
               "setting_rate": s.rate_each, "setting_qty": s.qty}
        if master_price is not None:
            ctx["RmRt_rate"] = master_price
        _inject_custom_vars(ctx, db, {"rm_code": s.rm_code, "set_code": s.set_code,
                                      "customer": company_code, "pointer": dim,
                                      "weight": s.weight, "qty": s.qty})
        master_val, trace = _eval_component(component, company_code, ctx)
        desc = rm_descriptions.get(s.rm_code) or f"{s.shape} {s.dimension}".strip()
        note = "base chart" if key in base_stone_keys else ""
        rows.append(_row("Stone", s.rm_code or s.set_code, desc, s.value,
                         master_val, component, company_code, trace, note))

        # ---- Setting cost for this stone (SET/<code>, from LabRt) ----
        # Master setting rate lives in LabRt with LrMCd='SET'; the weight band is
        # matched on the PER-STONE weight (total carat / qty), and the value is
        # rate × number of stones set.
        if s.set_code and (s.setting_total or s.rate_each):
            per_stone_wt = (s.weight / s.qty) if s.qty else 0.0
            set_ctx = {**base_ctx, "qty": s.qty, "line_value": s.setting_total,
                       "setting_rate": s.rate_each, "setting_qty": s.qty}
            set_note = ""
            set_res = db.get_setting_rate(s.set_code, company_code, per_stone_wt,
                                          base_company_code)
            if set_res is not None:
                set_rate, _sqw, set_min, set_from_base = set_res
                set_ctx["LabRt_rate"] = set_rate
                set_ctx["LabRt_min"] = set_min
                if set_from_base:
                    set_note = "base chart"
            set_master, set_trace = _eval_component("setting", company_code, set_ctx)
            rows.append(_row("Stone Setting", f"SET/{s.set_code}",
                             f"{desc} setting".strip(), s.setting_total,
                             set_master, "setting", company_code, set_trace, set_note))

    # ---- Labour (setting / others) and Findings ----
    for lines, section, is_finding in (
        (doc.labour_setting, "Labour (Setting)", False),
        (doc.labour_others, "Labour (Others)", False),
        (doc.findings, "Findings", True),
    ):
        pairs = list({(l.pointer, l.sub_code) for l in lines if l.pointer})
        rates = db.get_labour_rates(pairs, company_code, weight=metal_weight)
        rates, base_labour_keys = _fill_from_base(
            rates,
            lambda missing, cc: db.get_labour_rates(missing, cc, weight=metal_weight),
            pairs, base_company_code)
        # Component used for display/edit when the rate (and thus Q/W) is unknown.
        default_component = "finding" if is_finding else "labour_q"
        for l in lines:
            key = (l.pointer, l.sub_code)
            rate_tuple = rates.get(key)
            component = default_component
            ctx = {**base_ctx, "qty": l.qty, "line_value": l.value}
            note = ""
            if rate_tuple is not None:
                master_rate, lr_qw, lab_min = rate_tuple
                component = "finding" if is_finding else _labour_component(l.pointer, lr_qw)
                ctx["LabRt_rate"] = master_rate
                ctx["LabRt_min"] = lab_min
                if key in base_labour_keys:
                    note = "base chart"
            _inject_custom_vars(ctx, db, {"main_code": l.pointer, "sub_code": l.sub_code,
                                          "customer": company_code, "qty": l.qty})
            master_val, trace = _eval_component(component, company_code, ctx)
            rows.append(_row(section, f"{l.pointer}/{l.sub_code}", l.sub_code,
                             l.value, master_val, component, company_code, trace, note))

    return rows


def summary_stats(rows: list[ComparisonRow], multiplier: float = 1.0) -> dict:
    """
    Roll up the comparison.

    multiplier: CustMst.CmMulBy — the additional-charge factor. Per the costing
    reference it applies to the TOTAL calculated price, not to individual lines,
    so it is applied here to the master total only. The template total already
    has whatever the quotation charged baked in.
    """
    total_template = sum(r.template_value for r in rows)
    total_master_raw = sum(r.master_value for r in rows if r.master_value is not None)
    total_master = round(total_master_raw * multiplier, 2)
    total_diff = round(total_master - total_template, 2)
    total_pct = round(_pct(total_template, total_master), 2) if total_template else 0.0
    counts: dict[str, int] = {"match": 0, "minor": 0, "major": 0, "missing": 0}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {
        "total_template": round(total_template, 2),
        "total_master_raw": round(total_master_raw, 2),
        "multiplier": multiplier,
        "total_master": total_master,
        "total_diff": total_diff,
        "total_pct": total_pct,
        "counts": counts,
    }
