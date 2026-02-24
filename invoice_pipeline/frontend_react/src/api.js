// In production set VITE_API_URL to your deployed backend root URL,
// e.g.  VITE_API_URL=https://invoice-pipeline-api.onrender.com
// In development leave it unset — the Vite proxy rewrites /api → localhost:8000
const BASE = import.meta.env.VITE_API_URL || '/api'

export async function checkHealth() {
  const res = await fetch(`${BASE}/health`)
  if (!res.ok) throw new Error('API unreachable')
  return res.json()
}

/**
 * Upload a PDF and process it, streaming real-time progress via SSE.
 * @param {File} file - The PDF file to upload.
 * @param {(msg: string) => void} onProgress - Called for each progress log line.
 * @returns {Promise<object>} - The full invoice result JSON.
 */
export async function processInvoice(file, onProgress) {
  const fd = new FormData()
  fd.append('file', file)

  const res = await fetch(`${BASE}/process/stream`, { method: 'POST', body: fd })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Processing failed')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''   // keep any incomplete trailing line

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      let event
      try {
        event = JSON.parse(line.slice(6))
      } catch {
        continue
      }
      if (event.type === 'log' && onProgress) {
        onProgress(event.message)
      } else if (event.type === 'result') {
        result = event.data
      } else if (event.type === 'error') {
        throw new Error(event.message)
      }
    }
  }

  if (!result) throw new Error('No result received from server')
  return result
}

export async function listResults() {
  const res = await fetch(`${BASE}/results`)
  if (!res.ok) throw new Error('Could not fetch results')
  return res.json()
}
