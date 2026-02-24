import { useState } from 'react'

function RiskBadge({ level }) {
  const cls = { high: 'badge warn', medium: 'badge medium', low: 'badge ok' }[level] || 'badge ok'
  return <span className={cls}>{level.toUpperCase()}</span>
}

function ItemReport({ report, index }) {
  const [open, setOpen] = useState(report.risk_level === 'high')

  const fillPct = `${Math.round(report.risk_score * 100)}%`

  return (
    <div className="h-item">
      <div className="h-item-header" onClick={() => setOpen(o => !o)}>
        <span className="text-xs text-muted" style={{ width: 24, flexShrink: 0 }}>
          {index + 1}
        </span>
        <span className="h-item-desc" title={report.item_description}>
          {report.item_description}
        </span>
        <div className="h-risk-bar">
          <div
            className={`h-risk-fill ${report.risk_level}`}
            style={{ width: fillPct }}
          />
        </div>
        <span className="text-xs text-muted" style={{ width: 36, textAlign: 'right' }}>
          {(report.risk_score * 100).toFixed(0)}%
        </span>
        <RiskBadge level={report.risk_level} />
        <span className={`chevron${open ? ' open' : ''}`}>▼</span>
      </div>

      {open && (
        <>
          {report.flags.length > 0 && (
            <div className="h-flags">
              {report.flags.map((f, fi) => (
                <div className="h-flag" key={fi}>{f}</div>
              ))}
            </div>
          )}

          <div className="h-checks">
            {report.checks.map((chk, ci) => (
              <div className="h-check-row" key={ci}>
                <span className="h-check-icon">
                  {chk.found_in_source ? '✅' : '❌'}
                </span>
                <span className="h-check-field">{chk.field}</span>
                <div>
                  <div className="h-check-val">{chk.value}</div>
                  {chk.detail && <div className="h-check-detail">{chk.detail}</div>}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default function HallucinationReport({ report, summary }) {
  if (!report || report.length === 0) {
    return (
      <div className="empty-state" style={{ padding: '24px 0' }}>
        <div className="empty-sub">No hallucination report available.</div>
      </div>
    )
  }

  const high   = summary?.high_risk   ?? report.filter(r => r.risk_level === 'high').length
  const medium = summary?.medium_risk ?? report.filter(r => r.risk_level === 'medium').length
  const low    = summary?.low_risk    ?? report.filter(r => r.risk_level === 'low').length

  return (
    <div>
      <div className="h-summary">
        <div className="h-stat">
          <div className="h-stat-val">{report.length}</div>
          <div className="h-stat-label">Total</div>
        </div>
        <div className={`h-stat${high > 0 ? ' red' : ''}`}>
          <div className="h-stat-val">{high}</div>
          <div className="h-stat-label">High Risk</div>
        </div>
        <div className={`h-stat${medium > 0 ? ' amber' : ''}`}>
          <div className="h-stat-val">{medium}</div>
          <div className="h-stat-label">Medium Risk</div>
        </div>
        <div className="h-stat green">
          <div className="h-stat-val">{low}</div>
          <div className="h-stat-label">Low Risk</div>
        </div>
      </div>

      {high > 0 && (
        <div className="alert info" style={{ marginBottom: 12 }}>
          <strong>{high} item{high !== 1 ? 's' : ''} flagged as high risk.</strong>{' '}
          These may contain fabricated MPNs, item numbers, or prices not found in the source PDF.
          Please verify manually.
        </div>
      )}

      {report.map((r, i) => (
        <ItemReport key={i} report={r} index={i} />
      ))}
    </div>
  )
}
