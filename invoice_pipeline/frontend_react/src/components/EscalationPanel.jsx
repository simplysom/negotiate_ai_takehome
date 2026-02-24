export default function EscalationPanel({ items, escalationThreshold }) {
  const escalated = items.filter(i => i.escalation_flag)
  if (!escalated.length) return null

  return (
    <div>
      <div className="section-heading">Items Needing Review ({escalated.length})</div>
      <div className="esc-list">
        {escalated.map((item, idx) => {
          const reasons = []
          if (item.confidence_score < escalationThreshold)
            reasons.push(`Low confidence score (${(item.confidence_score * 100).toFixed(0)}%)`)
          if (item.price_per_base_unit == null)
            reasons.push('Price per EA could not be determined')
          if (item.lookup_notes && item.lookup_notes.includes('nothing useful'))
            reasons.push('Web lookup could not resolve UOM or pack size')
          if (item.line_total_check === 'mismatch')
            reasons.push('Line total arithmetic does not match extracted price × quantity')

          return (
            <div className="esc-card" key={idx}>
              <div className="esc-title">{item.item_description}</div>
              {item.item_number && (
                <div className="text-xs text-muted mb-2">Item # {item.item_number}</div>
              )}
              {reasons.map((r, ri) => (
                <div className="esc-reason" key={ri}>{r}</div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
