export default function MetricsBar({ results }) {
  const totalItems  = results.reduce((s, r) => s + (r.line_items?.length || 0), 0)
  const totalEsc    = results.reduce((s, r) => s + (r.line_items?.filter(i => i.escalation_flag).length || 0), 0)
  const totalLookup = results.reduce((s, r) => s + (r.line_items?.filter(i => i.uom_source === 'lookup_web').length || 0), 0)
  const avgConf     = totalItems
    ? results.reduce((s, r) => s + (r.line_items?.reduce((ss, i) => ss + (i.confidence_score || 0), 0) || 0), 0) / totalItems
    : 0

  const escCls  = totalEsc > 0 ? 'red' : 'green'
  const confCls = avgConf >= 0.75 ? 'green' : 'amber'

  return (
    <div className="metrics-grid">
      <div className="metric-card blue">
        <div className="metric-icon">🗂</div>
        <div className="metric-label">Invoices</div>
        <div className="metric-value">{results.length}</div>
      </div>
      <div className="metric-card">
        <div className="metric-icon">🔢</div>
        <div className="metric-label">Line Items</div>
        <div className="metric-value">{totalItems}</div>
      </div>
      <div className={`metric-card ${escCls}`}>
        <div className="metric-icon">⚠️</div>
        <div className="metric-label">Need Review</div>
        <div className="metric-value">{totalEsc}</div>
        <div className="metric-sub">escalated</div>
      </div>
      <div className={`metric-card ${confCls}`}>
        <div className="metric-icon">🎯</div>
        <div className="metric-label">Avg Confidence</div>
        <div className="metric-value">{(avgConf * 100).toFixed(0)}%</div>
      </div>
      <div className="metric-card purple">
        <div className="metric-icon">🔍</div>
        <div className="metric-label">Lookup Resolved</div>
        <div className="metric-value">{totalLookup}</div>
        <div className="metric-sub">via web search</div>
      </div>
    </div>
  )
}
