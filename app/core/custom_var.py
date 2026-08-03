"""
Custom variables — user-defined DB lookups that become selectable in formulas
without any code change. Each one names a table + value column + match keys;
the comparator resolves it live per line and injects the result into the
formula context. Definitions are stored locally (Emperor stays read-only).

Match sources are the per-line fields the comparator can supply:
  rm_code, set_code, main_code, sub_code, customer, pointer, weight, qty
plus "literal" for a fixed value typed by the user.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


CUSTOM_VARS_PATH = Path.home() / ".emr_reporter" / "custom_variables.json"

# Per-line fields available to match against, with friendly labels for the UI.
MATCH_SOURCES: dict[str, str] = {
    "rm_code": "Line RM code",
    "set_code": "Stone setting code",
    "main_code": "Labour main code",
    "sub_code": "Labour sub code",
    "customer": "Customer / company code",
    "pointer": "Stone pointer / size",
    "weight": "Line weight",
    "qty": "Line quantity",
    "literal": "Fixed value…",
}

OPERATORS = ["=", "<=", ">=", "<", ">"]
AGGREGATES = ["TOP1", "MIN", "MAX", "SUM", "AVG"]


@dataclass
class MatchKey:
    column: str            # DB column on the target table
    op: str = "="          # comparison between column and the source value
    source: str = "rm_code"  # a MATCH_SOURCES key, or "literal"
    literal: str = ""      # used when source == "literal"

    def to_dict(self) -> dict:
        return {"column": self.column, "op": self.op,
                "source": self.source, "literal": self.literal}

    @staticmethod
    def from_dict(d: dict) -> "MatchKey":
        return MatchKey(d.get("column", ""), d.get("op", "="),
                        d.get("source", "rm_code"), d.get("literal", ""))


@dataclass
class CustomVar:
    name: str                       # token used in formulas (valid identifier)
    table: str = ""
    value_column: str = ""
    aggregate: str = "TOP1"
    label: str = ""
    match_keys: list[MatchKey] = field(default_factory=list)
    enabled: bool = True
    notes: str = ""

    def source_ref(self) -> str:
        return f"{self.table}.{self.value_column}" if self.table else "(unset)"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "table": self.table,
            "value_column": self.value_column,
            "aggregate": self.aggregate,
            "label": self.label,
            "match_keys": [m.to_dict() for m in self.match_keys],
            "enabled": self.enabled,
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(d: dict) -> "CustomVar":
        return CustomVar(
            name=d["name"],
            table=d.get("table", ""),
            value_column=d.get("value_column", ""),
            aggregate=d.get("aggregate", "TOP1"),
            label=d.get("label", ""),
            match_keys=[MatchKey.from_dict(m) for m in d.get("match_keys", [])],
            enabled=bool(d.get("enabled", True)),
            notes=d.get("notes", ""),
        )


class CustomVarStore:
    def __init__(self, path: Path = CUSTOM_VARS_PATH):
        self._path = path
        self._vars: dict[str, CustomVar] = {}
        self.reload()

    def reload(self) -> None:
        self._vars = {}
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                for d in data.get("custom_variables", []):
                    cv = CustomVar.from_dict(d)
                    self._vars[cv.name] = cv
            except Exception:
                self._vars = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"custom_variables": [cv.to_dict() for cv in self.list_all()]}
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def list_all(self) -> list[CustomVar]:
        return sorted(self._vars.values(), key=lambda c: c.name.lower())

    def get(self, name: str) -> Optional[CustomVar]:
        return self._vars.get(name)

    def upsert(self, cv: CustomVar) -> None:
        self._vars[cv.name] = cv
        self.save()

    def delete(self, name: str) -> None:
        self._vars.pop(name, None)
        self.save()


custom_var_store = CustomVarStore()
