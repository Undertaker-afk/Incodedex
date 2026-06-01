import React, { useState } from 'react'
import { api } from '../api/client'

// "Ask the codebase" — grounded RAG. LFM rewrites the question, the embedding
// index retrieves source, and the model answers with [ref N] citations that map
// to clickable file/index references.
export default function AskPanel({ onSelect }) {
  const [q, setQ] = useState('')
  const [ans, setAns] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const ask = async (e) => {
    e?.preventDefault()
    if (!q.trim()) return
    setBusy(true); setErr(''); setAns(null)
    try {
      const r = await api.ask(q, 8)
      if (r.error) setErr(r.error)
      else setAns(r)
    } catch (e) {
      setErr('Request failed. Is the index built and the backend running?')
    } finally { setBusy(false) }
  }

  // Render [ref N] markers as clickable chips.
  const renderAnswer = (text, refs) => {
    const parts = String(text).split(/(\[ref \d+\])/g)
    return parts.map((p, i) => {
      const m = p.match(/\[ref (\d+)\]/)
      if (m) {
        const r = refs.find((x) => x.ref === Number(m[1]))
        return (
          <span key={i} className="refchip" title={r ? `${r.path}:${r.start_line}` : ''}
            onClick={() => r && onSelect && onSelect(r.node_id)}>[ref {m[1]}]</span>
        )
      }
      return <span key={i}>{p}</span>
    })
  }

  return (
    <div className="ask">
      <form onSubmit={ask}>
        <textarea value={q} onChange={(e) => setQ(e.target.value)} rows={2}
          placeholder="Ask about the codebase…  e.g. How does inheritance resolution work?" />
        <button type="submit" disabled={busy}>{busy ? 'Thinking…' : 'Ask'}</button>
      </form>
      {err && <div className="askerr">{err}</div>}
      {ans && (
        <div className="answer">
          {ans.rewritten?.length > 0 && (
            <div className="rewritten">queries: {ans.rewritten.join(' · ')}</div>
          )}
          <div className="atext">{renderAnswer(ans.answer, ans.references)}</div>
          <div className="abackend">grounded via {ans.backend}</div>
          <h4>References</h4>
          {ans.references.map((r) => (
            <div key={r.ref} className="aref" onClick={() => onSelect && onSelect(r.node_id)}>
              <span className="refnum">[{r.ref}]</span>
              <span className={`chip k-${r.kind}`}>{r.kind}</span>
              <span className="arname">{r.name}</span>
              <div className="rpath">{r.path}:{r.start_line} · score {r.score}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
