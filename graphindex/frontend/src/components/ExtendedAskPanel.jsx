import React, { useEffect, useRef, useState } from 'react'
import { api, connectExtSocket } from '../api/client'

// Deep, multi-agent investigation ("extended_ask"). Streams keyword rounds,
// agent focuses/findings per round, then a final grounded answer + references
// + token-saving stats. Designed to let a coding agent understand a codebase
// while spending the fewest possible tokens.
export default function ExtendedAskPanel({ onSelect }) {
  const [q, setQ] = useState('')
  const [rounds, setRounds] = useState(3)
  const [agents, setAgents] = useState(3)
  const [kwRounds, setKwRounds] = useState(2)
  const [running, setRunning] = useState(false)
  const [phase, setPhase] = useState('')
  const [keywords, setKeywords] = useState([])
  const [activity, setActivity] = useState([])
  const [result, setResult] = useState(null)
  const [err, setErr] = useState('')
  const sockRef = useRef(null)

  useEffect(() => {
    const socket = connectExtSocket((evt) => {
      switch (evt.type) {
        case 'ext_phase': setPhase(evt.message || evt.phase); break
        case 'ext_keywords':
          setKeywords((k) => [...k, { round: evt.round, keywords: evt.keywords }]); break
        case 'ext_agent_start':
          setActivity((a) => [...a, { kind: 'start', focus: evt.focus }]); break
        case 'ext_agent_done':
          setActivity((a) => [...a, { kind: 'done', focus: evt.focus, findings: evt.findings, refs: evt.refs }]); break
        case 'ext_done':
          setResult({ answer: evt.answer, references: evt.references, stats: evt.stats })
          setRunning(false); setPhase('done'); break
        default: break
      }
    })
    sockRef.current = socket
    return () => socket.close()
  }, [])

  const run = async (e) => {
    e?.preventDefault()
    if (!q.trim() || running) return
    setRunning(true); setErr(''); setResult(null); setKeywords([]); setActivity([]); setPhase('starting…')
    try {
      const r = await api.extendedAsk({ question: q, max_rounds: rounds, agents_per_round: agents, keyword_rounds: kwRounds })
      if (r.status === 'already_running') { setErr('An investigation is already running.'); setRunning(false) }
    } catch {
      setErr('Request failed.'); setRunning(false)
    }
  }

  const renderAnswer = (text, refs) => String(text).split(/(\[ref \d+\])/g).map((p, i) => {
    const m = p.match(/\[ref (\d+)\]/)
    if (m) {
      const r = refs.find((x) => x.ref === Number(m[1]))
      return <span key={i} className="refchip" title={r ? `${r.path}:${r.start_line}` : ''}
        onClick={() => r && onSelect && onSelect(r.node_id)}>[ref {m[1]}]</span>
    }
    return <span key={i}>{p}</span>
  })

  return (
    <div className="ask">
      <form onSubmit={run}>
        <textarea value={q} onChange={(e) => setQ(e.target.value)} rows={2}
          placeholder="Deep question… runs parallel agents over the index + source" />
        <div className="caps">
          <label>rounds<input type="number" min="1" max="10" value={rounds}
            onChange={(e) => setRounds(+e.target.value)} /></label>
          <label>agents<input type="number" min="1" max="3" value={agents}
            onChange={(e) => setAgents(+e.target.value)} /></label>
          <label>kw<input type="number" min="1" max="4" value={kwRounds}
            onChange={(e) => setKwRounds(+e.target.value)} /></label>
        </div>
        <button type="submit" disabled={running}>{running ? 'Investigating…' : 'Run deep investigation'}</button>
      </form>
      {err && <div className="askerr">{err}</div>}
      {(running || phase) && <div className="phase">▸ {phase}</div>}

      {keywords.length > 0 && (
        <div className="kwbox">
          {keywords.map((k) => (
            <div key={k.round} className="rewritten">round {k.round} keywords: {k.keywords.join(', ')}</div>
          ))}
        </div>
      )}

      {activity.length > 0 && !result && (
        <div className="activity">
          {activity.map((a, i) => (
            <div key={i} className={`act ${a.kind}`}>
              {a.kind === 'start' ? '⟳ agent: ' : '✓ '}{a.focus}
              {a.findings && <div className="actfind">{a.findings}</div>}
            </div>
          ))}
        </div>
      )}

      {result && (
        <div className="answer">
          <div className="atext">{renderAnswer(result.answer, result.references)}</div>
          {result.stats && (
            <div className="savings">
              🪙 {result.stats.references} refs · inspected {result.stats.nodes_inspected} nodes ·
              read {result.stats.files_read} source ranges · {result.stats.llm_calls} local LLM calls ·
              ~{Math.round((result.stats.estimated_full_file_chars || 0) / 4)} tokens of full files distilled
            </div>
          )}
          <h4>References</h4>
          {result.references.map((r) => (
            <div key={r.ref} className="aref" onClick={() => onSelect && onSelect(r.node_id)}>
              <span className="refnum">[{r.ref}]</span>
              <span className={`chip k-${r.kind}`}>{r.kind}</span>
              <span className="arname">{r.name}</span>
              <div className="rpath">{r.path}:{r.start_line}{r.params ? ` · ${r.params}` : ''}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
