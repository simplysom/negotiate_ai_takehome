"""
PDF extraction layer.
Uses pdfplumber for layout-aware text + table extraction.
Returns raw text suitable for downstream LLM parsing.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pdfplumber


def _clean_text(text: str) -> str:
    """Light cleaning: collapse excessive whitespace, normalize line endings."""
    # Collapse runs of spaces to a single space (keep newlines)
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _table_to_text(table: list[list[Optional[str]]]) -> str:
    """Serialize a pdfplumber table to a readable pipe-delimited string."""
    rows = []
    for row in table:
        cells = [str(c).strip() if c else "" for c in row]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def extract_pdf_text(pdf_path: str | Path) -> str:
    """
    Extract all text from a PDF, interleaving raw page text with any
    detected table content.  Returns a single consolidated string.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pages_text: list[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            parts: list[str] = [f"=== PAGE {page_num} ==="]

            # Raw text
            raw = page.extract_text(x_tolerance=3, y_tolerance=3)
            if raw:
                parts.append(_clean_text(raw))

            # Tables (often more accurate than raw text for line-item grids)
            tables = page.extract_tables()
            if tables:
                for t_idx, table in enumerate(tables, start=1):
                    if any(any(cell for cell in row) for row in table):
                        parts.append(f"-- TABLE {t_idx} --")
                        parts.append(_table_to_text(table))

            pages_text.append("\n".join(parts))

    return "\n\n".join(pages_text)


def get_pdf_metadata(pdf_path: str | Path) -> dict:
    """Return basic file metadata (name, size, page count)."""
    pdf_path = Path(pdf_path)
    with pdfplumber.open(str(pdf_path)) as pdf:
        return {
            "file_name": pdf_path.name,
            "file_size_bytes": pdf_path.stat().st_size,
            "page_count": len(pdf.pages),
        }
