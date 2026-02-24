"""
Agentic UOM / pack-size lookup agent.

When a line item cannot be normalized deterministically (UOM missing or pack
quantity unknown), this module searches the web and uses Claude to interpret
the results.

Search providers (in priority order):
  1. Tavily MCP  — Claude acts as agent, calls Tavily search tool directly
                    via the Anthropic MCP-client beta (TAVILY_MCP_URL in .env)
  2. Tavily SDK  — direct API call, pre-extracts page content
  3. DuckDuckGo  — no key required, fetches pages manually

Safety guardrails:
  - Confidence hard-capped at 0.85 for all web-sourced data.
  - Inference from product-category knowledge is allowed but capped at 0.55.
  - Only positive results (found=True) are cached; failed searches are not,
    so they are always retried on the next run.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Optional

import anthropic
import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    CACHE_DIR,
    CONTAINER_UOMS,
    LOOKUP_MAX_RESULTS,
    TAVILY_API_KEY,
    TAVILY_MCP_URL,
)
from backend.pipeline.models import LookupResult

_CACHE_FILE = CACHE_DIR / "lookup_cache.json"
_CACHE_LOCK = threading.Lock()   # protects concurrent reads/writes from parallel workers
_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (compatible; InvoicePipeline/1.0; "
            "+https://github.com/example/invoice-pipeline)"
        )
    }
)


# ─── Cache helpers ─────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    _CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]


# ─── Query helpers ─────────────────────────────────────────────────────────────

def _build_query(
    description: str,
    mpn: Optional[str],
    item_number: Optional[str],
    supplier: Optional[str],
) -> str:
    """Primary search query — prefers MPN/item number for precision."""
    parts = []
    if mpn:
        parts.append(mpn)
    elif item_number:
        parts.append(item_number)
    parts.append(description[:80])
    if supplier:
        parts.append(supplier)
    parts.append("pack size UOM each quantity")
    return " ".join(parts)


def _build_alt_queries(
    description: str,
    mpn: Optional[str],
    item_number: Optional[str],
    supplier: Optional[str],
) -> list[str]:
    """
    Return up to 3 alternative search strings for products that are hard to find.
    These progressively widen the search.
    """
    queries = []

    # 1. Clean description + "each" — avoids noisy terms like "pack size UOM"
    clean = re.sub(r"\s+", " ", description[:80]).strip()
    queries.append(f'"{clean}" each quantity sold')

    # 2. MPN alone on distributor sites (Grainger, Uline, Fastenal, MSC)
    if mpn:
        queries.append(
            f'{mpn} site:grainger.com OR site:uline.com OR site:fastenal.com OR site:mscdirect.com'
        )
    elif item_number:
        queries.append(f'{item_number} {description[:40]} product specifications')

    # 3. Description + category-specific terms
    queries.append(f'{description[:60]} specifications "sold as" OR "per case" OR "per box" OR "per each"')

    return queries[:3]


# ─── Search providers ──────────────────────────────────────────────────────────

def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search via Tavily SDK.  Returns results with keys: href, title, body.
    Tavily pre-extracts page content so no additional fetch is needed.
    """
    if not TAVILY_API_KEY:
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        response = client.search(
            query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=False,
        )
        results = []
        for r in response.get("results", []):
            results.append({
                "href":  r.get("url", ""),
                "title": r.get("title", ""),
                "body":  r.get("content", ""),
                "score": r.get("score", 0.0),
            })
        return results
    except Exception:
        return []


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo fallback — no key required."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []


def _search(query: str, max_results: int = 5) -> tuple[list[dict], str]:
    """
    Run search via Tavily SDK (preferred) or DuckDuckGo (fallback).
    Returns (results, provider_name).
    """
    if TAVILY_API_KEY:
        results = _tavily_search(query, max_results)
        if results:
            return results, "tavily"

    results = _ddg_search(query, max_results)
    return results, "ddgs"


def _fetch_page_text(url: str, char_limit: int = 3000) -> str:
    """Fetch and clean a web page.  Only used for DDGS results."""
    try:
        resp = _SESSION.get(url, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return re.sub(r"\s+", " ", text)[:char_limit]
    except Exception:
        return ""


# ─── Shared tool schema ────────────────────────────────────────────────────────

_LOOKUP_TOOL = {
    "name": "report_pack_info",
    "description": (
        "Report the pack size and unit-of-measure (UOM) for the product. "
        "Call this when you have evidence from search results OR when you can "
        "make a well-grounded inference from product category knowledge. "
        "Always call this tool — set found=false if genuinely uncertain."
    ),
    "input_schema": {
        "type": "object",
        "required": ["found", "source_snippet", "confidence", "notes"],
        "properties": {
            "found": {
                "type": "boolean",
                "description": (
                    "True if you have clear evidence OR a high-confidence inference. "
                    "False only when you have no basis for a reasonable estimate."
                ),
            },
            "pack_quantity": {
                "type": ["integer", "null"],
                "description": "Number of individual items per selling unit. null if unknown.",
            },
            "uom": {
                "type": ["string", "null"],
                "description": "Unit of measure abbreviation (EA, CS, BX, PK, DZ, PR …). null if unknown.",
            },
            "source_url": {
                "type": ["string", "null"],
                "description": "URL of the source page. null for knowledge-based inferences.",
            },
            "source_snippet": {
                "type": "string",
                "description": (
                    "The exact text from the source supporting the conclusion, "
                    "OR a brief rationale for a knowledge-based inference."
                ),
            },
            "confidence": {
                "type": "number",
                "description": (
                    "Confidence 0–1:\n"
                    "  0.80 — exact product page with explicit pack size\n"
                    "  0.65 — similar/related product with matching pack size\n"
                    "  0.55 — strong knowledge-based inference (e.g., gloves always 100/BX)\n"
                    "  0.45 — weak inference / indirect evidence\n"
                    "  Never exceed 0.85."
                ),
            },
            "notes": {
                "type": "string",
                "description": "Reasoning, caveats, or why found=false.",
            },
        },
    },
}


# ─── LLM interpretation (fallback path) ───────────────────────────────────────

_FALLBACK_SYSTEM = """\
You are a procurement data specialist. Your task: determine the pack size
(how many individual items per selling unit) and the unit of measure (UOM)
for a commercial/industrial product.

Decision rules — apply in order:
1. EXPLICIT MATCH  (confidence 0.75–0.85): The search results contain a page
   for this exact product with a clear pack size stated. Quote the snippet.
2. RELATED MATCH   (confidence 0.60–0.70): A very similar product (same type,
   same manufacturer) shows a pack size that almost certainly applies.
3. CATEGORY INFERENCE (confidence 0.45–0.55): No direct match, but the product
   category has a well-known standard pack size (e.g., disposable gloves → 100/BX,
   AA batteries → 24/PK, copy paper → 500 sheets/RM). Use your knowledge.
4. UNKNOWN (found=false): The product is ambiguous, the pack size varies widely
   in the category, OR you have no reasonable basis for any estimate.

Guardrails:
- Confidence ceiling is 0.85 — these are web sources or inferences.
- If multiple conflicting sizes appear with equal weight, set found=false.
- Always call report_pack_info — never leave without reporting.
"""


def _interpret_with_llm(
    description: str,
    search_results: list[dict],
    page_texts: list[tuple[str, str]],
) -> LookupResult:
    if not ANTHROPIC_API_KEY:
        return LookupResult(notes="ANTHROPIC_API_KEY not set; lookup skipped.")

    context_parts = [f"Product: {description}\n"]
    for r in search_results[:4]:
        body = r.get("body", "")[:1500]
        context_parts.append(
            f"URL: {r.get('href', '')}\n"
            f"Title: {r.get('title', '')}\n"
            f"Content: {body}\n"
        )
    for url, text in page_texts[:2]:
        context_parts.append(f"\nPage content from {url}:\n{text[:2000]}\n")
    context = "\n".join(context_parts)[:8000]

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=768,
            timeout=45.0,
            system=_FALLBACK_SYSTEM,
            tools=[_LOOKUP_TOOL],
            tool_choice={"type": "tool", "name": "report_pack_info"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Determine the pack size and UOM for this product.\n\n"
                        f"Search results:\n{context}"
                    ),
                }
            ],
        )
        tool_block = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            return LookupResult(notes="LLM returned no tool-use block.")

        data: dict = tool_block.input
        return LookupResult(
            found=data.get("found", False),
            pack_quantity=data.get("pack_quantity"),
            uom=data.get("uom"),
            source_url=data.get("source_url"),
            source_snippet=data.get("source_snippet", ""),
            confidence=min(data.get("confidence", 0.0), 0.85),
            notes=data.get("notes", ""),
        )
    except Exception as e:
        return LookupResult(notes=f"LLM lookup error: {e}")


# ─── MCP-enhanced agentic lookup ─────────────────────────────────────────────

_MCP_SYSTEM = """\
You are a procurement data specialist with access to a web search tool.
Your mission: find the pack size and unit-of-measure (UOM) for a commercial
product so an invoice pipeline can compute a price-per-each.

── SEARCH STRATEGY ──────────────────────────────────────────────────────────
1. Start with the MPN or item number if provided — exact product matches are best.
2. Search the product description on distributor sites:
   Grainger, Uline, Fastenal, MSC Industrial, Amazon Business, Home Depot Pro.
3. Try the manufacturer's site if identifiable.
4. If results are irrelevant, try a narrower query (e.g., strip generic words,
   focus on the model number or key product nouns).
5. Make 2–3 searches before concluding.

── REPORTING RULES ───────────────────────────────────────────────────────────
After searching, call report_pack_info:

• EXPLICIT  (confidence 0.75–0.85): Search result shows the exact product with
  a clear pack size. Quote the supporting snippet.

• RELATED   (confidence 0.60–0.70): A closely related product (same line, same
  manufacturer) shows a pack size that almost certainly applies.

• INFERRED  (confidence 0.45–0.55): No direct hit, but the product category has
  a well-known standard (e.g., nitrile exam gloves → 100/BX; copy paper →
  500/RM; AA batteries → 24/PK; trash liners → 100–250/CS). Use this path
  rather than returning found=false for common commodity items.

• UNKNOWN   (found=false): Product is unusual, pack size varies widely in the
  category, OR search results are completely irrelevant/empty.

── GUARDRAILS ────────────────────────────────────────────────────────────────
- Confidence ceiling is 0.85.
- If results are clearly about a different product, keep searching.
- You MUST call report_pack_info before finishing — never end without it.
"""


def _lookup_with_mcp(
    description: str,
    mpn: Optional[str],
    item_number: Optional[str],
    supplier: Optional[str],
) -> Optional[LookupResult]:
    """
    Agentic lookup: Claude + Tavily remote MCP server.

    The Anthropic API executes all Tavily search calls server-side within one
    request/response cycle.  Claude can call the search tool multiple times
    before calling report_pack_info.

    Returns None only on a hard API error so the caller can fall back.
    """
    if not (ANTHROPIC_API_KEY and TAVILY_MCP_URL):
        return None

    query = _build_query(description, mpn, item_number, supplier)
    alt_queries = _build_alt_queries(description, mpn, item_number, supplier)

    user_content = (
        f"Find the pack size and UOM for this product.\n\n"
        f"Description : {description}"
        + (f"\nMPN        : {mpn}" if mpn else "")
        + (f"\nItem number: {item_number}" if item_number else "")
        + (f"\nSupplier   : {supplier}" if supplier else "")
        + f"\n\nSuggested queries to try (in order):\n"
        + "\n".join(f"  {i+1}. {q}" for i, q in enumerate([query] + alt_queries))
        + "\n\nSearch for this product now. Try at least 2 queries. "
        "Then call report_pack_info with your findings."
    )

    messages: list[dict] = [{"role": "user", "content": user_content}]
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for _turn in range(6):
        try:
            resp = client.beta.messages.create(  # type: ignore[attr-defined]
                model=ANTHROPIC_MODEL,
                max_tokens=4096,
                timeout=60.0,
                system=_MCP_SYSTEM,
                tools=[_LOOKUP_TOOL],
                mcp_servers=[{"type": "url", "url": TAVILY_MCP_URL, "name": "tavily"}],
                betas=["mcp-client-2025-04-04"],
                messages=messages,
            )
        except Exception:
            # Connection/timeout/API error — return None so caller uses fallback
            return None

        # ── Check for our report_pack_info tool call ──────────────────────────
        report_block = next(
            (
                b for b in resp.content
                if getattr(b, "type", None) == "tool_use"
                and b.name == "report_pack_info"
            ),
            None,
        )
        if report_block:
            d = report_block.input
            return LookupResult(
                found=d.get("found", False),
                pack_quantity=d.get("pack_quantity"),
                uom=d.get("uom"),
                source_url=d.get("source_url"),
                source_snippet=d.get("source_snippet", ""),
                confidence=min(d.get("confidence", 0.0), 0.85),
                notes=d.get("notes", ""),
            )

        # ── Handle stop reasons that don't include report_pack_info ──────────
        if resp.stop_reason in ("end_turn", "max_tokens"):
            # Claude finished (or was cut short) without calling report_pack_info.
            # Nudge it once more.
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({
                "role": "user",
                "content": (
                    "You haven't called report_pack_info yet. "
                    "Based on your search findings, call it now. "
                    "If the searches returned nothing useful, still call it with "
                    "found=false and explain why."
                ),
            })
            continue

        # stop_reason == "tool_use" for a non-report block (MCP tool calls are
        # handled server-side and normally won't appear here, but be defensive).
        messages.append({"role": "assistant", "content": resp.content})

    return LookupResult(notes="[mcp] report_pack_info not called after max turns.")


# ─── Public API ────────────────────────────────────────────────────────────────

def lookup_pack_info(
    description: str,
    mpn: Optional[str] = None,
    item_number: Optional[str] = None,
    supplier: Optional[str] = None,
) -> LookupResult:
    """Attempt to resolve pack size / UOM via web search + LLM."""
    query = _build_query(description, mpn, item_number, supplier)
    key   = _cache_key(query)

    # ── Cache: only positive results are cached; failures are always retried ──
    # Lock protects the read-check so parallel workers don't duplicate work.
    with _CACHE_LOCK:
        cache = _load_cache()
        if key in cache and cache[key].get("found"):
            return LookupResult(**cache[key])

    # ── Primary: MCP-enhanced agentic lookup ──────────────────────────────────
    if TAVILY_MCP_URL:
        result = _lookup_with_mcp(description, mpn, item_number, supplier)
        if result is not None:
            if not result.notes.startswith("[mcp]"):
                result.notes = f"[mcp] {result.notes}"
            if result.found:
                with _CACHE_LOCK:
                    cache = _load_cache()
                    cache[key] = result.model_dump()
                    _save_cache(cache)
            return result
        # _lookup_with_mcp returned None (hard config error) — fall through

    # ── Fallback: direct search + LLM interpretation ──────────────────────────
    # Try the primary query first; if it yields nothing, try alt queries.
    results: list[dict] = []
    provider = "none"
    all_queries = [query] + _build_alt_queries(description, mpn, item_number, supplier)

    for q in all_queries:
        r, p = _search(q, max_results=LOOKUP_MAX_RESULTS)
        if r:
            results, provider = r, p
            break

    if not results:
        # Don't cache empty results — they may be transient
        return LookupResult(notes="Web search returned no results after multiple queries.")

    # Tavily provides full page content in 'body' — no extra fetch needed.
    # For DDGS results, fetch the top pages for richer context.
    page_texts: list[tuple[str, str]] = []
    if provider == "ddgs":
        for r in results[:2]:
            url = r.get("href", "")
            if url:
                text = _fetch_page_text(url)
                if text:
                    page_texts.append((url, text))
                time.sleep(0.5)

    result = _interpret_with_llm(description, results, page_texts)
    result.notes = f"[{provider}] {result.notes}".strip()

    if result.found:
        with _CACHE_LOCK:
            cache = _load_cache()
            cache[key] = result.model_dump()
            _save_cache(cache)
    return result


def should_trigger_lookup(
    original_uom: Optional[str],
    pack_qty: Optional[int],
    price_per_ea: Optional[float],
) -> bool:
    """Return True when a web lookup should be attempted for this line item."""
    from backend.pipeline.normalizer import canonicalize_uom

    if original_uom is None:
        return True
    canonical = canonicalize_uom(original_uom)
    if canonical in CONTAINER_UOMS and pack_qty is None:
        return True
    if price_per_ea is None:
        return True
    return False
