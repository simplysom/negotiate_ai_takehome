import { useState, useMemo } from 'react'

function ConfBadge({ score }) {
  const cls = score >= 0.80 ? 'high' : score >= 0.50 ? 'medium' : 'low'
  const dot = score >= 0.80 ? '●' : score >= 0.50 ? '◐' : '○'
  return <span className={`badge ${cls}`}>{dot} {(score * 100).toFixed(0)}%</span>
}

function ReviewBadge({ flag }) {
  return flag
    ? <span className="badge warn">⚠ Review</span>
    : <span className="badge ok">✓ OK</span>
}

export default function LineItemsTable({ items, escalationThreshold }) {
  const [onlyEsc, setOnlyEsc] = useState(false)
  const [minConf, setMinConf] = useState(0)
  const [sort, setSort] = useState({ col: null, dir: 'asc' })

  const filtered = useMemo(() => {
    let rows = items
    if (onlyEsc) rows = rows.filter(i => i.escalation_flag)
    if (minConf > 0) rows = rows.filter(i => i.confidence_score >= minConf)
    if (sort.col) {
      rows = [...rows].sort((a, b) => {
        let va = a[sort.col] ?? '', vb = b[sort.col] ?? ''
        if (typeof va === 'string') va = va.toLowerCase()
        if (typeof vb === 'string') vb = vb.toLowerCase()
        const cmp = va < vb ? -1 : va > vb ? 1 : 0
        return sort.dir === 'asc' ? cmp : -cmp
      })
    }
    return rows
  }, [items, onlyEsc, minConf, sort])

  const toggleSort = (col) => {
    setSort(s => s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' })
  }

  const SortIcon = ({ col }) => {
    if (sort.col !== col) return <span style={{ opacity: .3 }}> ↕</span>
    return <span style={{ color: 'var(--blue)' }}>{sort.dir === 'asc' ? ' ↑' : ' ↓'}</span>
  }

  return (
    <>
      <div className="filter-bar">
        <label>
          <input type="checkbox" checked={onlyEsc} onChange={e => setOnlyEsc(e.target.checked)} />
          Escalated only
        </label>
        <label style={{ gap: 8 }}>
          Min confidence:
          <select value={minConf} onChange={e => setMinConf(parseFloat(e.target.value))}>
            <option value={0}>All</option>
            <option value={0.5}>≥ 50%</option>
            <option value={0.7}>≥ 70%</option>
            <option value={0.8}>≥ 80%</option>
          </select>
        </label>
        <span className="text-xs text-muted" style={{ marginLeft: 'auto' }}>
          {filtered.length} of {items.length} item{items.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th onClick={() => toggleSort('item_description')}>
                Description <SortIcon col="item_description" />
              </th>
              <th onClick={() => toggleSort('item_number')}>Item # <SortIcon col="item_number" /></th>
              <th>MPN</th>
              <th onClick={() => toggleSort('original_uom')}>UOM <SortIcon col="original_uom" /></th>
              <th onClick={() => toggleSort('detected_pack_quantity')}>Pack <SortIcon col="detected_pack_quantity" /></th>
              <th onClick={() => toggleSort('price_per_base_unit')}>$/EA <SortIcon col="price_per_base_unit" /></th>
              <th onClick={() => toggleSort('confidence_score')}>Confidence <SortIcon col="confidence_score" /></th>
              <th>Status</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={10} style={{ textAlign: 'center', color: 'var(--text-3)', padding: 28 }}>
                  No items match the current filter.
                </td>
              </tr>
            )}
            {filtered.map((item, idx) => (
              <tr key={idx}>
                <td className="text-xs text-muted">{item._idx ?? idx + 1}</td>
                <td className="desc">{item.item_description}</td>
                <td className="mono">{item.item_number || '—'}</td>
                <td className="mono">{item.manufacturer_part_number || '—'}</td>
                <td>{item.original_uom || '—'}</td>
                <td>{item.detected_pack_quantity ?? '—'}</td>
                <td className="mono">
                  {item.price_per_base_unit != null ? `$${item.price_per_base_unit.toFixed(4)}` : '—'}
                </td>
                <td><ConfBadge score={item.confidence_score} /></td>
                <td><ReviewBadge flag={item.escalation_flag} /></td>
                <td className="text-xs text-muted">{(item.uom_source || '—').replace(/_/g, ' ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
