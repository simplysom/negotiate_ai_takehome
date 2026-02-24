"""
Pydantic data models for the invoice processing pipeline.
All outputs conform to these schemas — downstream consumers can rely on them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class UOMSource(str, Enum):
    """Where did we obtain the UOM / pack information?"""
    INVOICE_DIRECT = "invoice_direct"   # Clearly printed on the invoice
    LOOKUP_WEB     = "lookup_web"       # Resolved via agentic web search
    INFERRED       = "inferred"         # Inferred from description text
    MISSING        = "missing"          # Could not determine


class LookupResult(BaseModel):
    """Structured result returned by the agentic lookup agent."""
    found: bool = False
    pack_quantity: Optional[int] = None
    uom: Optional[str] = None
    source_url: Optional[str] = None
    source_snippet: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = ""


class RawLineItem(BaseModel):
    """Raw line item as extracted by the LLM parser — before normalization."""
    item_description: str
    item_number: Optional[str] = None
    manufacturer_part_number: Optional[str] = None
    original_uom: Optional[str] = None
    pack_expression: Optional[str] = None
    quantity_ordered: Optional[float] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None


class InvoiceLineItem(BaseModel):
    """
    Fully normalized line item — canonical output schema.
    Every field maps to the specification in the take-home prompt.
    """
    # ── Required output fields ────────────────────────────────────────────────
    supplier_name: str
    item_description: str
    manufacturer_part_number: Optional[str] = None
    original_uom: Optional[str] = None
    detected_pack_quantity: Optional[int] = None
    canonical_base_uom: str = "EA"
    price_per_base_unit: Optional[float] = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    escalation_flag: bool = False

    # ── Traceability metadata ─────────────────────────────────────────────────
    uom_source: UOMSource = UOMSource.MISSING
    raw_unit_price: Optional[float] = None
    raw_quantity: Optional[float] = None
    raw_line_total: Optional[float] = None
    item_number: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    line_total_check: Optional[str] = None   # "ok" | "mismatch" | "unverifiable"
    lookup_notes: Optional[str] = None

    @model_validator(mode="after")
    def _check_escalation(self) -> "InvoiceLineItem":
        from backend.config import ESCALATION_THRESHOLD, MIN_PRICE_PER_EA, MAX_PRICE_PER_EA
        if self.confidence_score < ESCALATION_THRESHOLD:
            self.escalation_flag = True
        if self.price_per_base_unit is None:
            self.escalation_flag = True
        if self.price_per_base_unit is not None:
            if (self.price_per_base_unit < MIN_PRICE_PER_EA
                    or self.price_per_base_unit > MAX_PRICE_PER_EA):
                self.escalation_flag = True
        return self


class InvoiceResult(BaseModel):
    """Top-level output structure for one processed invoice."""
    invoice_file: str
    processed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    supplier_name: str = ""
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    raw_text: Optional[str] = None          # source PDF text for hallucination checking
    hallucination_report: Optional[list] = None

    def build_summary(self) -> None:
        total    = len(self.line_items)
        escalated = sum(1 for i in self.line_items if i.escalation_flag)
        looked_up = sum(1 for i in self.line_items if i.uom_source == UOMSource.LOOKUP_WEB)
        scores    = [i.confidence_score for i in self.line_items]
        self.summary = {
            "total_line_items":          total,
            "escalated_items":           escalated,
            "items_resolved_via_lookup": looked_up,
            "avg_confidence_score":      round(sum(scores) / len(scores), 3) if scores else 0.0,
            "min_confidence_score":      round(min(scores), 3) if scores else 0.0,
        }
