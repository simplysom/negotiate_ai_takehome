"""
Confidence scoring for normalized line items.
Fully deterministic — no LLM or network calls.

Score bands:
  0.80 – 1.00  High    — ready to use
  0.50 – 0.79  Medium  — use with caution
  0.00 – 0.49  Low     — escalate for human review
"""
from __future__ import annotations

import re
from typing import Optional

from backend.pipeline.models import UOMSource

_BASE_SCORE: dict[UOMSource, float] = {
    UOMSource.INVOICE_DIRECT: 0.90,
    UOMSource.LOOKUP_WEB:     0.0,   # overridden by lookup.confidence
    UOMSource.INFERRED:       0.55,
    UOMSource.MISSING:        0.15,
}


def score_line_item(
    uom_source: UOMSource,
    original_uom: Optional[str],
    pack_qty: Optional[int],
    price_per_ea: Optional[float],
    raw_unit_price: Optional[float],
    raw_quantity: Optional[float],
    raw_line_total: Optional[float],
    mpn_present: bool,
    pack_expression: Optional[str],
    lookup_confidence: float = 0.0,
) -> tuple[float, str]:
    """
    Compute confidence score for a single normalized line item.

    Returns:
        (score: float, line_total_check: str)
        line_total_check is "ok" | "mismatch" | "unverifiable"
    """
    from backend.config import CONTAINER_UOMS
    from backend.pipeline.normalizer import canonicalize_uom

    # 1. Base score
    if uom_source == UOMSource.LOOKUP_WEB:
        base = min(lookup_confidence, 0.85)
    else:
        base = _BASE_SCORE.get(uom_source, 0.15)
    score = base

    # 2. Pack expression clarity
    if original_uom is not None:
        canonical = canonicalize_uom(original_uom)
        if canonical in CONTAINER_UOMS:
            if pack_qty is not None and pack_expression:
                pass                     # explicit — no penalty
            elif pack_qty is not None:
                score *= 0.90            # resolved but implicit
            else:
                score *= 0.65            # container UOM, qty unknown
    else:
        score *= 0.70                    # no UOM at all

    # 3. Price-per-EA availability
    if price_per_ea is None:
        score *= 0.80

    # 4. MPN presence bonus
    if mpn_present:
        score = min(1.0, score + 0.04)

    # 5. Line-total cross-check
    line_total_check = "unverifiable"
    if raw_unit_price is not None and raw_quantity is not None and raw_line_total is not None:
        expected = raw_unit_price * raw_quantity
        if abs(expected - raw_line_total) / max(raw_line_total, 0.01) < 0.05:
            line_total_check = "ok"
            score = min(1.0, score + 0.03)
        else:
            line_total_check = "mismatch"
            score *= 0.80

    return round(min(1.0, max(0.0, score)), 4), line_total_check


def ocr_noise_penalty(text: str) -> float:
    """Multiplicative penalty (0–1) based on detected OCR noise in text."""
    noise_indicators = [
        r"[^\x00-\x7F]",
        r"[|]{2,}",
        r"\b[A-Z]{1}[0-9]{5,}\b",
        r"\.{4,}",
    ]
    hits = sum(1 for p in noise_indicators if re.search(p, text))
    return max(0.70, 1.0 - hits * 0.05)
