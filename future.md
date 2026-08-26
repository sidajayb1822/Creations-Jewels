# Future considerations / backlog

Notes on things worth handling later. Nothing here is implemented yet.

---

## 1. Per-design (variable) labour should not be compared to the static rate chart

**Status:** investigated, not implemented (deliberately deferred).

**What it is**
Some labour operations are **per-design charges**, not fixed customer rates. The clearest
example is **`CAD/SKCADRUS`** (the computer-aided-design fee): the amount depends on how much
CAD work a specific design needs, so it is chosen per order/design — not read from the
customer's rate chart.

**Evidence (from the live Emperor DB)**
- Across ALL orders, `CAD/SKCADRUS` is charged at a wide spread of values, all common:
  $35 (2,657 orders), $75 (2,601), $125 (1,429), $150 (1,317), $100 (924),
  **$175 (898)**, $200 (737), … ranging $25–$500. So $175 is a normal value, not a one-off.
- The design master `CUR04242` (`DsgLab` table) lists *which* operations apply
  (CAD, CFP, ENGRV, RH) but **stores no rate** — the rate is entered per order.
- On order `CJE\QT\26\A\382` the rates ($175 CAD, $20 CFP, $1 ENGRV) were set by operator
  `MKT8` in April 2026; the customer chart's $75 / $15 are older (2023–2025) placeholder
  defaults.

**Why it matters**
The BOM Compare tool currently compares these lines against the customer's static rate chart
(e.g. `CAD/SKCADRUS` chart = $75), so a correct per-design charge ($175) shows up as a large
red "mismatch" even though nothing is wrong. This produces false discrepancies.

**Possible future handling (not decided)**
- Tag a set of "per-design / variable" labour operations (at least `CAD/SKCADRUS`, possibly
  the engraving/finding heads like `CFP/RNG-ENG`, `ENGRV/ENGRNG`) as *not comparable*.
- For those lines, either skip the comparison or show them in a neutral "per-design charge"
  state (own colour/label) instead of red — the quote value stands on its own.
- Optionally cross-check against `DsgLab` to confirm the operation belongs to the design, and
  surface the design-level context rather than the chart rate.
- Make the "variable labour" list configurable (Settings), since which operations count as
  per-design is a client/business decision.

**Reference tables:** `OrdLab` (order labour actually charged), `DsgLab` (design operations,
no rate), `LabRt` (static customer rate chart), `MultiPrcQtLab` / `xTxnLab` (quote/txn labour).

---

## 2. One customer name → two Emperor accounts (regular vs lab-grown)

**Status:** investigated, undecided — parked deliberately.

**What it is**
A single BOM customer name can map to **two (or more) real Emperor customer codes** with
different rate charts. "OM JEWELRY INC" has:
- `OMJEWLRY` — the regular account
- `OM-LGD` — "OM JEWELRY INC (LGD)", the **lab-grown-diamond** account

The exact-name auto-match (`find_company_code` in `app/core/db.py`) now resolves the file to
`OMJEWLRY`. That fixed the engraving labour line but **regressed the stone lines**, because
this order's stones are lab-grown and their rates match the **OM-LGD** chart, not OMJEWLRY.

**Evidence (order `CJE\QT\26\A\382`, from `OrdRm` / `OrdLab`)**

| Line | Quote (Emperor) | OM-LGD chart | OMJEWLRY chart |
|------|-----------------|--------------|----------------|
| TAP-LABVS @3.1mm | 125/ct → 96.75 | **125 ✅** | 115 → 89.01 ✗ |
| OV-LABVS | 0.001 → ~0 | **0.001 ✅** | missing (N/A) |
| ENGRV/ENGRNG | 1.00 | missing (N/A) | **1.00 ✅** |

So **no single account reproduces the whole quote** — stones line up with OM-LGD, engraving
labour with OMJEWLRY. Likely the quote was built from the design's **frozen costing**, which
matches OM-LGD's older stone rates while OMJEWLRY's have since drifted (115).

**Why it matters**
Auto-detecting by name alone can pick the "wrong" sibling account and flip several lines
between match and mismatch/N/A. Which account is authoritative depends on the order type
(lab-grown vs natural), which the name doesn't state.

**Possible future handling (not decided)**
- Let the user map a customer name → a specific company code (a saved alias table), and/or a
  rule like "lab-grown BOM → the -LGD account".
- Or make auto-detect prefer the sibling account whose chart best **covers the BOM's actual
  items** (most lines resolved), instead of just the exact name.
- Or detect lab-grown content in the BOM (stone codes like `*-LAB*`, `*LBG*`) and prefer the
  matching LGD account.
- Interim workaround (already possible, no code change): set **Company code** manually in
  Settings per file (e.g. `OM-LGD` for a lab-grown OM order).

**Reference:** `find_company_code` (`app/core/db.py`), `CustMst` (`CmCd`, `CmName`,
`CmLkUpRmRt`, `CmLkUpLabRt`), `OrdRm` / `OrdLab` (what the quote actually used).
