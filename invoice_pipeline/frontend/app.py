"""
Invoice Processing Pipeline — Streamlit Web UI

Run from the project root:
  streamlit run frontend/app.py
  python main.py ui
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Invoice Pipeline",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Base ── */
[data-testid="stAppViewContainer"] { background: #F1F5F9; }

/* ── Sidebar ── */
[data-testid="stSidebar"] { background: #0F172A; border-right: 1px solid #1E293B; }
[data-testid="stSidebar"] * { color: #94A3B8 !important; }
[data-testid="stSidebar"] .stMarkdown strong,
[data-testid="stSidebar"] .stMarkdown b { color: #E2E8F0 !important; }
[data-testid="stSidebar"] hr { border-color: #1E293B !important; margin: 14px 0 !important; }
[data-testid="stSidebar"] .stButton > button {
    background: #2563EB; color: white !important; border: none;
    border-radius: 8px; font-weight: 600; width: 100%;
    padding: 0.55rem 1rem; font-size: .85rem;
}
[data-testid="stSidebar"] .stButton > button:hover { background: #1D4ED8; }
[data-testid="stSidebar"] label { color: #94A3B8 !important; font-size: .82rem !important; }

/* ── Status pill ── */
.pill-ok  { display:inline-flex;align-items:center;gap:6px;
            background:rgba(16,185,129,.15);color:#10B981;
            border:1px solid rgba(16,185,129,.3);border-radius:100px;
            padding:4px 12px;font-size:.78rem;font-weight:600; }
.pill-err { display:inline-flex;align-items:center;gap:6px;
            background:rgba(239,68,68,.15);color:#EF4444;
            border:1px solid rgba(239,68,68,.3);border-radius:100px;
            padding:4px 12px;font-size:.78rem;font-weight:600; }

/* ── Page title ── */
.page-title { margin-bottom:22px; padding-bottom:16px; border-bottom:1px solid #E2E8F0; }
.page-title h2 { font-size:1.45rem;font-weight:700;color:#0F172A;margin:0 0 4px;line-height:1.3; }
.page-title p  { font-size:.85rem;color:#64748B;margin:0; }

/* ── Upload card ── */
.upload-wrap {
    background:white;border-radius:14px;padding:20px 22px;
    border:1px solid #E2E8F0;margin-bottom:22px;
    box-shadow:0 1px 3px rgba(0,0,0,.05);
}
[data-testid="stFileUploaderDropzone"] {
    border:2px dashed #CBD5E1 !important;border-radius:10px !important;
    background:#F8FAFC !important;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color:#3B82F6 !important; }

/* ── Metric cards ── */
.metrics-row { display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:0 0 24px; }
.mcard {
    background:white;border-radius:12px;padding:16px 18px;
    border:1px solid #F1F5F9;box-shadow:0 1px 3px rgba(0,0,0,.06);
    position:relative;overflow:hidden;
}
.mcard::after {
    content:'';position:absolute;bottom:0;left:0;right:0;height:3px;
    background:#3B82F6;border-radius:0 0 12px 12px;
}
.mcard.amber::after  { background:#F59E0B; }
.mcard.green::after  { background:#10B981; }
.mcard.purple::after { background:#8B5CF6; }
.mcard.red::after    { background:#EF4444; }
.mcard-icon  { font-size:1.1rem;margin-bottom:10px; }
.mcard-label { font-size:.7rem;font-weight:700;color:#94A3B8;text-transform:uppercase;
               letter-spacing:.07em;margin-bottom:6px; }
.mcard-value { font-size:1.8rem;font-weight:700;color:#0F172A;line-height:1; }
.mcard-sub   { font-size:.72rem;color:#94A3B8;margin-top:4px; }

/* ── Invoice info strip ── */
.inv-strip {
    background:white;border-radius:12px;padding:16px 20px;
    border:1px solid #E2E8F0;margin-bottom:18px;
    display:grid;grid-template-columns:repeat(4,1fr);gap:20px;
}
.inv-label { font-size:.68rem;font-weight:700;color:#94A3B8;
             text-transform:uppercase;letter-spacing:.07em;margin-bottom:3px; }
.inv-value { font-size:.92rem;font-weight:600;color:#0F172A; }

/* ── Section heading ── */
.sh {
    font-size:.72rem;font-weight:700;color:#64748B;text-transform:uppercase;
    letter-spacing:.1em;margin:22px 0 10px;
    display:flex;align-items:center;gap:10px;
}
.sh::after { content:'';flex:1;height:1px;background:#E2E8F0; }

/* ── Tab bar ── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background:white;border-radius:10px;padding:4px;
    border:1px solid #E2E8F0;gap:2px;margin-bottom:4px;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    border-radius:8px;font-size:.82rem;font-weight:600;color:#64748B;padding:6px 14px;
}
[data-testid="stTabs"] [aria-selected="true"] {
    background:#EFF6FF !important;color:#1D4ED8 !important;
}

/* ── Escalation card ── */
.esc-card {
    background:white;border-radius:10px;border:1px solid #FECACA;
    border-left:4px solid #EF4444;padding:14px 16px;margin-bottom:8px;
}
.esc-title { font-size:.88rem;font-weight:600;color:#0F172A;margin-bottom:6px; }
.esc-reasons { list-style:none;padding:0;margin:0; }
.esc-reasons li {
    font-size:.8rem;color:#64748B;padding:2px 0;
    display:flex;align-items:flex-start;gap:6px;
}
.esc-reasons li::before { content:'›';color:#EF4444;font-weight:700;flex-shrink:0; }

/* ── JSON expander ── */
[data-testid="stExpander"] {
    border:1px solid #E2E8F0 !important;border-radius:10px !important;
    background:white !important;
}

/* ── Buttons ── */
[data-testid="stDownloadButton"] button { border-radius:8px;font-weight:600;font-size:.83rem; }
.stButton button { border-radius:8px;font-weight:600;font-size:.83rem; }
</style>
""", unsafe_allow_html=True)


# ─── Session state ─────────────────────────────────────────────────────────────
if "results" not in st.session_state:
    st.session_state["results"] = []


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<div style='padding:6px 0 18px'>"
        "<span style='font-size:1.15rem;font-weight:700;color:#F1F5F9;letter-spacing:-.01em'>"
        "📄 Invoice Pipeline</span></div>",
        unsafe_allow_html=True,
    )

    # API key status (env only — never exposed as input)
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        st.markdown('<span class="pill-ok">● API key ready</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="pill-err">● API key missing</span>', unsafe_allow_html=True)
        st.caption("Add ANTHROPIC_API_KEY to .env and restart")

    st.markdown("---")
    st.markdown(
        "<div style='font-size:.68rem;font-weight:700;color:#475569;"
        "text-transform:uppercase;letter-spacing:.09em;margin-bottom:10px'>Settings</div>",
        unsafe_allow_html=True,
    )

    enable_lookup = st.toggle(
        "Agentic web lookup",
        value=True,
        help="When UOM or pack size is missing, search the web automatically.",
    )
    os.environ["ENABLE_LOOKUP"] = "true" if enable_lookup else "false"

    escalation_threshold = st.slider(
        "Escalation threshold",
        min_value=0.1, max_value=0.9, value=0.5, step=0.05,
        help="Items with confidence below this value are flagged for review.",
    )
    os.environ["ESCALATION_THRESHOLD"] = str(escalation_threshold)

    st.markdown("---")
    st.markdown(
        "<div style='font-size:.68rem;font-weight:700;color:#475569;"
        "text-transform:uppercase;letter-spacing:.09em;margin-bottom:10px'>Inbox</div>",
        unsafe_allow_html=True,
    )

    inbox_path_str = st.text_input(
        "Inbox folder",
        value=str(Path(__file__).parent.parent / "data" / "input"),
        label_visibility="collapsed",
    )
    inbox_path = Path(inbox_path_str)

    if st.button("Process Inbox →", use_container_width=True):
        st.session_state["process_inbox"] = True

    st.markdown("---")
    st.caption("v1.0 · Claude AI")


# ─── Page title ───────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-title">
  <h2>Invoice Processing</h2>
  <p>Upload supplier PDFs to extract, normalize, and price every line item automatically.</p>
</div>
""", unsafe_allow_html=True)


# ─── Upload card ──────────────────────────────────────────────────────────────
st.markdown('<div class="upload-wrap">', unsafe_allow_html=True)
up_col, hint_col = st.columns([3, 1])
with up_col:
    uploaded_files = st.file_uploader(
        "Upload PDF invoices",
        type=["pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
with hint_col:
    st.markdown("""
    <div style="padding:14px;background:#F8FAFC;border-radius:10px;
                border:1px solid #E2E8F0;font-size:.8rem;color:#64748B;line-height:1.75;">
      <div style="font-weight:700;color:#0F172A;margin-bottom:8px;">Supported</div>
      ✓ Any supplier format<br>
      ✓ Multi-page PDFs<br>
      ✓ Embedded tables<br>
      ✓ Missing / mixed UOM<br>
      ✓ Pack expressions (25/CS…)
    </div>
    """, unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)


# ─── Processing helpers ────────────────────────────────────────────────────────
def _reload_backend() -> None:
    import importlib
    import backend.config as cfg
    importlib.reload(cfg)


def _process_bytes(file_name: str, file_bytes: bytes) -> dict | None:
    _reload_backend()
    from backend.pipeline.processor import run_pipeline, save_result
    from backend.config import OUTPUT_DIR

    log = st.session_state.setdefault("current_log", [])
    log.clear()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    try:
        result = run_pipeline(tmp_path, progress_cb=log.append)
        result.invoice_file = file_name
        save_result(result, OUTPUT_DIR)
        return result.model_dump()
    except Exception as e:
        st.error(f"Error processing **{file_name}**: {e}")
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


# ─── Trigger processing ────────────────────────────────────────────────────────
files_to_process: list[tuple[str, bytes]] = []

if uploaded_files:
    for uf in uploaded_files:
        if not any(r.get("invoice_file") == uf.name for r in st.session_state["results"]):
            files_to_process.append((uf.name, uf.read()))

if st.session_state.get("process_inbox"):
    st.session_state["process_inbox"] = False
    if inbox_path.exists():
        for pdf in sorted(inbox_path.glob("*.pdf")):
            if not any(r.get("invoice_file") == pdf.name for r in st.session_state["results"]):
                files_to_process.append((pdf.name, pdf.read_bytes()))

if files_to_process:
    if not api_key:
        st.error("ANTHROPIC_API_KEY not found — add it to your .env file and restart.")
    else:
        prog = st.progress(0, text="Starting…")
        with st.expander("Processing log", expanded=True):
            log_placeholder = st.empty()

        for idx, (fname, fbytes) in enumerate(files_to_process):
            prog.progress(
                idx / len(files_to_process),
                text=f"Processing {fname}  ({idx + 1} of {len(files_to_process)})",
            )
            result_dict = _process_bytes(fname, fbytes)
            if result_dict:
                st.session_state["results"].append(result_dict)
            log_placeholder.code(
                "\n".join(st.session_state.get("current_log", [])), language=None
            )

        prog.progress(1.0, text="Done!")


# ─── Results ──────────────────────────────────────────────────────────────────
all_results: list[dict] = st.session_state["results"]

if not all_results:
    st.markdown("""
    <div style="text-align:center;padding:64px 20px;">
      <div style="font-size:2.8rem;margin-bottom:14px;">📂</div>
      <div style="font-size:1rem;font-weight:600;color:#475569;margin-bottom:6px;">
        No invoices processed yet
      </div>
      <div style="font-size:.85rem;color:#94A3B8;">
        Upload a PDF above, or drop files in <code>data/input/</code> and click
        <strong>Process Inbox</strong>
      </div>
    </div>
    """, unsafe_allow_html=True)

else:
    # ── Summary metrics ────────────────────────────────────────────────────────
    total_items = sum(len(r.get("line_items", [])) for r in all_results)
    total_esc   = sum(
        sum(1 for li in r.get("line_items", []) if li.get("escalation_flag"))
        for r in all_results
    )
    avg_conf = (
        sum(li.get("confidence_score", 0) for r in all_results for li in r.get("line_items", []))
        / max(total_items, 1)
    )
    looked_up = sum(
        sum(1 for li in r.get("line_items", []) if li.get("uom_source") == "lookup_web")
        for r in all_results
    )

    esc_cls  = "red"   if total_esc > 0    else "green"
    conf_cls = "green" if avg_conf >= 0.75 else "amber"

    st.markdown(f"""
    <div class="metrics-row">
      <div class="mcard">
        <div class="mcard-icon">🗂</div>
        <div class="mcard-label">Invoices</div>
        <div class="mcard-value">{len(all_results)}</div>
      </div>
      <div class="mcard">
        <div class="mcard-icon">🔢</div>
        <div class="mcard-label">Line Items</div>
        <div class="mcard-value">{total_items}</div>
      </div>
      <div class="mcard {esc_cls}">
        <div class="mcard-icon">⚠️</div>
        <div class="mcard-label">Need Review</div>
        <div class="mcard-value">{total_esc}</div>
        <div class="mcard-sub">escalated</div>
      </div>
      <div class="mcard {conf_cls}">
        <div class="mcard-icon">🎯</div>
        <div class="mcard-label">Avg Confidence</div>
        <div class="mcard-value">{avg_conf:.0%}</div>
      </div>
      <div class="mcard purple">
        <div class="mcard-icon">🔍</div>
        <div class="mcard-label">Lookup Resolved</div>
        <div class="mcard-value">{looked_up}</div>
        <div class="mcard-sub">via web search</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Per-invoice tabs ───────────────────────────────────────────────────────
    tab_labels = [r.get("invoice_file", f"Invoice {i+1}") for i, r in enumerate(all_results)]
    tabs = st.tabs(tab_labels)

    for tab, result in zip(tabs, all_results):
        with tab:

            # Invoice info strip
            s = result.get("summary", {})
            esc_count = s.get("escalated_items", 0)
            esc_color = "#EF4444" if esc_count else "#10B981"
            st.markdown(f"""
            <div class="inv-strip">
              <div>
                <div class="inv-label">Supplier</div>
                <div class="inv-value">{result.get('supplier_name', '—')}</div>
              </div>
              <div>
                <div class="inv-label">Invoice #</div>
                <div class="inv-value">{result.get('invoice_number', '—')}</div>
              </div>
              <div>
                <div class="inv-label">Date</div>
                <div class="inv-value">{result.get('invoice_date', '—')}</div>
              </div>
              <div>
                <div class="inv-label">Items / Escalated</div>
                <div class="inv-value">
                  {s.get('total_line_items', '—')}
                  <span style="color:{esc_color};font-size:.82rem;margin-left:8px;font-weight:500;">
                    ({esc_count} flagged)
                  </span>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            line_items = result.get("line_items", [])
            if not line_items:
                st.warning("No line items found in this invoice.")
                continue

            # ── Line items table ────────────────────────────────────────────────
            st.markdown('<div class="sh">Line Items</div>', unsafe_allow_html=True)

            fc1, fc2, fc3 = st.columns([1.2, 2, 2])
            with fc1:
                filter_esc = st.checkbox(
                    "Escalated only",
                    key=f"esc_{result.get('invoice_file')}",
                )
            with fc2:
                st.caption("Min confidence filter")
                min_conf = st.slider(
                    "Min confidence",
                    0.0, 1.0, 0.0, 0.05,
                    key=f"conf_{result.get('invoice_file')}",
                    label_visibility="collapsed",
                )

            rows = []
            for li in line_items:
                conf = li.get("confidence_score", 0)
                badge = (
                    "● High" if conf >= 0.80 else
                    "● Med"  if conf >= 0.50 else
                    "● Low"
                )
                rows.append({
                    "Description": li.get("item_description", ""),
                    "Item #":      li.get("item_number") or "—",
                    "MPN":         li.get("manufacturer_part_number") or "—",
                    "UOM":         li.get("original_uom") or "—",
                    "Pack":        str(li.get("detected_pack_quantity") or "—"),
                    "$/EA": (
                        f"${li['price_per_base_unit']:.4f}"
                        if li.get("price_per_base_unit") is not None else "—"
                    ),
                    "Confidence": badge,
                    "_score":     conf,
                    "Review":     "⚠ YES" if li.get("escalation_flag") else "✓ OK",
                    "Source":     (li.get("uom_source") or "—").replace("_", " "),
                })

            df = pd.DataFrame(rows)
            display_df = df.copy()
            if filter_esc:
                display_df = display_df[display_df["Review"].str.startswith("⚠")]
            if min_conf > 0:
                display_df = display_df[display_df["_score"] >= min_conf]

            def _color_conf(v: str) -> str:
                if "High" in str(v): return "color:#059669;font-weight:700"
                if "Med"  in str(v): return "color:#D97706;font-weight:700"
                return "color:#DC2626;font-weight:700"

            def _color_rev(v: str) -> str:
                return "color:#DC2626;font-weight:700" if "YES" in str(v) else "color:#059669;font-weight:600"

            styled = (
                display_df.drop(columns=["_score"])
                .style
                .map(_color_conf, subset=["Confidence"])
                .map(_color_rev,  subset=["Review"])
            )
            st.dataframe(
                styled,
                use_container_width=True,
                height=min(440, 60 + len(display_df) * 38),
            )

            # ── Escalation cards ────────────────────────────────────────────────
            escalated = [li for li in line_items if li.get("escalation_flag")]
            if escalated:
                st.markdown('<div class="sh">Items Needing Review</div>', unsafe_allow_html=True)
                for li in escalated:
                    reasons = []
                    if li.get("confidence_score", 1) < escalation_threshold:
                        reasons.append(f"Low confidence score ({li['confidence_score']:.2f})")
                    if li.get("price_per_base_unit") is None:
                        reasons.append("Price per EA could not be determined")
                    if li.get("lookup_notes"):
                        reasons.append(li["lookup_notes"][:150])
                    reason_items = "".join(f"<li>{r}</li>" for r in reasons)
                    st.markdown(
                        f'<div class="esc-card">'
                        f'<div class="esc-title">{li.get("item_description", "—")}</div>'
                        f'<ul class="esc-reasons">{reason_items}</ul>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # ── Hallucination report ────────────────────────────────────────────
            hallucination_report = result.get("hallucination_report") or []
            if hallucination_report:
                from backend.pipeline.hallucination_checker import summarize_hallucination_report
                h_summary = summarize_hallucination_report(hallucination_report)
                high_risk = h_summary.get("high_risk", 0)
                med_risk  = h_summary.get("medium_risk", 0)

                st.markdown('<div class="sh">Hallucination Check</div>', unsafe_allow_html=True)

                hc1, hc2, hc3, hc4 = st.columns(4)
                hc1.metric("Items Checked", h_summary.get("total", 0))
                hc2.metric("High Risk",   high_risk)
                hc3.metric("Medium Risk", med_risk)
                hc4.metric("Low Risk",    h_summary.get("low_risk", 0))

                if high_risk > 0:
                    st.warning(
                        f"{high_risk} item(s) flagged high risk — MPNs, item numbers, or prices "
                        "not found in source PDF. Verify manually before use."
                    )

                risky = [r for r in hallucination_report if r.get("risk_level") in ("high", "medium")]
                if risky:
                    with st.expander(f"View {len(risky)} flagged item(s)", expanded=high_risk > 0):
                        for r in risky:
                            lvl = r.get("risk_level", "low")
                            lvl_color = "#DC2626" if lvl == "high" else "#D97706"
                            flags_html = "".join(f"<li>{f}</li>" for f in r.get("flags", []))
                            st.markdown(
                                f'<div class="esc-card" style="border-left-color:{lvl_color}">'
                                f'<div class="esc-title" style="display:flex;'
                                f'justify-content:space-between">'
                                f'<span>{r.get("item_description", "—")[:80]}</span>'
                                f'<span style="color:{lvl_color};font-size:.78rem;font-weight:700">'
                                f'{lvl.upper()} · {r.get("risk_score", 0):.0%}</span></div>'
                                f'<ul class="esc-reasons">{flags_html}</ul>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

            # ── JSON output ─────────────────────────────────────────────────────
            with st.expander("📋 Structured JSON Output", expanded=False):
                view_mode = st.radio(
                    "Format",
                    ["Interactive tree", "Raw JSON"],
                    horizontal=True,
                    key=f"view_{result.get('invoice_file')}",
                    label_visibility="collapsed",
                )
                if view_mode == "Interactive tree":
                    st.json(result, expanded=2)
                else:
                    st.code(json.dumps(result, indent=2, default=str), language="json")

                st.download_button(
                    "⬇️  Download JSON",
                    data=json.dumps(result, indent=2, default=str),
                    file_name=f"{Path(result.get('invoice_file', 'invoice')).stem}_output.json",
                    mime="application/json",
                    key=f"dl_{result.get('invoice_file')}",
                )

    # ── Bulk actions ───────────────────────────────────────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    ba1, ba2, _ = st.columns([1.5, 1, 3])
    with ba1:
        st.download_button(
            "⬇️  Download All (JSON)",
            data=json.dumps(all_results, indent=2, default=str),
            file_name="all_invoices_output.json",
            mime="application/json",
        )
    with ba2:
        if st.button("Clear session", use_container_width=True):
            st.session_state["results"] = []
            st.rerun()


# ─── Previously processed files ───────────────────────────────────────────────
st.markdown(
    "<hr style='border:none;border-top:1px solid #E2E8F0;margin:32px 0 24px'>",
    unsafe_allow_html=True,
)
st.markdown('<div class="sh">Previously Processed Files</div>', unsafe_allow_html=True)

output_dir  = Path(__file__).parent.parent / "data" / "output"
saved_jsons = sorted(
    output_dir.glob("*_output.json"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not saved_jsons:
    st.markdown(
        "<div style='color:#94A3B8;font-size:.85rem;padding:8px 0'>"
        "No saved output files yet.</div>",
        unsafe_allow_html=True,
    )
else:
    selected_file = st.selectbox(
        "Select file",
        options=saved_jsons,
        format_func=lambda p: p.stem.replace("_output", ""),
        label_visibility="collapsed",
    )
    if selected_file:
        try:
            saved_data = json.loads(selected_file.read_text())
            sv = saved_data.get("summary", {})

            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("Supplier",   saved_data.get("supplier_name", "—"))
            sc2.metric("Invoice #",  saved_data.get("invoice_number", "—"))
            sc3.metric("Line Items", sv.get("total_line_items", "—"))
            sc4.metric("Escalated",  sv.get("escalated_items", "—"))

            with st.expander("View JSON", expanded=False):
                sv_mode = st.radio(
                    "Format", ["Interactive tree", "Raw JSON"],
                    horizontal=True, key="saved_view",
                    label_visibility="collapsed",
                )
                if sv_mode == "Interactive tree":
                    st.json(saved_data, expanded=2)
                else:
                    st.code(json.dumps(saved_data, indent=2), language="json")

            st.download_button(
                f"⬇️  Download {selected_file.name}",
                data=selected_file.read_text(),
                file_name=selected_file.name,
                mime="application/json",
                key="dl_saved",
            )
        except Exception as e:
            st.error(f"Could not load file: {e}")
