from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BOMHeader:
    order_no: str = ""
    design_code: str = ""
    suffix: str = ""
    size: str = ""
    customer: str = ""
    po_reference: str = ""
    shipment_date: str = ""
    calc_price: float = 0.0
    sales_price: float = 0.0
    quantity: float = 0.0


@dataclass
class MetalLine:
    sr: int = 0
    category: str = ""
    sub_category: str = ""
    rm_code: str = ""
    qty: float = 0.0
    weight: float = 0.0
    calc_mode: str = "W"  # Q=Qty, W=Weight
    lme_rate: float = 0.0
    rate: float = 0.0
    value: float = 0.0
    source_row: int = 0   # 1-based Excel row this line was parsed from


@dataclass
class StoneLine:
    sr: int = 0
    shape: str = ""           # Sub-category: OVL, TAP, RND, etc.
    rm_code: str = ""         # Stone RM code: OV-LABVS, TAP-LABVS, etc. (col 4)
    set_code: str = ""        # Setting code: CFP, etc. (col 12)
    description: str = ""     # Category: D / C
    qty: float = 0.0          # Number of stones (col 7)
    dimension: str = ""       # Size string e.g. "2.5 PTR", "8x6" (col 5)
    pointer_value: float = 0.0  # Per-stone pointer/carat size for rate lookup (col 6)
    weight: float = 0.0       # Total carat weight (col 8)
    price: float = 0.0        # Rate per carat from BOM (col 10)
    value: float = 0.0        # Total value (col 11)
    sub_code: str = ""        # Setting sub-code (col 3, kept for compat)
    rate_each: float = 0.0    # Setting rate per stone (col 13)
    setting_total: float = 0.0  # Setting total value (col 14)
    source_row: int = 0       # 1-based Excel row this line was parsed from


@dataclass
class LabourLine:
    sr: int = 0
    section: str = ""     # "setting" or "others"
    pointer: str = ""
    set_code: str = ""
    description: str = ""
    sub_code: str = ""
    qty: float = 0.0
    rate: float = 0.0
    value: float = 0.0
    source_row: int = 0   # 1-based Excel row this line was parsed from


@dataclass
class FindingLine:
    sr: int = 0
    pointer: str = ""
    set_code: str = ""
    description: str = ""
    sub_code: str = ""
    qty: float = 0.0
    rate: float = 0.0
    value: float = 0.0
    source_row: int = 0   # 1-based Excel row this line was parsed from


@dataclass
class BOMSummary:
    metal_weight: float = 0.0
    metal_value: float = 0.0
    stone_qty: float = 0.0
    stone_weight: float = 0.0
    stone_value: float = 0.0
    coloured_stone_value: float = 0.0
    findings_value: float = 0.0
    labour_setting_value: float = 0.0
    labour_other_value: float = 0.0
    total_value: float = 0.0


@dataclass
class BOMDocument:
    header: BOMHeader = field(default_factory=BOMHeader)
    metals: list[MetalLine] = field(default_factory=list)
    stones: list[StoneLine] = field(default_factory=list)
    labour_setting: list[LabourLine] = field(default_factory=list)
    labour_others: list[LabourLine] = field(default_factory=list)
    findings: list[FindingLine] = field(default_factory=list)
    chain: list[MetalLine] = field(default_factory=list)  # Chain & Accessories section
    summary: BOMSummary = field(default_factory=BOMSummary)
    source_file: str = ""
    sheet_name: str = ""   # worksheet title — used as the design/tab label

    @property
    def design_label(self) -> str:
        """Best label for a per-design tab: design code, else sheet, else file."""
        return (self.header.design_code or self.sheet_name
                or self.source_file or "BOM").strip()
