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
