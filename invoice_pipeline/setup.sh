#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Invoice Processing Pipeline — Setup Script
# Run: bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Invoice Processing Pipeline — Setup"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Python version check ──────────────────────────────────────────────────────
PYTHON_BIN=""
for bin in python3 python; do
    if command -v "$bin" &>/dev/null; then
        VER=$("$bin" --version 2>&1 | awk '{print $2}')
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON_BIN="$bin"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: Python 3.10+ is required."
    echo "Install from https://python.org and re-run this script."
    exit 1
fi

echo "✓ Python: $("$PYTHON_BIN" --version)"

# ── Virtual environment ───────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "→ Creating virtual environment (.venv)…"
    "$PYTHON_BIN" -m venv .venv
fi

# Activate
# shellcheck disable=SC1091
source .venv/bin/activate
echo "✓ Virtual environment activated"

# ── Install dependencies ──────────────────────────────────────────────────────
echo "→ Installing dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "✓ Dependencies installed"

# ── .env file ─────────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  Created .env from .env.example"
    echo "   Open .env and set your ANTHROPIC_API_KEY before running."
    echo ""
else
    echo "✓ .env already exists"
fi

# ── Folders ───────────────────────────────────────────────────────────────────
mkdir -p data/input data/output data/cache
echo "✓ Directories: data/input/  data/output/  data/cache/"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Setup complete! Next steps:"
echo ""
echo "  1. Edit .env and set ANTHROPIC_API_KEY"
echo ""
echo "  2. Process a single invoice:"
echo "     python main.py process path/to/invoice.pdf"
echo ""
echo "  3. Process all invoices in a folder:"
echo "     python main.py process-all ../Invoices_1/"
echo ""
echo "  4. Launch the web UI (recommended):"
echo "     python main.py ui"
echo "       — or —"
echo "     streamlit run frontend/app.py"
echo ""
echo "  5. Watch data/input/ for new PDFs:"
echo "     python main.py watch"
echo ""
echo "  6. Run integration tests:"
echo "     python tests/test_pipeline.py"
echo "═══════════════════════════════════════════════════"
echo ""
