import React, { useState } from 'react'
import { api } from '../api/client'

const MODES = [
  ['semantic', 'Semantic'],
  ['regex', 'Regex'],
  ['fuzzy', 'Fuzzy'],
  ['case', 'Case'],
]

// Search box with mode toggles. Supports inline filters (lang: kind: path: ...).
export default function SearchBar({ onResults, onSelect }) {
  const [q, setQ] = useState('')
  const [modes, setModes] = useState({ semantic: true })
  const [results, setResults] = useState([])
  const [busy, setBusy] = useState(false)

  const toggle = (m) => setModes((s) => ({ ...s, [m]: !s[m] }))

  const run = async (e) => {
    e?.preventDefault()
    if (!q.trim()) return
    setBusy(true)
    try {
      const opts = {}
      for (const [m] of MODES) if (modes[m]) opts[m] = 'true'
      const r = await api.search(q, opts)
      const rows = r?.results || []   // never setResults(undefined) -> render crash
      setResults(rows)
      onResults && onResults(rows)
    } catch {
      setResults([])
    } finally { setBusy(false) }
  }

  return (
    <div className="search">
      <form onSubmit={run}>
        <input value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="search…  e.g. lang:python kind:function auth token" />
        <button type="submit" disabled={busy}>{busy ? '…' : 'Search'}</button>
      </form>
      <div className="modes">
        {MODES.map(([m, label]) => (
          <label key={m} className={modes[m] ? 'on' : ''}>
            <input type="checkbox" checked={!!modes[m]} onChange={() => toggle(m)} />
            {label}
          </label>
        ))}
      </div>
      <div className="results">
        {results.map((r) => (
          <div key={r.id} className="result" onClick={() => onSelect && onSelect(r)}>
            <span className={`chip k-${r.kind}`}>{r.kind}</span>
            <span className="rname">{r.name}</span>
            <span className="rscore">{r.score}</span>
            <div className="rpath">{r.path}:{r.start_line} · {r.matched_by?.join(',')}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
