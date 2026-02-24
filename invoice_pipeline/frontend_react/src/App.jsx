import { useState, useEffect, useRef } from 'react'
import Sidebar from './components/Sidebar.jsx'
import UploadZone from './components/UploadZone.jsx'
import MetricsBar from './components/MetricsBar.jsx'
import InvoiceView from './components/InvoiceView.jsx'
import { processInvoice, listResults } from './api.js'

// ── Saved results panel ─────────────────────────────────────────────────────
function SavedPanel({ onSelect }) {
  const [saved, setSaved] = useState([])
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try { setSaved(await listResults()) } catch { setSaved([]) }
    finally { setLoading(false) }
  }

  useEffect(() => { refresh() }, [])

  if (!saved.length) {
    return (
      <div>
        <div className="section-heading">Previously Processed Files</div>
        <p className="text-sm text-muted">
          No saved output files yet.{' '}
          <button className="btn btn-outline btn-sm" onClick={refresh} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center gap-3" style={{ marginBottom: 12 }}>
        <div className="section-heading" style={{ margin: 0, flex: 1 }}>
          Previously Processed Files
        </div>
        <button className="btn btn-outline btn-sm" onClick={refresh} disabled={loading}>
          {loading ? '…' : 'Refresh'}
        </button>
      </div>
      <div className="file-list">
        {saved.map((item, i) => (
          <div
            key={i}
            className="file-item"
            onClick={() => onSelect(item.data)}
          >
            <span className="file-item-icon">📄</span>
            <span className="file-item-name">
              {item.filename.replace(/_output\.json$/, '')}
            </span>
            <span className="file-item-meta">
              {item.data?.summary?.total_line_items ?? 0} items
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Pipeline stage definitions ───────────────────────────────────────────────
const PIPELINE_STAGES = [
  { id: 1, label: 'Extract',   icon: '📄', hint: 'Reading PDF text' },
  { id: 2, label: 'Parse',     icon: '🤖', hint: 'AI extracting items' },
  { id: 3, label: 'Normalize', icon: '⚙️', hint: 'Pricing & UOM' },
  { id: 4, label: 'Build',     icon: '📋', hint: 'Structuring result' },
  { id: 5, label: 'Validate',  icon: '✓',  hint: 'Hallucination check' },
]

function detectStage(logs) {
  for (let i = logs.length - 1; i >= 0; i--) {
    const l = logs[i]
    if (l.includes('[5/5]') || l.toLowerCase().includes('hallucination')) return 5
    if (l.includes('[4/5]') || l.includes('Building result'))             return 4
    if (l.includes('[3/5]') || /Item \d+\/\d+/.test(l) ||
        l.includes('Normalizing') || l.includes('web lookup'))            return 3
    if (l.includes('[2/5]') || l.includes('Parsing') || l.includes('Claude')) return 2
    if (l.includes('[1/5]') || l.includes('Extracting'))                  return 1
  }
  return 0
}

function detectItemProgress(logs) {
  for (let i = logs.length - 1; i >= 0; i--) {
    const m = logs[i].match(/Item (\d+)\/(\d+)/)
    if (m) return { cur: parseInt(m[1], 10), tot: parseInt(m[2], 10) }
  }
  return null
}

function calcPct(stage, logs) {
  // Approximate progress within a single file based on stage + item progress
  const stageFloor  = [0, 5, 15, 35, 82, 92, 100]
  const stageCeiling = [0, 15, 35, 82, 92, 100, 100]

  if (logs.some(l => l.startsWith('✓ Done'))) return 100

  if (stage === 3) {
    const ip = detectItemProgress(logs)
    if (ip && ip.tot > 0) {
      const within = ip.cur / ip.tot
      return Math.round(stageFloor[3] + within * (stageCeiling[3] - stageFloor[3]))
    }
  }
  return stageFloor[stage] ?? 0
}

// ── Derive a human-readable "currently doing" string from logs ───────────────
function getCurrentAction(logs, stage, isDone) {
  if (isDone) return 'Processing complete!'
  if (stage === 0) return 'Starting up…'

  // Scan from the end for the most specific recent message
  for (let i = logs.length - 1; i >= 0; i--) {
    const l = logs[i].trim()
    // Heartbeat / waiting (emitted every 15 s while lookups are in flight)
    if (l.includes('⏳') || l.toLowerCase().includes('waiting for web lookup'))
      return `Still running web lookups… server is working, please wait`
    // Per-item timeout fallback
    if (/⚠ Item \d+/.test(l) && l.includes('timed out'))
      return `Item lookup timed out — continuing with invoice values`
    if (/⚠ Item \d+/.test(l) && l.includes('error'))
      return `Item error — continuing with available data`
    if (l.startsWith('[lookup] Searching'))
      return `Web lookup: ${l.replace(/.*Searching web for pack\/UOM:\s*/i, '')}`
    if (l.startsWith('[lookup] Found'))
      return `Lookup complete — ${l.replace(/.*Found\s*—\s*/i, '')}`
    if (l.startsWith('[lookup] Nothing'))
      return 'Lookup returned no results — using invoice values'
    if (/^\s*Item \d+\/\d+:/.test(l)) {
      const m = l.match(/Item (\d+)\/(\d+):\s*(.+)/)
      if (m) return `Normalizing item ${m[1]} of ${m[2]}: ${m[3]}`
    }
    if (l.includes('Sending invoice text to Claude'))
      return 'Waiting for Claude to parse the invoice… (15–45 s)'
    if (l.includes('[2/5]')) return 'Sending invoice to Claude for AI extraction…'
    if (l.includes('[3/5]')) return 'Normalizing UOM and pricing for each line item…'
    if (l.includes('[4/5]')) return 'Building structured result…'
    if (l.includes('[5/5]')) return 'Running hallucination / accuracy checks…'
    if (l.includes('Cross-referencing')) return 'Cross-referencing extracted values against source PDF…'
    if (l.includes('[1/5]')) return 'Extracting text from PDF…'
    if (l.startsWith('Done.')) return l
  }
  return PIPELINE_STAGES[stage - 1]?.hint || 'Processing…'
}

// ── Processing progress ─────────────────────────────────────────────────────
function ProgressCard({ current, total, logs, currentFile }) {
  const stage   = detectStage(logs)
  const itemPct = detectItemProgress(logs)
  const pct     = calcPct(stage, logs)
  const isDone  = logs.some(l => l.startsWith('✓ Done'))
  const logRef  = useRef(null)

  const currentAction = getCurrentAction(logs, stage, isDone)

  // Auto-scroll log to bottom whenever a new line arrives
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  // All log lines except the generic "Starting …" opener
  const displayLogs = logs.filter(l => !l.startsWith('Starting '))

  return (
    <div className={`progress-card enhanced${isDone ? ' done' : ''}`}>

      {/* ── Header ── */}
      <div className="progress-header">
        <div className="progress-filename">
          {isDone
            ? <span className="progress-done-icon">✓</span>
            : <span className="progress-spinner-lg" />}
          <span className="progress-file-label" title={currentFile}>
            {currentFile || `File ${current}`}
          </span>
        </div>
        {total > 1 && (
          <span className="progress-counter">{current} / {total}</span>
        )}
      </div>

      {/* ── Stage stepper ── */}
      <div className="stage-track">
        <div className="stage-line" />
        {PIPELINE_STAGES.map(s => {
          const status = stage > s.id ? 'done' : stage === s.id ? 'active' : 'pending'
          return (
            <div key={s.id} className={`stage-step ${status}`} title={s.hint}>
              <div className="stage-dot">
                {status === 'done' ? '✓' : s.icon}
              </div>
              <div className="stage-label">{s.label}</div>
            </div>
          )
        })}
      </div>

      {/* ── Progress bar ── */}
      <div className="progress-bar-row">
        <div className="progress-bar">
          <div
            className={`progress-fill${isDone ? '' : ' shimmer'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="progress-pct">{pct}%</span>
      </div>

      {/* ── "Now doing" callout ── */}
      <div className={`now-doing${isDone ? ' now-doing-done' : ''}`}>
        {!isDone && <span className="now-doing-pulse" />}
        {isDone && <span className="now-doing-check">✓</span>}
        <span className="now-doing-text">{currentAction}</span>
      </div>

      {/* ── Item counter while normalising ── */}
      {stage === 3 && itemPct && !isDone && (
        <div className="item-counter">
          Items completed: {itemPct.cur} / {itemPct.tot}
        </div>
      )}

      {/* ── Full scrollable log ── */}
      {displayLogs.length > 0 && (
        <div className="progress-log" ref={logRef}>
          {displayLogs.map((l, i) => {
            const isLookup   = l.includes('[lookup]')
            const isWaiting  = l.includes('⏳') || l.toLowerCase().includes('waiting for web lookup')
            const isWarning  = /⚠ Item \d+/.test(l)
            const isResult   = l.trim().startsWith('→')
            const isError    = !isWarning && (l.toLowerCase().includes('error') || l.toLowerCase().includes('fail'))
            const isDoneLn   = l.startsWith('✓') || l.startsWith('Done.')
            const isStage    = /^\[[\d]\/5\]/.test(l.trim())
            const cls = isError    ? 'log-error'
                      : isDoneLn   ? 'log-done'
                      : isWarning  ? 'log-warning'
                      : isWaiting  ? 'log-waiting'
                      : isLookup   ? 'log-lookup'
                      : isResult   ? 'log-result'
                      : isStage    ? 'log-stage'
                      : ''
            return (
              <div key={i} className={`progress-log-line ${cls}`}>{l}</div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Main App ────────────────────────────────────────────────────────────────
export default function App() {
  const [settings, setSettings] = useState({
    enableLookup: true,
    escalationThreshold: 0.5,
  })

  const [results, setResults] = useState([])
  const [activeTab, setActiveTab] = useState(0)
  const [processing, setProcessing] = useState(null)   // { current, total, logs }
  const [error, setError] = useState(null)
  const [showSaved, setShowSaved] = useState(false)

  const handleFiles = async (files) => {
    setError(null)
    const queue = [...files]
    setProcessing({ current: 0, total: queue.length, logs: [], currentFile: '' })

    const newResults = []
    for (let i = 0; i < queue.length; i++) {
      const file = queue[i]
      // Reset logs per-file so the progress card reflects the current file only
      setProcessing(p => ({
        ...p,
        current: i + 1,
        currentFile: file.name,
        logs: [`Starting ${file.name}…`],
      }))
      try {
        const result = await processInvoice(file, (msg) => {
          setProcessing(p => ({ ...p, logs: [...p.logs, msg] }))
        })
        newResults.push(result)
        setProcessing(p => ({
          ...p,
          logs: [...p.logs, `✓ Done: ${file.name}`],
        }))
      } catch (e) {
        setError(`Failed to process "${file.name}": ${e.message}`)
      }
    }

    setResults(prev => {
      const merged = [...prev]
      for (const r of newResults) {
        const exists = merged.findIndex(x => x.invoice_file === r.invoice_file)
        if (exists >= 0) merged[exists] = r
        else merged.push(r)
      }
      return merged
    })
    setActiveTab(results.length)    // jump to first new result

    // Keep progress card visible for 2.5 s so the user can read the final log
    await new Promise(r => setTimeout(r, 2500))
    setProcessing(null)
  }

  const clearAll = () => {
    setResults([])
    setActiveTab(0)
    setError(null)
  }

  const downloadAll = () => {
    const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = 'all_invoices_output.json'; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="layout">
      <Sidebar settings={settings} onSettings={setSettings} />

      <main className="main">
        <div className="page-header">
          <h1>Invoice Processing</h1>
          <p>Upload supplier PDFs to extract, normalize, and price every line item automatically.</p>
        </div>

        {/* Upload */}
        <UploadZone onFiles={handleFiles} />

        {/* Processing progress */}
        {processing && (
          <ProgressCard
            current={processing.current}
            total={processing.total}
            logs={processing.logs}
            currentFile={processing.currentFile}
          />
        )}

        {/* Error banner */}
        {error && (
          <div className="alert error">
            {error}
          </div>
        )}

        {/* Results */}
        {results.length > 0 && (
          <>
            <MetricsBar results={results} />

            {/* Tab bar */}
            <div className="tabs-bar">
              {results.map((r, i) => (
                <button
                  key={i}
                  className={`tab-btn${activeTab === i ? ' active' : ''}`}
                  onClick={() => setActiveTab(i)}
                  title={r.invoice_file}
                >
                  {r.invoice_file}
                </button>
              ))}
            </div>

            {/* Active invoice */}
            <InvoiceView
              result={results[activeTab]}
              escalationThreshold={settings.escalationThreshold}
            />

            {/* Bulk actions */}
            <div className="flex gap-2" style={{ marginTop: 20, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
              <button className="btn btn-outline" onClick={downloadAll}>
                ⬇ Download All JSON
              </button>
              <button className="btn btn-danger" onClick={clearAll}>
                Clear session
              </button>
            </div>
          </>
        )}

        {/* Empty state */}
        {!results.length && !processing && (
          <div className="empty-state">
            <div className="empty-icon">📂</div>
            <div className="empty-title">No invoices processed yet</div>
            <div className="empty-sub">Drop a PDF above to get started</div>
          </div>
        )}

        {/* Divider */}
        <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '32px 0 24px' }} />

        {/* Previously processed */}
        <button
          className="btn btn-outline btn-sm"
          style={{ marginBottom: 16 }}
          onClick={() => setShowSaved(s => !s)}
        >
          {showSaved ? 'Hide' : 'Show'} previously processed files
        </button>

        {showSaved && (
          <SavedPanel onSelect={result => {
            setResults(prev => {
              const exists = prev.findIndex(x => x.invoice_file === result.invoice_file)
              if (exists >= 0) {
                setActiveTab(exists)
                return prev
              }
              setActiveTab(prev.length)
              return [...prev, result]
            })
          }} />
        )}
      </main>
    </div>
  )
}
