"""
LLM-powered invoice parser.

Sends raw invoice text to Claude via tool-use, receiving back a structured
list of line items.  The tool schema acts as a hard output contract so we
never get free-form prose back from the model.
"""
from __future__ import annotations

from typing import Optional

import anthropic

from backend.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from backend.pipeline.models import RawLineItem


# ─── Tool schema ──────────────────────────────────────────────────────────────

_EXTRACT_TOOL = {
    "name": "extract_invoice",
    "description": (
        "Extract all line items from an invoice document. "
        "Return exactly the fields requested. Do not invent values — "
        "use null when a field is genuinely absent from the document."
    ),
    "input_schema": {
        "type": "object",
        "required": ["supplier_name", "invoice_number", "invoice_date", "line_items"],
        "properties": {
            "supplier_name": {
                "type": "string",
                "description": "Vendor / supplier name as printed on the invoice.",
            },
            "invoice_number": {
                "type": ["string", "null"],
                "description": "Invoice number or document ID.",
            },
            "invoice_date": {
                "type": ["string", "null"],
                "description": "Invoice date, in whatever format appears on the document.",
            },
            "line_items": {
                "type": "array",
                "description": "One element per line item on the invoice.",
                "items": {
                    "type": "object",
                    "required": ["item_description"],
                    "properties": {
                        "item_description": {
                            "type": "string",
                            "description": "Full product description, cleaned of OCR noise.",
                        },
                        "item_number": {
                            "type": ["string", "null"],
                            "description": "Supplier item number / SKU / catalog number.",
                        },
                        "manufacturer_part_number": {
                            "type": ["string", "null"],
                            "description": (
                                "Manufacturer part number (MPN / Mfr#). "
                                "Must appear explicitly on the invoice. "
                                "Return null if absent — do NOT guess."
                            ),
                        },
                        "original_uom": {
                            "type": ["string", "null"],
                            "description": (
                                "Unit of measure exactly as printed (e.g. EA, CS, DZ, PK, BX). "
                                "Return null if genuinely absent."
                            ),
                        },
                        "pack_expression": {
                            "type": ["string", "null"],
                            "description": (
                                "Any pack-size expression embedded in the description, "
                                "e.g. '25/CS', '12PR/PK', 'PK10', '1000 EA', '100/BX 8 BX/CS'. "
                                "Copy the raw expression verbatim; return null if absent."
                            ),
                        },
                        "quantity_ordered": {
                            "type": ["number", "null"],
                            "description": "Quantity ordered (the number of invoiced units).",
                        },
                        "unit_price": {
                            "type": ["number", "null"],
                            "description": "Price per invoiced unit (before any multiplier).",
                        },
                        "line_total": {
                            "type": ["number", "null"],
                            "description": "Line extension total (qty × unit price).",
                        },
                    },
                },
            },
        },
    },
}

_SYSTEM_PROMPT = """\
You are an expert invoice parsing assistant for a procurement data team.

Your job is to extract every line item from a supplier invoice with maximum accuracy.

Rules:
1. Extract ALL line items — do not skip any, even if they look like service charges or fees.
2. Clean obvious OCR noise from descriptions (garbled chars, double spaces) but preserve product names.
3. NEVER invent manufacturer part numbers (MPN). Only extract MPNs that are explicitly labeled
   "Mfr#", "MPN", "Mfr Part#", "Part No.", or similar on the invoice. Set to null otherwise.
4. Capture pack expressions verbatim (e.g. "25/CS", "12PR/PK", "PK10", "100/BX 8 BX/CS").
5. If a field is not present on the invoice, return null — do not guess.
6. For items listed with "X @ $Y" notation, quantity = X and unit_price = Y.
7. PRICE PER HUNDRED ("Price/Hundred", "Price/C", "/M", "per 100"): Some invoices—especially
   vending or industrial distributors—list prices per 100 units in a "Price/Hundred" or "Price/C"
   column. When you detect this column format:
     a. Set unit_price = (column value) / 100  (e.g. 195.0000 → 1.95).
     b. Leave pack_expression as null — the price is already normalized to per-unit.
     c. Verify your interpretation: qty_shipped × unit_price should equal the line Amount column.
8. When an invoice has separate "Qty Ordered", "Qty Shipped", and "Qty Backordered" columns,
   use the SHIPPED quantity as quantity_ordered.
9. "Control No." or "Control #" is the supplier item number (item_number field).
   "Part No." or "Part #" is typically the manufacturer part number (manufacturer_part_number).
10. Truncated descriptions (OCR cut-off) are acceptable — extract as much text as is visible.
11. "Location: N pcs / pack" lines in vending invoices are SECTION HEADERS, not pack expressions.
    Do not capture them as pack_expression. Set pack_expression = null for those items.
12. When a price is already normalized to per-unit (via rule 7), set pack_expression = null.
"""


def parse_invoice(
    invoice_text: str,
) -> tuple[str, Optional[str], Optional[str], list[RawLineItem]]:
    """
    Call Claude to extract structured line items from raw invoice text.

    Returns:
        (supplier_name, invoice_number, invoice_date, line_items)
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Copy .env.example to .env and add your key."
        )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        timeout=120.0,
        system=_SYSTEM_PROMPT,
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_invoice"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Please extract all line items from the following invoice document:\n\n"
                    + invoice_text
                ),
            }
        ],
    )

    tool_block = next(
        (b for b in response.content if b.type == "tool_use"),
        None,
    )
    if tool_block is None:
        raise ValueError("Claude did not return a tool-use block. Raw: " + str(response))

    data: dict = tool_block.input

    supplier_name: str        = data.get("supplier_name", "Unknown Supplier")
    invoice_number: Optional[str] = data.get("invoice_number")
    invoice_date:   Optional[str] = data.get("invoice_date")

    raw_items: list[RawLineItem] = []
    for item_dict in data.get("line_items", []):
        try:
            raw_items.append(RawLineItem(**item_dict))
        except Exception:
            continue

    return supplier_name, invoice_number, invoice_date, raw_items
