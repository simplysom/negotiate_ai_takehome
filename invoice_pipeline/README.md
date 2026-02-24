# Invoice Processing Pipeline

An AI-powered pipeline that extracts, normalises, and prices every line item from supplier PDF invoices. Upload a PDF through the React UI or CLI and get back structured JSON with confidence scores, UOM normalisation, web-lookup resolution, and escalation flags for items needing human review.

---

## Features

- **AI parsing** — Claude extracts all line items via structured tool-use (never free-form prose)
- **UOM normalisation** — deterministic rules convert units (EA, CS, DZ, PR, BX …) and compute price-per-each
- **Agentic web lookup** — when pack size is missing, Claude searches the web (Tavily / DuckDuckGo) to resolve it
- **Hallucination checking** — cross-references extracted values against the source PDF text
- **Confidence scoring** — every item gets a 0–1 score; low-confidence items are automatically escalated
- **Real-time progress** — Server-Sent Events stream live logs to the React UI stage-by-stage
- **Parallel processing** — line items normalised concurrently (up to 4 workers) with per-item timeouts and graceful fallbacks
- **CLI + React UI** — process invoices from the terminal or a full web interface

---

## Architecture

```
invoice_pipeline/
├── backend/
│   ├── api.py                      FastAPI REST + SSE streaming endpoint
│   ├── config.py                   All settings, loaded from .env
│   └── pipeline/
│       ├── extractor.py            PDF → raw text  (pdfplumber)
│       ├── parser.py               Raw text → structured items  (Claude tool-use)
│       ├── normalizer.py           UOM canonicalisation + price-per-EA
│       ├── lookup.py               Agentic web search for missing pack info
│       ├── scorer.py               Confidence scoring + escalation logic
│       ├── hallucination_checker.py  Cross-reference validation
│       ├── processor.py            Pipeline orchestrator
│       └── models.py               Pydantic output schemas
├── frontend_react/                 React 18 + Vite UI
│   ├── src/
│   │   ├── App.jsx                 Main app, SSE consumer, progress card
│   │   ├── api.js                  fetch wrapper (dev proxy / prod URL)
│   │   └── components/             Sidebar, UploadZone, MetricsBar, InvoiceView
│   ├── vercel.json                 Vercel deployment config
│   └── vite.config.js              Dev proxy → localhost:8000
├── data/
│   ├── input/                      Drop PDFs here for CLI processing
│   ├── output/                     JSON results written here
│   └── cache/                      Web lookup cache (speeds up repeat runs)
├── main.py                         CLI entry point (Click + Rich)
├── render.yaml                     Render deployment blueprint (backend)
├── Procfile                        Render/Heroku process file
├── requirements.txt
└── .env.example
```

---

## Pipeline stages

```
[1/5] Extract   — pdfplumber reads PDF text
[2/5] Parse     — Claude extracts all line items (tool-use, ~15–45 s)
[3/5] Normalize — UOM + price-per-EA (parallel, web lookup if needed)
[4/5] Build     — assemble InvoiceResult + summary
[5/5] Validate  — hallucination check against source PDF text
```

---

## Local setup

### Prerequisites

- Python 3.10+
- Node.js 18+ (for the React UI)

### 1. Clone and install

```bash
git clone <your-repo-url>
cd invoice_pipeline

# Python dependencies
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Frontend dependencies
cd frontend_react && npm install && cd ..
```

Or use the provided setup script:

```bash
bash setup.sh
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...          # required
TAVILY_API_KEY=tvly-...               # recommended (falls back to DuckDuckGo if absent)
TAVILY_MCP_URL=https://mcp.tavily.com/mcp/?tavilyApiKey=tvly-...  # optional MCP path
ENABLE_LOOKUP=true
ESCALATION_THRESHOLD=0.5
LOOKUP_MAX_RESULTS=5
```

### 3. Run locally

**Terminal 1 — backend:**

```bash
source .venv/bin/activate
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — frontend (Node 18+ required):**

```bash
cd frontend_react
npm run dev
```

Open **http://localhost:3000**

---

## CLI usage

```bash
source .venv/bin/activate

# Single PDF
python main.py process path/to/invoice.pdf

# All PDFs in a folder
python main.py process-all path/to/invoices/

# Watch mode — auto-processes any PDF dropped into data/input/
python main.py watch data/input/
```

Results are written to `data/output/<filename>_output.json` and printed as a rich table in the terminal.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check + API key status |
| `POST` | `/process/stream` | Upload PDF, stream SSE progress + result |
| `POST` | `/process` | Upload PDF, return JSON when done (no streaming) |
| `GET` | `/results` | List all saved output files |
| `GET` | `/results/{filename}` | Fetch one saved result |

---

## Output schema

```json
{
  "invoice_file": "invoice.pdf",
  "supplier_name": "Acme Supplies",
  "invoice_number": "INV-12345",
  "invoice_date": "2024-01-15",
  "summary": {
    "total_line_items": 24,
    "escalated_items": 2,
    "items_resolved_via_lookup": 5,
    "avg_confidence_score": 0.847,
    "min_confidence_score": 0.32
  },
  "line_items": [
    {
      "item_description": "Nitrile Exam Gloves Medium",
      "original_uom": "CS",
      "detected_pack_quantity": 1000,
      "canonical_base_uom": "EA",
      "price_per_base_unit": 0.0842,
      "confidence_score": 0.91,
      "escalation_flag": false,
      "uom_source": "lookup_web",
      "raw_unit_price": 84.20,
      "raw_quantity": 5,
      "raw_line_total": 421.00,
      "line_total_check": "ok",
      "lookup_notes": "Source: grainger.com. Snippet: ..."
    }
  ],
  "hallucination_report": [...]
}
```

### UOM source values

| Value | Meaning |
|-------|---------|
| `invoice_direct` | UOM was printed on the invoice |
| `inferred` | Inferred from pack expression in description |
| `lookup_web` | Resolved via agentic web search |
| `missing` | Could not determine |

---

## Confidence scoring

| Score | Band | Meaning |
|-------|------|---------|
| 0.80 – 1.00 | High | Ready to use |
| 0.50 – 0.79 | Medium | Use with caution |
| 0.00 – 0.49 | Low | Escalated — needs human review |

Factors that **raise** confidence: UOM on invoice, MPN present, unambiguous pack expression, line total cross-check passes.

Factors that **lower** confidence: UOM missing, container UOM without pack qty, OCR noise, line total mismatch.

---

## Handled UOM patterns

| Pattern | Example | Result |
|---------|---------|--------|
| Slash notation | `25/CS` | pack_qty=25, uom=CS |
| UOM-first | `PK10`, `BX12` | pack_qty=10/12, uom=PK/BX |
| Qty-first | `1000 EA`, `12 PR` | pack_qty=1000/12, uom=EA/PR |
| Case of | `CASE OF 24` | pack_qty=24, uom=CS |
| Dozen | `12 DZ` | pack_qty=144, uom=EA |
| Nested | `100/BX 8 BX/CS` | pack_qty=800, uom=CS |
| Pair | `PR` | factor=2, uom=EA |

---

## Deployment

### Backend → Render

1. Push to GitHub
2. [render.com](https://render.com) → **New** → **Blueprint** → connect repo, root dir `invoice_pipeline/`
3. Render reads `render.yaml` and provisions the web service + 1 GB persistent disk automatically
4. In the Render dashboard → **Environment**, add secrets:
   - `ANTHROPIC_API_KEY`
   - `TAVILY_API_KEY`
   - `TAVILY_MCP_URL`
5. Copy the service URL: `https://invoice-pipeline-api.onrender.com`

> **Note:** The free Render tier sleeps after 15 minutes of inactivity. Upgrade to the Starter paid plan for always-on operation.

### Frontend → Vercel

1. [vercel.com](https://vercel.com) → **New Project** → import same repo
2. Set **Root Directory** to `invoice_pipeline/frontend_react`
3. Add environment variable:
   ```
   VITE_API_URL = https://invoice-pipeline-api.onrender.com
   ```
4. Deploy — Vercel runs `npm run build` automatically

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key for Claude |
| `TAVILY_API_KEY` | No | — | Tavily search key (falls back to DuckDuckGo if absent) |
| `TAVILY_MCP_URL` | No | — | Tavily MCP server URL for agentic multi-step search |
| `ENABLE_LOOKUP` | No | `true` | Enable/disable web lookup for missing UOM |
| `ESCALATION_THRESHOLD` | No | `0.5` | Confidence below which items are flagged for review |
| `LOOKUP_MAX_RESULTS` | No | `5` | Max web search results per lookup query |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| AI / LLM | Claude (Anthropic) via tool-use |
| PDF parsing | pdfplumber |
| Web search | Tavily SDK / DuckDuckGo (ddgs) |
| Backend API | FastAPI + uvicorn |
| Streaming | Server-Sent Events (SSE) |
| Frontend | React 18 + Vite |
| Data models | Pydantic v2 |
| CLI | Click + Rich |
| Backend hosting | Render |
| Frontend hosting | Vercel |

---

## Known limitations

- **Image-only PDFs** — pdfplumber cannot extract text from scanned images. Integrate `pytesseract` + Tesseract OCR as a fallback if needed.
- **Very long invoices** — multi-page invoices are supported; extremely long ones may approach token limits.
- **Non-English invoices** — parsing is attempted but may be less accurate.
