"""
Local persistence + CRUD for pricing formulas.

Formulas live in ~/.emr_reporter/formulas.json (next to config.json). The
Emperor SQL Server is NEVER written to — all formula state is local and
reversible.

On first run (or whenever a component's default is missing) the store seeds
built-in defaults that reproduce the previously hard-coded comparator math, so
behaviour is identical until the user edits a formula.

Lookup semantics: get(component, customer) returns the customer-specific
formula if one exists and is enabled, otherwise the default ("" customer),
otherwise the built-in seed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.core.formula import FormulaDef, COMPONENTS


FORMULAS_PATH = Path.home() / ".emr_reporter" / "formulas.json"


# ---------------------------------------------------------------------------
# Built-in defaults — mirror the verified comparator math (customer "" = all).
#   metal:        (LME / 31.1035) × purity × (1 + loss%) × weight
#   diamond/CS:   stone rate/ct × carat weight
#   labour_q:     rate × qty          labour_w: rate × total metal weight
#   cdw:          rate × total diamond weight
#   finding:      rate direct
# ---------------------------------------------------------------------------

SEED_DEFAULTS: dict[str, FormulaDef] = {
    "metal": FormulaDef(
        component="metal",
        expression="(lme / TROY_OZ) * RmMst_RmPurityRt * (1 + loss_pct / 100) * weight",
        notes="Metal value. Purity from RmMst.RmPurityRt; loss % from settings/Emperor.",
    ),
    "diamond": FormulaDef(
        component="diamond",
        expression="RmRt_rate * weight",
        notes="Diamond value = per-carat rate (RmRt range match) × total carat weight.",
    ),
    "colour_stone": FormulaDef(
        component="colour_stone",
        expression="RmRt_rate * weight",
        notes="Colour-stone value = per-carat rate × total carat weight.",
    ),
    "finding": FormulaDef(
        component="finding",
        expression="LabRt_rate",
        notes="Finding rate taken directly from the rate master.",
    ),
    "labour_q": FormulaDef(
        component="labour_q",
        expression="LabRt_rate * qty",
        notes="Per-piece labour = rate × quantity (LrQw='Q').",
    ),
    "labour_w": FormulaDef(
        component="labour_w",
        expression="LabRt_rate * metal_weight",
        notes="Per-gram labour = rate × total metal weight (LrQw='W').",
    ),
    "cdw": FormulaDef(
        component="cdw",
        expression="LabRt_rate * diamond_weight",
        notes="Diamond-weight labour (CDW) = rate × total diamond carats.",
    ),
}


class FormulaStore:
    """In-memory cache of FormulaDefs backed by formulas.json."""

    def __init__(self, path: Path = FORMULAS_PATH):
        self._path = path
        self._defs: dict[tuple[str, str], FormulaDef] = {}
        self.reload()

    # ---- persistence ----
    def reload(self) -> None:
        self._defs = {}
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                for d in data.get("formulas", []):
                    fd = FormulaDef.from_dict(d)
                    self._defs[fd.key()] = fd
            except Exception:
                self._defs = {}
        self._ensure_seeds()

    def _ensure_seeds(self) -> None:
        """Add any missing built-in default; persist if we had to add one."""
        changed = False
        for comp, seed in SEED_DEFAULTS.items():
            if (comp, "") not in self._defs:
                self._defs[(comp, "")] = FormulaDef.from_dict(seed.to_dict())
                changed = True
        if changed:
            self.save()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"formulas": [fd.to_dict() for fd in self._sorted()]}
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _sorted(self) -> list[FormulaDef]:
        # defaults first, then customer overrides, grouped by component order
        order = {c: i for i, c in enumerate(COMPONENTS)}
        return sorted(
            self._defs.values(),
            key=lambda fd: (order.get(fd.component, 99), fd.customer_code or ""),
        )

    # ---- CRUD ----
    def list_all(self) -> list[FormulaDef]:
        return self._sorted()

    def get(self, component: str, customer_code: str = "") -> Optional[FormulaDef]:
        """Customer override (if enabled) → default → built-in seed."""
        cust = (customer_code or "").strip()
        if cust:
            fd = self._defs.get((component, cust))
            if fd and fd.enabled:
                return fd
        fd = self._defs.get((component, ""))
        if fd and fd.enabled:
            return fd
        return SEED_DEFAULTS.get(component)

    def upsert(self, fd: FormulaDef) -> None:
        self._defs[fd.key()] = fd
        self.save()

    def delete(self, component: str, customer_code: str = "") -> None:
        key = (component, (customer_code or "").strip())
        if key in self._defs:
            del self._defs[key]
        # never leave a component without a default
        if key[1] == "" and component in SEED_DEFAULTS:
            self._defs[(component, "")] = FormulaDef.from_dict(
                SEED_DEFAULTS[component].to_dict()
            )
        self.save()

    def reset_to_default(self, component: str, customer_code: str = "") -> None:
        """Delete a customer override, or restore a default to its seed."""
        cust = (customer_code or "").strip()
        if cust:
            self.delete(component, cust)
        elif component in SEED_DEFAULTS:
            self._defs[(component, "")] = FormulaDef.from_dict(
                SEED_DEFAULTS[component].to_dict()
            )
            self.save()


# Module-level singleton (mirrors db.py's pattern).
formula_store = FormulaStore()
