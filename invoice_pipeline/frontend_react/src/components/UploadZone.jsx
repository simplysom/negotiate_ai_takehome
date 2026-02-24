import { useState, useRef } from 'react'

export default function UploadZone({ onFiles }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef()

  const handleDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.pdf'))
    if (files.length) onFiles(files)
  }

  const handleChange = (e) => {
    const files = Array.from(e.target.files)
    if (files.length) onFiles(files)
    e.target.value = ''
  }

  return (
    <div className="upload-card">
      <div className="upload-row">
        <div
          className={`dropzone${dragging ? ' active' : ''}`}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current.click()}
        >
          <div className="dropzone-icon">📂</div>
          <div className="dropzone-title">Drop PDF invoices here</div>
          <div className="dropzone-sub">or click to browse your computer</div>
          <button className="dropzone-btn" type="button">Choose files</button>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            multiple
            style={{ display: 'none' }}
            onChange={handleChange}
          />
        </div>

        <ul className="upload-hint">
          <strong>Supported formats</strong>
          <li>Any supplier PDF</li>
          <li>Multi-page invoices</li>
          <li>Embedded tables</li>
          <li>Missing / mixed UOM</li>
          <li>Pack expressions (25/CS…)</li>
        </ul>
      </div>
    </div>
  )
}
