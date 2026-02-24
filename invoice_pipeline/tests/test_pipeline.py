"""
End-to-end integration test for the invoice pipeline.

Mocks the LLM parser and lookup so the full normalization, scoring, and
output generation can be validated without an API key or network access.

Run from the project root:
  .venv/bin/python tests/test_pipeline.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

# Add the project root to sys.path so backend.* is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.pipeline.models import InvoiceResult, RawLineItem
from backend.pipeline.processor import run_pipeline, save_result

# ─── Mock data ────────────────────────────────────────────────────────────────

MOCK_SUPPLIER     = "MSC Industrial Supply Co."
MOCK_INVOICE_NUM  = "92022099"
MOCK_DATE         = "04/15/25"

MOCK_RAW_ITEMS: list[RawLineItem] = [
    # Direct EA — no pack expression
    RawLineItem(
        item_description="COTTON/POLY STRING KNIT GLOVES GRY L/XL",
        item_number="35-C410/S",
        original_uom="EA",
        quantity_ordered=200.0, unit_price=0.37, line_total=74.00,
    ),
    # EA with MPN present (confidence bonus)
    RawLineItem(
        item_description="CLR LENS CLR FRAME INTRUDER SAFETY GLASSES",
        item_number="68912609", manufacturer_part_number="S4110S",
        original_uom="EA",
        quantity_ordered=96.0, unit_price=0.73, line_total=70.08,
    ),
    # Pack expression in description: 100/BX → pack_qty=100
    RawLineItem(
        item_description="BOX 100 PR CORDED MOLDEX EARPLUGS",
        item_number="06506349", manufacturer_part_number="6654",
        original_uom="EA", pack_expression="100/BX",
        quantity_ordered=6.0, unit_price=29.64, line_total=177.84,
    ),
    # BX UOM + 100/BX expression
    RawLineItem(
        item_description="3.5ML BLK LRG 100/BX ONYX PWDR FRNT TRL EXAM GLOVES",
        item_number="60399433", manufacturer_part_number="N643",
        original_uom="BX", pack_expression="100/BX",
        quantity_ordered=10.0, unit_price=17.37, line_total=173.70,
    ),
    # Compound: 12PR/PK → pack_qty=24 EA
    RawLineItem(
        item_description="FOAM NITRILE GLOVES LARGE",
        item_number="MAG100FN",
        original_uom="PK", pack_expression="12PR/PK",
        quantity_ordered=5.0, unit_price=14.40, line_total=72.00,
    ),
    # Nested: 100/BX 8 BX/CS → pack_qty=800 EA
    RawLineItem(
        item_description="3M SAFETY GLASS WIPES 100/BX 8 BX/CS",
        item_number="S-14835",
        original_uom="CS", pack_expression="100/BX 8 BX/CS",
        quantity_ordered=1.0, unit_price=32.00, line_total=32.00,
    ),
    # Arc Flash Kit — EA with MPN
    RawLineItem(
        item_description="Arc Flash Clothing Kit, Navy, 2X",
        item_number="819X89", manufacturer_part_number="ARC40KITNG-2X",
        original_uom="EA",
        quantity_ordered=1.0, unit_price=2890.20, line_total=2890.20,
    ),
    # Embedded "144 EA" → price/144 = $2.50/EA
    RawLineItem(
        item_description="Apache Clear-Frame Safety Glasses 144 EA",
        original_uom="EA", pack_expression="144 EA",
        quantity_ordered=1.0, unit_price=360.00, line_total=360.00,
    ),
    # Missing UOM → triggers lookup → resolved
    RawLineItem(
        item_description="Blue Nitrile Gloves Large",
        item_number="NITL-BL-L",
        original_uom=None,
        quantity_ordered=2.0, unit_price=18.50, line_total=37.00,
    ),
    # CS with no pack qty → lookup fails → escalated
    RawLineItem(
        item_description="Denatured Alcohol Cleaning Solution",
        item_number="DA-500",
        original_uom="CS",
        quantity_ordered=1.0, unit_price=45.00, line_total=45.00,
    ),
]


def _mock_parse_invoice(_text: str):
    return MOCK_SUPPLIER, MOCK_INVOICE_NUM, MOCK_DATE, MOCK_RAW_ITEMS


def _mock_lookup(description, mpn=None, item_number=None, supplier=None):
    from backend.pipeline.models import LookupResult
    if "nitrile" in description.lower():
        return LookupResult(
            found=True, pack_quantity=100, uom="BX",
            source_url="https://example.com/nitl-bl-l",
            source_snippet="Blue Nitrile Gloves Large — sold in boxes of 100",
            confidence=0.78,
            notes="Matched exact SKU on distributor page.",
        )
    return LookupResult(found=False, notes="No clear pack size found.")


# ─── Test runner ─────────────────────────────────────────────────────────────

def run_tests() -> None:
    print("=" * 70)
    print("  Invoice Pipeline — Integration Test")
    print("=" * 70)

    pdf_path = (
        Path(__file__).parent.parent.parent
        / "Invoices_1"
        / "2700-APUSBWAY_23811_92022099_496ef_page_1_1.pdf"
    )

    with (
        patch("backend.pipeline.processor.parse_invoice",   side_effect=_mock_parse_invoice),
        patch("backend.pipeline.processor.lookup_pack_info", side_effect=_mock_lookup),
    ):
        result: InvoiceResult = run_pipeline(
            pdf_path if pdf_path.exists() else Path(__file__),  # extractor fallback
            progress_cb=print,
        )

    print()
    print("-" * 70)
    print(f"Supplier : {result.supplier_name}")
    print(f"Invoice  : {result.invoice_number}  Date: {result.invoice_date}")
    print(f"Summary  : {result.summary}")
    print()

    header = f"{'Description':<43} {'UOM':<5} {'Pck':>4} {'$/EA':>10} {'Conf':>5} {'Esc':>4} {'Source'}"
    print(header)
    print("-" * len(header))
    for item in result.line_items:
        esc = "YES" if item.escalation_flag else "no"
        ppe = f"${item.price_per_base_unit:.4f}" if item.price_per_base_unit else "N/A"
        print(
            f"{item.item_description[:43]:<43} "
            f"{item.original_uom or '?':<5} "
            f"{str(item.detected_pack_quantity or '?'):>4} "
            f"{ppe:>10} "
            f"{item.confidence_score:>5.2f} "
            f"{esc:>4}  "
            f"{item.uom_source.value}"
        )

    items = result.line_items

    # ── Assertions ────────────────────────────────────────────────────────────
    assert items[0].price_per_base_unit == 0.37,                   "item0 $/EA"
    assert items[2].detected_pack_quantity == 100,                  "item2 pack_qty"
    assert abs(items[2].price_per_base_unit - 0.2964) < 0.001,     "item2 $/EA"
    assert items[3].detected_pack_quantity == 100,                  "item3 pack_qty"
    assert abs(items[3].price_per_base_unit - 0.1737) < 0.001,     "item3 $/EA"
    assert items[4].detected_pack_quantity == 24,                   "item4 12PR/PK=24EA"
    assert abs(items[4].price_per_base_unit - (14.40 / 24)) < 0.001, "item4 $/EA"
    assert items[5].detected_pack_quantity == 800,                  "item5 nested=800EA"
    assert abs(items[5].price_per_base_unit - (32.00 / 800)) < 0.001, "item5 $/EA"
    assert abs(items[7].price_per_base_unit - 2.50) < 0.001,       "item7 144EA=$2.50"
    assert items[8].uom_source.value == "lookup_web",              "item8 lookup"
    assert items[8].detected_pack_quantity == 100,                  "item8 pack from lookup"
    assert items[9].escalation_flag,                               "item9 escalated"

    # Save output to data/output/
    out = Path(__file__).parent.parent / "data" / "output"
    out.mkdir(parents=True, exist_ok=True)
    out_path = save_result(result, out)
    print(f"\n✅ All assertions passed!\nJSON saved to: {out_path}")

    print("\nSample JSON (first 2 items):")
    print(json.dumps(
        [item.model_dump() for item in items[:2]],
        indent=2, default=str,
    ))


if __name__ == "__main__":
    run_tests()
