"""
Hallucination Checker

Verifies that values extracted by the LLM actually appear in the source PDF text.
Produces a per-item risk score and a list of specific flags.

Risk levels:
  0.0 – 0.20  Low     (likely clean extraction)
  0.21 – 0.49 Medium  (some fields unverifiable)
  0.50+       High    (likely hallucination)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ─── Data types ───────────────────────────────────────────────────────────────

@dataclass
class FieldCheck:
    field: str
    value: str
    found_in_source: bool
    detail: str = ""


@dataclass
class ItemHallucinationReport:
    item_index: int
    item_description: str
    risk_score: float          # 0.0 – 1.0
    risk_level: str            # "low" | "medium" | "high"
    flags: list[str]
    checks: list[FieldCheck]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _token_overlap(query: str, corpus: str) -> float:
    """Fraction of non-trivial tokens in `query` that appear in `corpus`."""
    stop = {"the", "a", "an", "of", "in", "for", "and", "or", "with", "to"}
    tokens = {t for t in _normalize(query).split() if len(t) > 2 and t not in stop}
    if not tokens:
        return 1.0
    corpus_n = _normalize(corpus)
    found = sum(1 for t in tokens if t in corpus_n)
    return found / len(tokens)


def _price_in_text(price: float, text: str) -> bool:
    """Check if a price value appears in text (try several formats)."""
    candidates = {
        f"{price:.2f}",
        f"{price:.4f}",
        f"{price:,.2f}",
        str(int(price)) if price == int(price) else None,
    }
    return any(c and c in text for c in candidates)


# ─── Core item checker ────────────────────────────────────────────────────────

def check_item(
    raw_text: str,
    item_description: str,
    item_number: Optional[str],
    mpn: Optional[str],
    raw_unit_price: Optional[float],
    raw_quantity: Optional[float],
    raw_line_total: Optional[float],
    item_index: int,
) -> ItemHallucinationReport:

    checks: list[FieldCheck] = []
    flags:  list[str]        = []
    risk_components: list[float] = []

    # ── 1. Description token overlap ──────────────────────────────────────────
    overlap = _token_overlap(item_description, raw_text)
    desc_ok = overlap >= 0.50
    checks.append(FieldCheck(
        field="item_description",
        value=item_description[:80],
        found_in_source=desc_ok,
        detail=f"{overlap:.0%} of description tokens found in source",
    ))
    if overlap < 0.35:
        flags.append(f"Description has very low overlap with source text ({overlap:.0%})")
        risk_components.append(0.45)
    elif overlap < 0.50:
        flags.append(f"Description has low overlap with source text ({overlap:.0%})")
        risk_components.append(0.20)
    else:
        risk_components.append(0.0)

    # ── 2. Item number ────────────────────────────────────────────────────────
    if item_number:
        found = item_number.lower() in _normalize(raw_text)
        checks.append(FieldCheck(
            field="item_number",
            value=item_number,
            found_in_source=found,
            detail="Item number found verbatim in source" if found else "Item number absent from source text",
        ))
        if not found:
            flags.append(f"Item number '{item_number}' not found in source — may be fabricated")
            risk_components.append(0.25)
        else:
            risk_components.append(0.0)

    # ── 3. MPN (highest risk — LLM explicitly told not to guess) ─────────────
    if mpn:
        found = mpn.lower() in _normalize(raw_text)
        checks.append(FieldCheck(
            field="manufacturer_part_number",
            value=mpn,
            found_in_source=found,
            detail="MPN found verbatim in source" if found else "MPN absent from source text — possible hallucination",
        ))
        if not found:
            flags.append(
                f"MPN '{mpn}' not found in source text — "
                "LLM was instructed not to guess MPNs; this may be fabricated"
            )
            risk_components.append(0.55)   # highest weight
        else:
            risk_components.append(0.0)

    # ── 4. Unit price ─────────────────────────────────────────────────────────
    if raw_unit_price is not None:
        found = _price_in_text(raw_unit_price, raw_text)
        checks.append(FieldCheck(
            field="unit_price",
            value=f"{raw_unit_price:.4f}",
            found_in_source=found,
            detail="Unit price found in source" if found else "Unit price not found in source text",
        ))
        if not found:
            flags.append(f"Unit price ${raw_unit_price:.4f} not found in source text")
            risk_components.append(0.20)
        else:
            risk_components.append(0.0)

    # ── 5. Line total arithmetic cross-check ─────────────────────────────────
    if raw_unit_price is not None and raw_quantity is not None and raw_line_total is not None:
        expected = round(raw_unit_price * raw_quantity, 2)
        actual   = round(raw_line_total, 2)
        match    = abs(expected - actual) <= max(0.02, actual * 0.001)
        checks.append(FieldCheck(
            field="line_total_arithmetic",
            value=f"{raw_quantity} × ${raw_unit_price:.4f} = ${expected:.2f} (invoice: ${actual:.2f})",
            found_in_source=match,
            detail="Arithmetic checks out" if match else f"Expected ${expected:.2f} but invoice shows ${actual:.2f}",
        ))
        if not match:
            flags.append(
                f"Arithmetic mismatch: {raw_quantity} × ${raw_unit_price:.4f} "
                f"= ${expected:.2f} ≠ ${actual:.2f} on invoice"
            )
            risk_components.append(0.30)
        else:
            risk_components.append(0.0)

    # ── Aggregate risk ────────────────────────────────────────────────────────
    risk_score = round(min(sum(risk_components), 1.0), 3)
    risk_level = (
        "high"   if risk_score >= 0.50 else
        "medium" if risk_score >= 0.20 else
        "low"
    )

    return ItemHallucinationReport(
        item_index=item_index,
        item_description=item_description,
        risk_score=risk_score,
        risk_level=risk_level,
        flags=flags,
        checks=checks,
    )


# ─── Invoice-level checker ────────────────────────────────────────────────────

def check_invoice(result_dict: dict) -> list[dict]:
    """
    Run hallucination checks on all line items in an InvoiceResult dict.
    Returns a serializable list of per-item reports.
    """
    raw_text   = result_dict.get("raw_text") or ""
    line_items = result_dict.get("line_items", [])

    reports = []
    for i, item in enumerate(line_items):
        report = check_item(
            raw_text=raw_text,
            item_description=item.get("item_description", ""),
            item_number=item.get("item_number"),
            mpn=item.get("manufacturer_part_number"),
            raw_unit_price=item.get("raw_unit_price"),
            raw_quantity=item.get("raw_quantity"),
            raw_line_total=item.get("raw_line_total"),
            item_index=i,
        )
        reports.append({
            "item_index":       report.item_index,
            "item_description": report.item_description,
            "risk_score":       report.risk_score,
            "risk_level":       report.risk_level,
            "flags":            report.flags,
            "checks": [
                {
                    "field":           c.field,
                    "value":           c.value,
                    "found_in_source": c.found_in_source,
                    "detail":          c.detail,
                }
                for c in report.checks
            ],
        })

    return reports


def summarize_hallucination_report(reports: list[dict]) -> dict:
    """Aggregate stats across all item reports."""
    if not reports:
        return {"total": 0, "high_risk": 0, "medium_risk": 0, "low_risk": 0, "avg_risk_score": 0.0}
    high   = sum(1 for r in reports if r["risk_level"] == "high")
    medium = sum(1 for r in reports if r["risk_level"] == "medium")
    low    = sum(1 for r in reports if r["risk_level"] == "low")
    avg    = round(sum(r["risk_score"] for r in reports) / len(reports), 3)
    return {
        "total":       len(reports),
        "high_risk":   high,
        "medium_risk": medium,
        "low_risk":    low,
        "avg_risk_score": avg,
    }
