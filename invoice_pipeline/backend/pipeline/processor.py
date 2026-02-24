"""
Pipeline orchestrator — integrates all backend modules.

Flow for each PDF:
  1. Extract raw text        (extractor)
  2. Parse line items        (parser / LLM)
  3. Normalize UOM + pack    (normalizer — deterministic)
  4. Agentic lookup if needed(lookup)
  5. Score confidence        (scorer)
  6. Return InvoiceResult    (models)
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait, FIRST_COMPLETED
from pathlib import Path
from typing import Callable, Optional

from backend.config import ENABLE_LOOKUP
from backend.pipeline.extractor           import extract_pdf_text
from backend.pipeline.hallucination_checker import check_invoice
from backend.pipeline.lookup              import lookup_pack_info, should_trigger_lookup
from backend.pipeline.models              import InvoiceLineItem, InvoiceResult, RawLineItem, UOMSource
from backend.pipeline.normalizer          import canonicalize_uom, compute_price_per_ea, parse_pack_expression
from backend.pipeline.parser              import parse_invoice
from backend.pipeline.scorer              import ocr_noise_penalty, score_line_item

# Hard timeout per line-item (covers web lookup + LLM); after this we use raw invoice values
_ITEM_TIMEOUT_SECS = 120


# ─── Fallback item builder ────────────────────────────────────────────────────

def _make_fallback_item(
    raw: RawLineItem,
    supplier_name: str,
    invoice_number: Optional[str],
    invoice_date: Optional[str],
    reason: str = "processing error",
) -> InvoiceLineItem:
    """Return a minimal InvoiceLineItem using only raw invoice values (confidence 0.0)."""
    return InvoiceLineItem(
        supplier_name=supplier_name,
        item_description=raw.item_description,
        manufacturer_part_number=raw.manufacturer_part_number,
        original_uom=raw.original_uom,
        detected_pack_quantity=None,
        canonical_base_uom=raw.original_uom or "EA",
        price_per_base_unit=raw.unit_price,   # use raw price, unmodified
        confidence_score=0.0,
        uom_source=UOMSource.MISSING,
        raw_unit_price=raw.unit_price,
        raw_quantity=raw.quantity_ordered,
        raw_line_total=raw.line_total,
        item_number=raw.item_number,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        line_total_check=None,
        lookup_notes=f"[fallback] {reason}",
    )


# ─── Item normalizer ──────────────────────────────────────────────────────────

def _normalize_item(
    raw: RawLineItem,
    supplier_name: str,
    invoice_number: Optional[str],
    invoice_date: Optional[str],
    progress_cb: Optional[Callable[[str], None]] = None,
) -> InvoiceLineItem:

    def log(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    # 1. Canonicalize UOM from invoice column
    canonical_uom = canonicalize_uom(raw.original_uom) if raw.original_uom else None

    # 2. Parse pack expression from description / explicit field
    search_text = " ".join(filter(None, [raw.pack_expression, raw.item_description]))
    pack_info   = parse_pack_expression(search_text)

    detected_pack_qty = pack_info.pack_qty
    effective_uom     = canonical_uom or (pack_info.container_uom or None)

    # 3. Compute price per EA
    price_per_ea, base_uom = compute_price_per_ea(
        raw.unit_price, effective_uom, detected_pack_qty
    )

    # 4. UOM source
    if raw.original_uom is not None:
        uom_source = UOMSource.INVOICE_DIRECT
    elif pack_info.matched_expression:
        uom_source = UOMSource.INFERRED
    else:
        uom_source = UOMSource.MISSING

    lookup_result = None
    lookup_notes: Optional[str] = None

    # 5. Agentic lookup if needed
    if ENABLE_LOOKUP and should_trigger_lookup(effective_uom, detected_pack_qty, price_per_ea):
        log(f"  [lookup] Searching web for pack/UOM: {raw.item_description[:55]}…")
        lookup_result = lookup_pack_info(
            description=raw.item_description,
            mpn=raw.manufacturer_part_number,
            item_number=raw.item_number,
            supplier=supplier_name,
        )
        if lookup_result.found:
            if lookup_result.uom and not canonical_uom:
                effective_uom = canonicalize_uom(lookup_result.uom) or lookup_result.uom
            if lookup_result.pack_quantity and not detected_pack_qty:
                detected_pack_qty = lookup_result.pack_quantity
            price_per_ea, base_uom = compute_price_per_ea(
                raw.unit_price, effective_uom, detected_pack_qty
            )
            uom_source   = UOMSource.LOOKUP_WEB
            lookup_notes = (
                f"Source: {lookup_result.source_url or 'web'}. "
                f"Snippet: {lookup_result.source_snippet[:120]}. "
                f"Notes: {lookup_result.notes}"
            )
            log(
                f"  [lookup] Found — {lookup_result.pack_quantity or '?'}/{lookup_result.uom or '?'}"
                f" (conf {lookup_result.confidence:.2f})"
            )
        else:
            lookup_notes = f"Lookup found nothing useful. {lookup_result.notes}"
            log("  [lookup] Nothing useful found — using original values")

    # 6. Score
    noise_mult   = ocr_noise_penalty(raw.item_description)
    lookup_conf  = lookup_result.confidence if lookup_result else 0.0

    score, line_total_check = score_line_item(
        uom_source=uom_source,
        original_uom=effective_uom,
        pack_qty=detected_pack_qty,
        price_per_ea=price_per_ea,
        raw_unit_price=raw.unit_price,
        raw_quantity=raw.quantity_ordered,
        raw_line_total=raw.line_total,
        mpn_present=bool(raw.manufacturer_part_number),
        pack_expression=pack_info.matched_expression,
        lookup_confidence=lookup_conf,
    )
    score = round(score * noise_mult, 4)

    return InvoiceLineItem(
        supplier_name=supplier_name,
        item_description=raw.item_description,
        manufacturer_part_number=raw.manufacturer_part_number,
        original_uom=raw.original_uom,
        detected_pack_quantity=detected_pack_qty,
        canonical_base_uom=base_uom,
        price_per_base_unit=price_per_ea,
        confidence_score=score,
        uom_source=uom_source,
        raw_unit_price=raw.unit_price,
        raw_quantity=raw.quantity_ordered,
        raw_line_total=raw.line_total,
        item_number=raw.item_number,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        line_total_check=line_total_check,
        lookup_notes=lookup_notes,
    )


# ─── Public API ───────────────────────────────────────────────────────────────

def run_pipeline(
    pdf_path: str | Path,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> InvoiceResult:
    """Full end-to-end pipeline for a single PDF invoice."""
    pdf_path = Path(pdf_path)

    def log(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    log(f"[1/5] Extracting text from {pdf_path.name}…")
    invoice_text = extract_pdf_text(pdf_path)
    word_count = len(invoice_text.split())
    log(f"      → Extracted {word_count:,} words across {invoice_text.count(chr(12)) + 1} page(s)")

    log("[2/5] Parsing line items with Claude…")
    log("      Sending invoice text to Claude (tool-use extraction)…")
    log("      This may take 15–45 s depending on invoice length…")
    supplier_name, invoice_number, invoice_date, raw_items = parse_invoice(invoice_text)
    log(f"      → Supplier : {supplier_name}")
    log(f"      → Invoice# : {invoice_number or '(not found)'}")
    log(f"      → Date     : {invoice_date or '(not found)'}")
    log(f"      → Items    : {len(raw_items)} line item(s) extracted")

    log("[3/5] Normalizing UOM and pricing…")
    normalized: list[InvoiceLineItem] = []
    total_items = len(raw_items)

    def _log_item_result(item: InvoiceLineItem) -> None:
        """Emit a one-line summary of what was resolved for a line item."""
        uom   = item.canonical_base_uom or item.original_uom or "UOM?"
        pack  = f" ×{item.detected_pack_quantity}" if item.detected_pack_quantity else ""
        price = f"${item.price_per_base_unit:.4f}/EA" if item.price_per_base_unit is not None else "no price"
        conf  = f"{item.confidence_score:.2f}"
        flag  = " ⚠ ESCALATED" if item.escalation_flag else ""
        log(f"    → {uom}{pack} · {price} · conf {conf}{flag}")

    if total_items <= 1:
        # No benefit from a thread pool for 0 or 1 items
        for i, raw in enumerate(raw_items, start=1):
            log(f"  Item {i}/{total_items}: {raw.item_description[:55]}…")
            try:
                item = _normalize_item(raw, supplier_name, invoice_number, invoice_date, progress_cb)
            except Exception as exc:
                log(f"  ⚠ Item {i}/{total_items}: error — using invoice values ({exc})")
                item = _make_fallback_item(raw, supplier_name, invoice_number, invoice_date, str(exc))
            _log_item_result(item)
            normalized.append(item)
    else:
        # Parallel normalization — each item is independent; I/O-bound (LLM + web)
        max_workers = min(4, total_items)
        results_map: dict[int, InvoiceLineItem] = {}

        def _normalize_indexed(args: tuple[int, RawLineItem]) -> tuple[int, InvoiceLineItem]:
            idx, raw = args
            log(f"  Item {idx}/{total_items}: {raw.item_description[:55]}…")
            item = _normalize_item(raw, supplier_name, invoice_number, invoice_date, progress_cb)
            _log_item_result(item)
            return idx, item

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = {
                executor.submit(_normalize_indexed, (i, raw)): i
                for i, raw in enumerate(raw_items, start=1)
            }
            submit_times = {f: time.time() for f in futures}
            remaining = set(futures)
            last_heartbeat = time.time()

            while remaining:
                done, remaining = futures_wait(remaining, timeout=10.0, return_when=FIRST_COMPLETED)

                for fut in done:
                    idx = futures[fut]
                    try:
                        _, item = fut.result()
                        results_map[idx] = item
                    except Exception as exc:
                        log(f"  ⚠ Item {idx}/{total_items}: error — using invoice values ({exc})")
                        results_map[idx] = _make_fallback_item(
                            raw_items[idx - 1], supplier_name, invoice_number, invoice_date, str(exc)
                        )

                now = time.time()

                # Enforce per-item hard timeout — abandon stalled threads gracefully
                timed_out = {f for f in remaining if now - submit_times[f] > _ITEM_TIMEOUT_SECS}
                for fut in timed_out:
                    idx = futures[fut]
                    log(f"  ⚠ Item {idx}/{total_items}: web lookup timed out — using invoice values")
                    results_map[idx] = _make_fallback_item(
                        raw_items[idx - 1], supplier_name, invoice_number, invoice_date,
                        "lookup timed out after 120 s"
                    )
                    remaining.discard(fut)

                # Heartbeat every 15 s so the UI doesn't appear frozen
                if remaining and now - last_heartbeat > 15:
                    last_heartbeat = now
                    waiting_idxs = sorted(futures[f] for f in remaining)
                    log(f"  ⏳ Waiting for web lookup on item(s) {waiting_idxs}… (may take up to 2 min)")

        finally:
            executor.shutdown(wait=False)  # release threads; stragglers run to completion in bg

        normalized = [results_map[i] for i in range(1, total_items + 1)]

    log(f"[4/5] Building result… ({len(normalized)} items normalized)")
    result = InvoiceResult(
        invoice_file=pdf_path.name,
        supplier_name=supplier_name,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        line_items=normalized,
        raw_text=invoice_text,
    )
    result.build_summary()

    log("[5/5] Running hallucination checks…")
    log("      Cross-referencing extracted values against source PDF…")
    result.hallucination_report = check_invoice(result.model_dump())

    h_high   = sum(1 for r in result.hallucination_report if r.get("risk_level") == "high")
    h_medium = sum(1 for r in result.hallucination_report if r.get("risk_level") == "medium")
    esc      = result.summary.get("escalated_items", 0)
    log(f"      → Hallucination: {h_high} high-risk, {h_medium} medium-risk items")
    log(f"Done. {len(normalized)} items processed · {esc} escalated for review.")
    return result


def save_result(result: InvoiceResult, output_dir: str | Path) -> Path:
    """Serialize InvoiceResult to JSON and write to output_dir."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem     = Path(result.invoice_file).stem
    out_path = output_dir / f"{stem}_output.json"
    out_path.write_text(
        json.dumps(result.model_dump(), indent=2, default=str),
        encoding="utf-8",
    )
    return out_path
