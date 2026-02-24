import { useState, useEffect } from 'react'
import { checkHealth } from '../api.js'

export default function Sidebar({ settings, onSettings }) {
  const [apiOk, setApiOk] = useState(null)

  useEffect(() => {
    checkHealth()
      .then(d => setApiOk(d.api_key_set))
      .catch(() => setApiOk(false))
  }, [])

  return (
    <aside className="sidebar">
      <div className="sb-logo">
        <div className="sb-logo-title">📄 Invoice Pipeline</div>
        <div className="sb-logo-sub">Powered by Claude AI</div>
      </div>

      <div className="sb-section">
        <div className="sb-section-label">Status</div>
        {apiOk === null && (
          <span className="sb-pill" style={{ color: '#6B7280', border: '1px solid #374151' }}>
            Checking…
          </span>
        )}
        {apiOk === true && (
          <span className="sb-pill ok">
            <span className="sb-pill-dot" /> API key ready
          </span>
        )}
        {apiOk === false && (
          <>
            <span className="sb-pill err">
              <span className="sb-pill-dot" /> API key missing
            </span>
            <p style={{ fontSize: '.72rem', color: '#6B7280', marginTop: 8 }}>
              Add ANTHROPIC_API_KEY to .env and restart the API server.
            </p>
          </>
        )}
      </div>

      <div className="sb-section">
        <div className="sb-section-label">Settings</div>

        <div className="sb-setting">
          <div className="sb-toggle-row">
            <span className="sb-toggle-label">Agentic web lookup</span>
            <label className="toggle">
              <input
                type="checkbox"
                checked={settings.enableLookup}
                onChange={e => onSettings({ ...settings, enableLookup: e.target.checked })}
              />
              <div className="toggle-track" />
              <div className="toggle-thumb" />
            </label>
          </div>
        </div>

        <div className="sb-setting">
          <label>
            Escalation threshold
            <span className="range-val">{settings.escalationThreshold.toFixed(2)}</span>
          </label>
          <input
            type="range"
            min="0.1" max="0.9" step="0.05"
            value={settings.escalationThreshold}
            onChange={e => onSettings({ ...settings, escalationThreshold: parseFloat(e.target.value) })}
          />
        </div>
      </div>

      <div className="sb-footer">v1.0 · Invoice Pipeline</div>
    </aside>
  )
}
