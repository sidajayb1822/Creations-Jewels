"""
Formula model + safe evaluator for the EMR Reporter costing engine.

A pricing formula is a plain arithmetic **expression string** over named
variables, e.g.:

    (lme / TROY_OZ) * RmMst_RmPurityRt * (1 + loss_pct / 100) * weight

This module is the single source of truth for how those strings are:
  - described        (VARIABLES registry — where each name's value comes from)
  - evaluated        (evaluate() — a whitelisted-AST evaluator, no eval/exec)
  - traced           (evaluate() also returns an ordered TraceStep list)
  - round-tripped    (to_builder_steps / from_builder_steps for the UI builder)

Evaluation is deliberately sandboxed: only numbers, names from the supplied
context, the operators + - * / ** and unary minus, parentheses, and a tiny
whitelist of functions (min/max/round/abs) are allowed. Anything else raises
FormulaError, which callers treat as "no master value" rather than a crash.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Component types — one formula per component, optionally per customer.
# ---------------------------------------------------------------------------

COMPONENTS = [
    "metal",
    "diamond",
    "colour_stone",
    "finding",
    "labour_q",
    "labour_w",
    "cdw",
    "setting",
    "chain",
]

COMPONENT_LABELS = {
    "metal": "Metal",
    "diamond": "Diamond",
    "colour_stone": "Colour stone",
    "finding": "Finding",
    "labour_q": "Labour (per piece)",
    "labour_w": "Labour (per gram)",
    "cdw": "CDW (per diamond ct)",
    "setting": "Stone setting",
    "chain": "Chain & accessories",
}


# ---------------------------------------------------------------------------
# Variable registry
# Each entry: name -> (display_label, source_kind, source_ref)
#   source_kind: "bom" | "aggregate" | "db" | "setting" | "constant"
#   source_ref : human string shown in the builder / line-detail panel
# The registry is descriptive only — actual values arrive via the eval context.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VarInfo:
    label: str
    source_kind: str
    source_ref: str


VARIABLES: dict[str, VarInfo] = {
    # --- BOM line fields ---
    "weight":      VarInfo("Line weight", "bom", "BOM line — weight (g or ct)"),
    "qty":         VarInfo("Line quantity", "bom", "BOM line — qty"),
    "lme":         VarInfo("LME / metal Loc rate", "bom", "BOM metal line — LME (US$/troy oz)"),
    "pointer":     VarInfo("Pointer / size", "bom", "BOM stone line — pointer"),
    "line_value":  VarInfo("Template value", "bom", "BOM line — value as quoted"),
    "setting_rate": VarInfo("Stone setting rate", "bom", "BOM stone line — Set Code rate"),
    "setting_qty": VarInfo("Stones set", "bom", "BOM stone line — qty"),
    # --- aggregates across the BOM ---
    "metal_weight":   VarInfo("Total metal weight", "aggregate", "Σ metal weights (g)"),
    "diamond_weight": VarInfo("Total diamond weight", "aggregate", "Σ diamond carats (ctg D)"),
    "colour_weight":  VarInfo("Total colour-stone weight", "aggregate", "Σ colour carats (ctg C)"),
    # --- database lookups ---
    "RmMst_RmPurityRt": VarInfo("Metal purity", "db", "RmMst.RmPurityRt"),
    "RmRt_CRP":         VarInfo("CRP purity factor", "db", "RmRt.RrSalRt (TcTyp='CRP')"),
    "RmRt_rate":        VarInfo("Stone rate / carat", "db", "RmRt.RrSalRt (range match)"),
    "LabRt_rate":       VarInfo("Labour rate", "db", "LabRt.LrSalRt"),
    "LabRt_min":        VarInfo("Labour minimum charge", "db", "LabRt.LrSalMin"),
    "CmMulBy":          VarInfo("Customer multiplier", "db", "CustMst.CmMulBy"),
    "LossMst_LmLossPer": VarInfo("Loss % (Emperor)", "db", "LossMst.LmLossPer"),
    # --- settings ---
    "loss_pct": VarInfo("Metal loss %", "setting", "Settings — metal loss %"),
    # --- constants ---
    "TROY_OZ": VarInfo("Troy oz → gram", "constant", "31.1035"),
}

# Constants always available in every eval context.
CONSTANTS: dict[str, float] = {
    "TROY_OZ": 31.1035,
}


def sample_context() -> dict[str, float]:
    """Representative values for every variable — used to preview/validate a
    formula in the editor without a live BOM. Numbers echo the G14 example."""
    return {
        "weight": 4.7, "qty": 1.0, "lme": 4875.0, "pointer": 3.10, "line_value": 472.66,
        "setting_rate": 0.40, "setting_qty": 2.0,
        "metal_weight": 4.7, "diamond_weight": 0.774, "colour_weight": 0.0,
        "RmMst_RmPurityRt": 0.5833, "RmRt_CRP": 0.585, "RmRt_rate": 125.0,
        "LabRt_rate": 75.0, "LabRt_min": 0.0,
        "CmMulBy": 1.0, "LossMst_LmLossPer": 10.0, "loss_pct": 10.0,
    }

# Functions the evaluator permits.
_FUNCS = {
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
}


class FormulaError(Exception):
    """Raised for any invalid/unsafe expression or unresolved variable."""


# ---------------------------------------------------------------------------
# Trace — an ordered, human-readable breakdown of one evaluation.
# ---------------------------------------------------------------------------

@dataclass
class TraceStep:
    label: str          # e.g. "purity" / "× (1 + loss)"
    source: str         # where the operand came from (VarInfo.source_ref / "constant")
    operator: str       # "start" | "+" | "-" | "*" | "/" | "**" | "()"
    operand: float      # the operand value applied at this step
    running_total: float  # result after applying this step


# ---------------------------------------------------------------------------
# FormulaDef — the stored formula.
# ---------------------------------------------------------------------------

@dataclass
class FormulaDef:
    component: str
    customer_code: str = ""      # "" = default (applies to all customers)
    expression: str = ""
    enabled: bool = True
    notes: str = ""

    def key(self) -> tuple[str, str]:
        return (self.component, self.customer_code or "")

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "customer_code": self.customer_code or "",
            "expression": self.expression,
            "enabled": self.enabled,
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(d: dict) -> "FormulaDef":
        return FormulaDef(
            component=d["component"],
            customer_code=d.get("customer_code", "") or "",
            expression=d.get("expression", ""),
            enabled=bool(d.get("enabled", True)),
            notes=d.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Safe evaluation
# ---------------------------------------------------------------------------

_ALLOWED_BINOPS = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "**",
}


def validate(expression: str) -> tuple[bool, str]:
    """
    Parse-check an expression. Returns (ok, message). Does not evaluate, so it
    catches syntax + disallowed constructs but not missing variables.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        return False, f"Syntax error: {e.msg}"
    try:
        _check_nodes(tree)
    except FormulaError as e:
        return False, str(e)
    return True, "OK"


def _check_nodes(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
                name = getattr(node.func, "id", type(node.func).__name__)
                raise FormulaError(f"Function not allowed: {name}")
            if node.keywords:
                raise FormulaError("Keyword arguments are not allowed")
            continue
        if isinstance(node, ast.BinOp) and type(node.op) not in _ALLOWED_BINOPS:
            raise FormulaError(f"Operator not allowed: {type(node.op).__name__}")
        if isinstance(node, ast.UnaryOp) and not isinstance(node.op, (ast.USub, ast.UAdd)):
            raise FormulaError(f"Unary operator not allowed: {type(node.op).__name__}")
        if isinstance(node, (
            ast.Attribute, ast.Subscript, ast.Lambda, ast.IfExp, ast.BoolOp,
            ast.Compare, ast.ListComp, ast.Dict, ast.List, ast.Set, ast.Tuple,
            ast.Starred, ast.NamedExpr if hasattr(ast, "NamedExpr") else ast.AST,
        )):
            raise FormulaError(f"Construct not allowed: {type(node).__name__}")


def _num(node: ast.AST) -> Optional[float]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Num):  # pragma: no cover (old python)
        return float(node.n)
    return None


def _eval_node(node: ast.AST, ctx: dict[str, float]) -> float:
    """Recursively evaluate a validated AST node against the context."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, ctx)

    n = _num(node)
    if n is not None:
        return n

    if isinstance(node, ast.Name):
        if node.id in ctx:
            val = ctx[node.id]
            if val is None:
                raise FormulaError(f"Variable '{node.id}' has no value")
            return float(val)
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise FormulaError(f"Unknown variable: {node.id}")

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, ctx)
        right = _eval_node(node.right, ctx)
        op = type(node.op)
        if op is ast.Add:
            return left + right
        if op is ast.Sub:
            return left - right
        if op is ast.Mult:
            return left * right
        if op is ast.Div:
            if right == 0:
                raise FormulaError("Division by zero")
            return left / right
        if op is ast.Pow:
            return left ** right
        raise FormulaError(f"Operator not allowed: {op.__name__}")

    if isinstance(node, ast.UnaryOp):
        val = _eval_node(node.operand, ctx)
        return -val if isinstance(node.op, ast.USub) else +val

    if isinstance(node, ast.Call):
        func = _FUNCS[node.func.id]  # validated already
        args = [_eval_node(a, ctx) for a in node.args]
        return float(func(*args))

    raise FormulaError(f"Construct not allowed: {type(node).__name__}")


def evaluate(expression: str,
             context: dict[str, float]) -> tuple[float, list[TraceStep]]:
    """
    Evaluate an expression against a variable context.

    Returns (value, trace). Raises FormulaError on any unsafe construct,
    unknown/None variable, or division by zero.

    The trace is a best-effort linear breakdown built from the top-level
    left-associative chain of the expression (which covers the shapes our
    seeded formulas use). Sub-expressions are shown as one grouped operand.
    """
    tree = ast.parse(expression, mode="eval")
    _check_nodes(tree)
    value = _eval_node(tree, context)
    trace = _build_trace(tree.body, context)
    if not math.isfinite(value):
        raise FormulaError("Result is not a finite number")
    return value, trace


def _operand_meta(node: ast.AST) -> tuple[str, str]:
    """(label, source) for a leaf/grouped operand node."""
    if isinstance(node, ast.Name):
        info = VARIABLES.get(node.id)
        if info:
            return info.label, info.source_ref
        if node.id in CONSTANTS:
            return node.id, "constant"
        return node.id, "variable"
    if _num(node) is not None:
        return "constant", "constant"
    if isinstance(node, ast.Call):
        return f"{node.func.id}(…)", "function"
    return "( … )", "sub-expression"


def _build_trace(node: ast.AST, ctx: dict[str, float]) -> list[TraceStep]:
    """Flatten the left-associative operator chain into ordered TraceSteps."""
    chain: list[tuple[str, ast.AST]] = []

    def unwind(n: ast.AST):
        if isinstance(n, ast.BinOp) and type(n.op) in _ALLOWED_BINOPS:
            unwind(n.left)
            chain.append((_ALLOWED_BINOPS[type(n.op)], n.right))
        else:
            chain.append(("start", n))

    unwind(node)

    steps: list[TraceStep] = []
    running = 0.0
    for i, (op, operand_node) in enumerate(chain):
        operand_val = _eval_node(operand_node, ctx)
        label, source = _operand_meta(operand_node)
        if i == 0:
            running = operand_val
            steps.append(TraceStep(label, source, "start", operand_val, running))
            continue
        if op == "+":
            running = running + operand_val
        elif op == "-":
            running = running - operand_val
        elif op == "*":
            running = running * operand_val
        elif op == "/":
            running = running / operand_val if operand_val else running
        elif op == "**":
            running = running ** operand_val
        steps.append(TraceStep(label, source, op, operand_val, running))
    return steps


# ---------------------------------------------------------------------------
# Builder round-trip
# The guided builder shows a formula as an ordered list of steps. We support
# the left-associative chain shape (op, operand) which our seeded formulas use;
# operands may themselves be parenthesised sub-expressions kept as raw text.
# ---------------------------------------------------------------------------

@dataclass
class BuilderStep:
    operator: str    # "start" | "+" | "-" | "*" | "/" | "**"
    operand: str     # raw operand text: a variable name, number, or "(sub-expr)"


def to_builder_steps(expression: str) -> list[BuilderStep]:
    """Parse an expression into ordered builder steps. Raises FormulaError."""
    ok, msg = validate(expression)
    if not ok:
        raise FormulaError(msg)
    tree = ast.parse(expression, mode="eval")
    chain: list[tuple[str, ast.AST]] = []

    def unwind(n: ast.AST):
        if isinstance(n, ast.BinOp) and type(n.op) in _ALLOWED_BINOPS:
            unwind(n.left)
            chain.append((_ALLOWED_BINOPS[type(n.op)], n.right))
        else:
            chain.append(("start", n))

    unwind(tree.body)
    steps: list[BuilderStep] = []
    for op, node in chain:
        text = _unparse(node)
        # Wrap compound operands so re-serialisation stays correct.
        if isinstance(node, ast.BinOp):
            text = f"({text})"
        steps.append(BuilderStep(op, text))
    return steps


def from_builder_steps(steps: list[BuilderStep]) -> str:
    """Serialise builder steps back into an expression string."""
    parts: list[str] = []
    for i, s in enumerate(steps):
        operand = s.operand.strip()
        if i == 0:
            parts.append(operand)
        else:
            parts.append(f" {s.operator} {operand}")
    return "".join(parts).strip()


def _unparse(node: ast.AST) -> str:
    """Text form of a node (ast.unparse on 3.9+, small fallback otherwise)."""
    try:
        return ast.unparse(node).strip()  # py3.9+
    except AttributeError:  # pragma: no cover
        if isinstance(node, ast.Name):
            return node.id
        n = _num(node)
        if n is not None:
            return repr(n)
        return "?"
