"""
Central configuration for the invoice pipeline.
All settings can be overridden via environment variables or a .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# .env lives at the project root (one level up from backend/)
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

# ── Data directories ───────────────────────────────────────────────────────────
DATA_DIR   = _ROOT / "data"
INPUT_DIR  = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
CACHE_DIR  = DATA_DIR / "cache"

for _d in (INPUT_DIR, OUTPUT_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── API ────────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str   = "claude-sonnet-4-6"
TAVILY_API_KEY: str    = os.getenv("TAVILY_API_KEY", "")
TAVILY_MCP_URL: str    = os.getenv("TAVILY_MCP_URL", "")

# ── Pipeline behaviour ─────────────────────────────────────────────────────────
ESCALATION_THRESHOLD: float = float(os.getenv("ESCALATION_THRESHOLD", "0.5"))
ENABLE_LOOKUP: bool         = os.getenv("ENABLE_LOOKUP", "true").lower() == "true"
LOOKUP_MAX_RESULTS: int     = int(os.getenv("LOOKUP_MAX_RESULTS", "5"))

# UOMs that are containers — price/EA cannot be computed without pack_qty
CONTAINER_UOMS = {"CS", "BX", "PK", "CT", "BG", "BT", "GL", "RL", "SK"}

# Fixed conversion factors to EA (each)
KNOWN_CONVERSION_TO_EA: dict[str, int] = {
    "EA": 1,
    "EACH": 1,
    "PC": 1,
    "PCS": 1,
    "DZ": 12,
    "DOZ": 12,
    "PR": 2,
    "PAIR": 2,
    "KT": 1,
    "KIT": 1,
}

# Price sanity bounds (USD per EA) — outside these → escalate
MIN_PRICE_PER_EA: float =      0.001
MAX_PRICE_PER_EA: float = 50_000.0
