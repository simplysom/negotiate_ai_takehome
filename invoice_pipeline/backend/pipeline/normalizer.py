"""
Deterministic UOM normalizer.

Responsibilities:
  1. Canonicalize raw UOM strings (e.g. "EACH" → "EA", "DOZEN" → "DZ")
  2. Parse pack expressions from descriptions (e.g. "25/CS", "PK10", "1000 EA")
  3. Compute the pack quantity and the canonical base UOM (EA)
  4. Compute price-per-EA when pack quantity is known

Nothing in this module calls an LLM or the network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# ─── UOM alias table ──────────────────────────────────────────────────────────
# Maps raw strings → canonical abbreviation

UOM_ALIASES: dict[str, str] = {
    # Each
    "EA": "EA", "EACH": "EA", "PC": "EA", "PCS": "EA",
    "PIECE": "EA", "PIECES": "EA", "UNIT": "EA", "UNITS": "EA",
    "IT": "EA",
    # Pair
    "PR": "PR", "PAIR": "PR", "PRS": "PR", "PAIRS": "PR",
    # Dozen
    "DZ": "DZ", "DOZ": "DZ", "DOZEN": "DZ", "DOZENS": "DZ",
    # Case
    "CS": "CS", "CASE": "CS", "CASES": "CS", "CA": "CS",
    # Box
    "BX": "BX", "BOX": "BX", "BOXES": "BX",
    # Pack / Package
    "PK": "PK", "PK.": "PK", "PKG": "PK", "PACK": "PK",
    "PACKAGE": "PK", "PKT": "PK",
    # Count / Carton
    "CT": "CT", "CNT": "CT", "COUNT": "CT",
    "CTN": "CT", "CARTON": "CT",
    # Bag
    "BG": "BG", "BAG": "BG", "BAGS": "BG",
    # Bottle
    "BT": "BT", "BTL": "BT", "BOTTLE": "BT", "BOTTLES": "BT",
    # Gallon
    "GL": "GL", "GAL": "GL", "GALLON": "GL", "GALLONS": "GL",
    # Roll
    "RL": "RL", "ROLL": "RL", "ROLLS": "RL",
    # Kit
    "KT": "KT", "KIT": "KT", "KITS": "KT",
    # Pound
    "LB": "LB", "LBS": "LB", "POUND": "LB", "POUNDS": "LB",
    # Ounce
    "OZ": "OZ", "OUNCE": "OZ", "OUNCES": "OZ",
    # Sack
    "SK": "SK", "SACK": "SK",
    # Tube
    "TU": "TU", "TUBE": "TU", "TUBES": "TU",
    # Can
    "CN": "CN", "CAN": "CN", "CANS": "CN",
    # Set
    "ST": "ST", "SET": "ST", "SETS": "ST",
}

# ─── Conversion factors to EA ──────────────────────────────────────────────────
# For UOMs with fixed, universally-agreed pack quantities
FIXED_EA_FACTORS: dict[str, int] = {
    "EA": 1,
    "PR": 2,    # 1 pair = 2 individual items
    "DZ": 12,   # 1 dozen = 12 EA
    "KT": 1,    # kit = 1 unit (the kit itself)
}

# ─── Pack expression patterns ──────────────────────────────────────────────────
# Each pattern returns (pack_qty: int, container_uom: str | None)
# Ordered from most-specific to least-specific.

_UOM_NAMES = r"(?:CS|BX|PK|CT|CTN|CASE|BOX|PACK|BAG|BG|BT|BOTTLE|CARTON|EA|EACH|DZ|PR|RL|ROLL|GL|GAL|SK|ST|SET)"

_PACK_PATTERNS: list[tuple[str, str]] = [
    # Nested: "100/BX 8 BX/CS"  →  800 /CS  (pick the larger container)
    # Handled specially below.

    # Compound: "12PR/PK", "24EA/CS", "10PC/BX" → inner qty × inner uom per outer uom
    (r"(\d+)\s*(" + _UOM_NAMES + r")\s*/\s*(" + _UOM_NAMES + r")\b", "compound"),

    # "N/UOM"  e.g.  25/CS, 100/BX, 12/PK
    (r"(\d+)\s*/\s*(" + _UOM_NAMES + r")\b", "slash"),

    # "UOM-N" or "UOM N"  e.g.  PK10, PK 10, BX12
    (r"\b(" + _UOM_NAMES + r")[- ]?(\d+)\b", "uom_first"),

    # "N DZ" shorthand (dozen) — must come BEFORE generic qty_first to avoid DZ ambiguity
    (r"\b(\d+)\s*DZ\b", "dozen"),

    # "N UOM"  e.g.  1000 EA, 12 PR, 2 DZ
    (r"\b(\d{1,5})\s+(" + _UOM_NAMES + r")\b", "qty_first"),

    # "CASE OF N" / "BOX OF N" / "PACK OF N"
    (r"\b(CASE|BOX|PACK)\s+OF\s+(\d+)\b", "of"),

    # "N-PK" or "N-CT"
    (r"\b(\d+)-(PK|CT|CS|BX)\b", "hyphen"),

    # Terminal UOM: description ends with a standalone UOM token
    # e.g. "M Wht SW Glove PR", "Foam Ear Plugs CASE", "Safety Glasses EA"
    # Only fires when no other pattern matched — lowest priority.
    (r"\b(" + _UOM_NAMES + r")\s*$", "terminal_uom"),
]


@dataclass
class PackInfo:
    """Result of pack expression parsing."""
    pack_qty: Optional[int]
    container_uom: Optional[str]      # canonical container UOM (CS, BX …)
    matched_expression: Optional[str]  # the substring that triggered the match
    is_fixed_conversion: bool          # True when factor is universally known


def canonicalize_uom(raw: Optional[str]) -> Optional[str]:
    """Map a raw UOM string to its canonical form. Returns None if unrecognised."""
    if not raw:
        return None
    key = raw.strip().upper().rstrip(".")
    return UOM_ALIASES.get(key)


def _parse_nested(text: str) -> Optional[PackInfo]:
    """
    Detect nested pack expressions like "100/BX 8 BX/CS" and compute
    the total pack quantity against the outermost container.
    Returns None if no nested pattern found.
    """
    pattern = re.compile(
        r"(\d+)\s*/\s*(" + _UOM_NAMES + r")\s+(\d+)\s*" + _UOM_NAMES + r"\s*/\s*(" + _UOM_NAMES + r")",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if m:
        inner_qty = int(m.group(1))
        outer_qty = int(m.group(3))
        outer_uom = canonicalize_uom(m.group(4)) or m.group(4).upper()
        total = inner_qty * outer_qty
        return PackInfo(
            pack_qty=total,
            container_uom=outer_uom,
            matched_expression=m.group(0),
            is_fixed_conversion=False,
        )
    return None


def parse_pack_expression(text: str) -> PackInfo:
    """
    Scan *text* for pack size expressions and return the best match.

    Priority:
      1. Nested expressions (e.g. "100/BX 8 BX/CS")
      2. Slash notation  (e.g. "25/CS")
      3. UOM-first       (e.g. "PK10")
      4. Qty-first       (e.g. "1000 EA")
      5. "CASE OF N"
    """
    if not text:
        return PackInfo(None, None, None, False)

    upper = text.upper()

    # 1. Nested
    nested = _parse_nested(upper)
    if nested:
        return nested

    # 2–5. Single patterns
    for pattern_str, kind in _PACK_PATTERNS:
        m = re.search(pattern_str, upper, re.IGNORECASE)
        if not m:
            continue

        if kind == "compound":
            # e.g. "12PR/PK" → 12 pairs per pack → pack_qty = 12*2 = 24 EA per PK
            inner_qty = int(m.group(1))
            inner_uom = canonicalize_uom(m.group(2)) or m.group(2).upper()
            outer_uom = canonicalize_uom(m.group(3)) or m.group(3).upper()
            inner_factor = FIXED_EA_FACTORS.get(inner_uom, 1)
            total_ea = inner_qty * inner_factor
            return PackInfo(total_ea, outer_uom, m.group(0), inner_uom in FIXED_EA_FACTORS)

        if kind == "slash":
            qty = int(m.group(1))
            uom = canonicalize_uom(m.group(2)) or m.group(2).upper()
            # Skip trivial "1/EA" — that's just saying qty 1
            if qty == 1 and uom == "EA":
                continue
            is_fixed = uom in FIXED_EA_FACTORS
            return PackInfo(qty, uom, m.group(0), is_fixed)

        elif kind == "uom_first":
            uom = canonicalize_uom(m.group(1)) or m.group(1).upper()
            qty = int(m.group(2))
            is_fixed = uom in FIXED_EA_FACTORS
            return PackInfo(qty, uom, m.group(0), is_fixed)

        elif kind == "qty_first":
            qty = int(m.group(1))
            uom = canonicalize_uom(m.group(2)) or m.group(2).upper()
            if qty == 1 and uom == "EA":
                continue
            is_fixed = uom in FIXED_EA_FACTORS
            return PackInfo(qty, uom, m.group(0), is_fixed)

        elif kind == "of":
            container_map = {"CASE": "CS", "BOX": "BX", "PACK": "PK"}
            uom = container_map[m.group(1).upper()]
            qty = int(m.group(2))
            return PackInfo(qty, uom, m.group(0), False)

        elif kind == "dozen":
            qty = int(m.group(1)) * 12
            return PackInfo(qty, "EA", m.group(0), True)

        elif kind == "hyphen":
            qty = int(m.group(1))
            uom = canonicalize_uom(m.group(2)) or m.group(2).upper()
            return PackInfo(qty, uom, m.group(0), False)

        elif kind == "terminal_uom":
            uom = canonicalize_uom(m.group(1)) or m.group(1).upper()
            # EA at the end means sold individually — trivial, skip
            if uom == "EA":
                continue
            is_fixed = uom in FIXED_EA_FACTORS
            return PackInfo(None, uom, m.group(0), is_fixed)

    return PackInfo(None, None, None, False)


def compute_price_per_ea(
    unit_price: Optional[float],
    uom: Optional[str],
    pack_qty: Optional[int],
) -> tuple[Optional[float], str]:
    """
    Compute price per individual EA given the unit price, canonical UOM,
    and pack quantity (from a pack expression in the description).

    Logic:
      - EA: price / pack_qty (pack_qty items per container) or price (if qty unknown)
      - DZ: price / (pack_qty × 12)  — pack_qty dozens per container
      - PR: price / (pack_qty × 2)   — pack_qty pairs per container
      - KT: price / 1                — kit is the EA
      - CS/BX/PK/…: price / pack_qty when pack_qty is known
      - Unknown without pack_qty → cannot convert; returns (None, uom)

    Returns:
        (price_per_ea, canonical_base_uom)
    """
    if unit_price is None:
        return None, "EA"

    canonical_uom = canonicalize_uom(uom) if uom else None

    # Fixed-factor UOMs: multiply the per-item factor by pack_qty if supplied.
    # pack_qty here comes from a pack expression (not quantity_ordered).
    # e.g. "12 DZ" → pack_qty=12, uom=DZ → total EA = 12 × 12 = 144
    # e.g. uom=DZ only  → pack_qty=None → treat as 1 DZ = 12 EA
    if canonical_uom in FIXED_EA_FACTORS:
        factor = FIXED_EA_FACTORS[canonical_uom]  # EA=1, PR=2, DZ=12, KT=1
        multiplier = (pack_qty or 1) * factor
        return round(unit_price / multiplier, 6), "EA"

    # Container UOMs (CS, BX, PK, …) — need pack_qty to convert
    if pack_qty and pack_qty > 0:
        return round(unit_price / pack_qty, 6), "EA"

    # Can't convert without pack_qty
    return None, canonical_uom or "EA"
