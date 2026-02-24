import { useState } from 'react'
import LineItemsTable from './LineItemsTable.jsx'
import EscalationPanel from './EscalationPanel.jsx'
import HallucinationReport from './HallucinationReport.jsx'

function Collapsible({ title, defaultOpen = false, children, badge }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="collapsible">
      <div className="collapsible-hdr" onClick={() => setOpen(o => !o)}>
        <span className="collapsible-title">{title}</span>
        {badge && <span style={{ marginLeft: 8 }}>{badge}</span>}
        <span className={`chevron${open ? ' open' : ''}`}>▼</span>
      </div>
      {open && <div className="collapsible-body">{children}</div>}
    </div>
  )
}

function downloadJSON(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

export default function InvoiceView({ result, escalationThreshold }) {
  const s         = result.summary || {}
  const items     = result.line_items || []
  const escCount  = s.escalated_items ?? 0
  const hReport   = result.hallucination_report || []
  const hSummary  = result.hallucination_summary || {}
  const highRisk  = hSummary.high_risk ?? hReport.filter(r => r.risk_level === 'high').length

  // Enrich items with 1-based index
  const enriched = items.map((item, i) => ({ ...item, _idx: i + 1 }))

  const stem = (result.invoice_file || 'invoice').replace(/\.pdf$/i, '')

  return (
    <div>
      {/* Invoice info strip */}
      <div className="invoice-strip">
        <div>
          <div className="inv-field-label">Supplier</div>
          <div className="inv-field-value">{result.supplier_name || '—'}</div>
        </div>
        <div>
          <div className="inv-field-label">Invoice #</div>
          <div className="inv-field-value">{result.invoice_number || '—'}</div>
        </div>
        <div>
          <div className="inv-field-label">Date</div>
          <div className="inv-field-value">{result.invoice_date || '—'}</div>
        </div>
        <div>
          <div className="inv-field-label">Items / Escalated</div>
          <div className="inv-field-value">
            {s.total_line_items ?? '—'}
            {escCount > 0 && (
              <span style={{ color: 'var(--red)', fontSize: '.82rem', marginLeft: 8, fontWeight: 500 }}>
                ({escCount} flagged)
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Line items */}
      <div className="section-heading">Line Items</div>
      <LineItemsTable items={enriched} escalationThreshold={escalationThreshold} />

      {/* Escalation */}
      {escCount > 0 && (
        <EscalationPanel items={items} escalationThreshold={escalationThreshold} />
      )}

      {/* Hallucination report */}
      <Collapsible
        title="Hallucination Check"
        defaultOpen={highRisk > 0}
        badge={
          highRisk > 0
            ? <span className="badge warn">{highRisk} high risk</span>
            : <span className="badge ok">Clean</span>
        }
      >
        <HallucinationReport report={hReport} summary={hSummary} />
      </Collapsible>

      {/* JSON output */}
      <Collapsible title="Structured JSON Output" defaultOpen={false}>
        <pre className="json-viewer">
          {JSON.stringify(
            { ...result, hallucination_report: undefined, hallucination_summary: undefined },
            null, 2
          )}
        </pre>
        <div className="flex gap-2" style={{ marginTop: 12 }}>
          <button
            className="btn btn-outline btn-sm"
            onClick={() => downloadJSON(result, `${stem}_output.json`)}
          >
            ⬇ Download JSON
          </button>
          <button
            className="btn btn-outline btn-sm"
            onClick={() => navigator.clipboard.writeText(JSON.stringify(result, null, 2))}
          >
            Copy to clipboard
          </button>
        </div>
      </Collapsible>
    </div>
  )
}
