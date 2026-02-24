"""
FastAPI REST API for the Invoice Processing Pipeline.

Endpoints:
  GET  /health              API + key status
  POST /process             Upload & process a PDF (returns full JSON when done)
  POST /process/stream      Upload & process a PDF with real-time SSE progress
  GET  /results             List all saved JSON results
  GET  /results/{filename}  Fetch a specific saved result
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Invoice Pipeline API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Root ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root() -> dict:
    """API root — frontend is served separately (Vercel)."""
    return {"service": "Invoice Pipeline API", "docs": "/docs", "health": "/health"}


# ─── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    from backend.config import ANTHROPIC_API_KEY
    return {"status": "ok", "api_key_set": bool(ANTHROPIC_API_KEY)}


# ─── Process a PDF ─────────────────────────────────────────────────────────────
@app.post("/process")
async def process_invoice(file: UploadFile = File(...)) -> dict:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    from backend.pipeline.processor import run_pipeline, save_result
    from backend.pipeline.hallucination_checker import check_invoice, summarize_hallucination_report
    from backend.config import OUTPUT_DIR

    content = await file.read()
    logs: list[str] = []

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = run_pipeline(tmp_path, progress_cb=logs.append)
        result.invoice_file = file.filename or tmp_path.name
        save_result(result, OUTPUT_DIR)

        result_dict = result.model_dump()

        # Use hallucination report already computed in pipeline; recompute only if missing
        h_reports = result_dict.get("hallucination_report") or check_invoice(result_dict)
        h_summary = summarize_hallucination_report(h_reports)

        # Attach to result (don't persist raw_text in the API response)
        result_dict["hallucination_report"] = h_reports
        result_dict["hallucination_summary"] = h_summary
        result_dict.pop("raw_text", None)   # strip large field from API response

        return {"logs": logs, **result_dict}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)


# ─── Process a PDF (SSE streaming) ────────────────────────────────────────────
@app.post("/process/stream")
async def process_invoice_stream(file: UploadFile = File(...)) -> StreamingResponse:
    """Same as /process but streams progress events via Server-Sent Events."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    content = await file.read()
    filename = file.filename

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress_cb(msg: str) -> None:
        asyncio.run_coroutine_threadsafe(
            queue.put({"type": "log", "message": msg}), loop
        )

    def run() -> None:
        from backend.pipeline.processor import run_pipeline, save_result
        from backend.pipeline.hallucination_checker import check_invoice, summarize_hallucination_report
        from backend.config import OUTPUT_DIR

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)

            result = run_pipeline(tmp_path, progress_cb=progress_cb)
            result.invoice_file = filename or tmp_path.name
            save_result(result, OUTPUT_DIR)

            result_dict = result.model_dump()
            h_reports = result_dict.get("hallucination_report") or check_invoice(result_dict)
            h_summary = summarize_hallucination_report(h_reports)
            result_dict["hallucination_report"] = h_reports
            result_dict["hallucination_summary"] = h_summary
            result_dict.pop("raw_text", None)

            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "result", "data": result_dict}), loop
            )
        except Exception as exc:
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "error", "message": str(exc)}), loop
            )
        finally:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)  # sentinel

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    async def generate():
        # Hard ceiling: if the pipeline thread vanishes or hangs, don't stream forever
        PIPELINE_TIMEOUT = 360.0  # 6 minutes per file
        deadline = asyncio.get_event_loop().time() + PIPELINE_TIMEOUT
        while True:
            remaining_secs = deadline - asyncio.get_event_loop().time()
            if remaining_secs <= 0:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Pipeline timed out after 6 minutes'})}\n\n"
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=min(remaining_secs, 30.0))
            except asyncio.TimeoutError:
                # Emit a keep-alive comment so the connection isn't dropped by proxies
                yield ": keepalive\n\n"
                continue
            if event is None:
                break
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── List saved results ────────────────────────────────────────────────────────
@app.get("/results")
def list_results() -> list[dict]:
    from backend.config import OUTPUT_DIR
    files = sorted(
        OUTPUT_DIR.glob("*_output.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    items = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # Attach hallucination report if not already present
            if "hallucination_report" not in data:
                from backend.pipeline.hallucination_checker import (
                    check_invoice, summarize_hallucination_report,
                )
                h_reports = check_invoice(data)
                data["hallucination_report"] = h_reports
                data["hallucination_summary"] = summarize_hallucination_report(h_reports)
            data.pop("raw_text", None)
            items.append({"filename": f.name, "data": data})
        except Exception:
            pass
    return items


# ─── Get one saved result ──────────────────────────────────────────────────────
@app.get("/results/{filename}")
def get_result(filename: str) -> dict:
    from backend.config import OUTPUT_DIR
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "hallucination_report" not in data:
            from backend.pipeline.hallucination_checker import (
                check_invoice, summarize_hallucination_report,
            )
            h_reports = check_invoice(data)
            data["hallucination_report"] = h_reports
            data["hallucination_summary"] = summarize_hallucination_report(h_reports)
        data.pop("raw_text", None)
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
