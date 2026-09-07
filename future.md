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

---

## 3. Chain / accessory rate — quoted value is ~3× the stored rate (source rule unknown)

**Status:** deeply investigated, NOT explained by any readable table. Do NOT assume chain
lines will auto-match on live data. Needs one question to the client before trusting them.

**What it is**
Chain & accessory lines (category `X` raw materials — post backs, nuts, hang tags) are quoted
by Emperor at a value that is roughly **3× the rate stored in the master rate chart**, and that
multiplier is **not found anywhere in the database**.

**Anchor design:** `SO-26-REG-225-1.xlsx` → `ER25164-(6)` (customer ADINA / `9ADNAPRC`),
metal G14 @ LME 4076. Chain lines (value = rate × qty, Q basis — confirmed from sheet formula):

| Code | Ctg/Sub | Qty | Wt | Quote rate | Quote value |
|------|---------|-----|-----|-----------|-------------|
| `14KYDBNOCPST` | X/PST (post) | 2 | 0.112 | **5.014** | 10.028 |
| `14KYPSBKZ` | X/NUT (nut) | 2 | 0.162 | **7.779** | 15.558 |
| `14Y14+1+1` | X/CHN (tag) | 1 | 1.14 | **113.106** | 113.106 |

**Where the rate actually lives (corrects an earlier wrong assumption)**
- Accessories are **NOT priced per-customer.** `9ADNAPRC` has 1,578 `RmRt` rows but **zero**
  category-X rows. The customer chart deliberately holds no accessory rates.
- They price from **`ZSELF`** — the manufacturer's own house company (7,646 category-X rows).
  The app's `base_company_code = ZSELF` fallback is therefore the *correct* source. (Old
  `OrdRm` rows confirm the lookup company is the house code, not the customer — `OrCoCd = ZZZ`.)
- `RmMst.RmPurityRt = 0.0` for all three, so Emperor does **not** cost them as gold-by-weight;
  the weight column is informational. Value is purely `rate × qty`.

**Why it does NOT reproduce, even on current data**
- Stored `ZSELF` rates: `14KYDBNOCPST` = **1.63**, `14KYPSBKZ` = **2.55**, `14Y14+1+1` = **42.05**.
- Quote used 5.014 / 7.779 / 113.106 → ratios **3.08 / 3.05 / 2.69** (the two small parts ~3.06,
  the tag 2.69 — not a single clean factor).
- The exact quoted rates (5.014 etc.) appear in **no** table: not `RmRt`, `RmRtHist`, `OrdRm`,
  or `MultiPrcQtRm`. The ~3× uplift is applied inside Emperor's pricing engine at quote time.
- Not gold-by-weight (implied per-gram 89.5 / 96.0 / 99.2 — all differ, all above the 85.6/g
  base gold rate; purity is 0 anyway). Not a base-chart scale (ratios inconsistent). Not a
  customer multiplier (`CmMulBy = 1.0`).

**The "stale backup" theory was ruled out (important)**
- Quote date **2026-06-30**; DB backup/restore **2026-06-27** (backup is 3 days older).
- BUT the `ZSELF` accessory rates were last changed **2025-09/10** (`ModDt` 2025-10-09 /
  2025-09-19) — stable ~8 months, unchanged in that 3-day window. So the backup holds the SAME
  rate (1.63) the quote would have read. The 3-day gap does **not** explain the 3× difference.

**Consequence for the app**
Current chain formula `RmRt_rate * qty` gives 1.63 × 2 = **3.26**; the quote is **10.028**.
So chain lines will show a large mismatch **even on fully current live data** until the ~3×
rule is known. The app's *source* (ZSELF) is right; the *transform* is missing.

**Next step (client question, before any code change)**
Ask: "For chain / accessory (category X) parts, how does Emperor get from the stored rate
(e.g. 1.63) to the quoted rate (5.014)? Is there a gold multiplier or markup applied at quote
time?" Their rule → a small formula change (a `chain` component multiplier / gold factor).

**Reference tables:** `RmRt` (RrCd, RrCmCd, RrCtg='X', RrFrLn/RrToLn gold band, RrSalRt,
ModDt), `RmMst` (RmPurityRt=0 for these), `OrdRm` (OrCoCd=ZZZ house company, historical
OrSalRt ~2.0), `RmRtHist` (no rows for these codes), `MultiPrcQtRm` (quote RM — no rows in
this restore). App: `get_chain_rates` (`app/core/db.py`), chain loop + `_fill_from_base`
(`app/core/comparator.py`), `SEED_DEFAULTS["chain"]` (`app/core/formula_store.py`).
