import React, { useEffect, useRef, useState } from 'react'
import { api, connectExtSocket } from '../api/client'

// Deep, multi-agent investigation ("extended_ask"). Streams keyword rounds,
// agent focuses/findings per round, then a final grounded answer + references
// + token-saving stats.
export default function ExtendedAskPanel({ onSelect }) {
  const [q, setQ] = useState('')
  const [rounds, setRounds] = useState(3)
  const [agents, setAgents] = useState(3)
  const [kwRounds, setKwRounds] = useState(2)
  const [running, setRunning] = useState(false)
  const [phase, setPhase] = useState('')
  const [keywords, setKeywords] = useState([])
  const [activity, setActivity] = useState([])
  const [flow, setFlow] = useState([])
  const [showFlow, setShowFlow] = useState(false)
  const [openFlowAgents, setOpenFlowAgents] = useState({})
  const [result, setResult] = useState(null)
  const [err, setErr] = useState('')
  const sockRef = useRef(null)

  useEffect(() => {
    const socket = connectExtSocket((evt) => {
      switch (evt.type) {
        case 'ext_phase':
          setPhase(evt.message || evt.phase)
          setFlow((f) => [...f, {
            kind: 'phase', phase: evt.phase, message: evt.message, round: evt.round,
          }])
          break
        case 'ext_keywords':
          setKeywords((k) => [...k, { round: evt.round, keywords: evt.keywords || [] }])
          setFlow((f) => [...f, {
            kind: 'keywords', round: evt.round, keywords: evt.keywords || [],
          }])
          break
        case 'ext_agent_start':
          setActivity((a) => upsertAgent(a, {
            status: 'running', round: evt.round, focus: evt.focus,
          }))
          setFlow((f) => [...f, {
            kind: 'agent_start', round: evt.round, focus: evt.focus,
          }])
          break
        case 'ext_agent_done':
          setActivity((a) => upsertAgent(a, eventToAgent(evt)))
          setFlow((f) => [...f, eventToFlowAgent(evt)])
          break
        case 'ext_done':
          setResult({ answer: evt.answer, references: evt.references || [], stats: evt.stats })
          setFlow((f) => [...f, {
            kind: 'done', stats: evt.stats, references: evt.references || [],
          }])
          setRunning(false)
          setPhase('done')
          break
        default:
          break
      }
    })
    sockRef.current = socket
    return () => socket.close()
  }, [])

  const run = async (e) => {
    e?.preventDefault()
    if (!q.trim() || running) return
    setRunning(true)
    setErr('')
    setResult(null)
    setKeywords([])
    setActivity([])
    setOpenFlowAgents({})
    setShowFlow(false)
    setFlow([{ kind: 'phase', phase: 'starting', message: 'starting...' }])
    setPhase('starting...')
    try {
      const r = await api.extendedAsk({
        question: q, max_rounds: rounds, agents_per_round: agents, keyword_rounds: kwRounds,
      })
      if (r.status === 'already_running') {
        setErr('An investigation is already running.')
        setRunning(false)
      }
    } catch {
      setErr('Request failed.')
      setRunning(false)
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

  const toggleFlowAgent = (id) => setOpenFlowAgents((open) => ({ ...open, [id]: !open[id] }))

  const refForNode = (nodeId) => result?.references?.find((x) => x.node_id === nodeId)

  const renderRefs = (refs = []) => {
    if (!refs.length) return <div className="muted">No refs reported.</div>
    return (
      <div className="agentrefs">
        {refs.map((nodeId) => {
          const r = refForNode(nodeId)
          return (
            <button key={nodeId} type="button" title={r ? `${r.path}:${r.start_line}` : nodeId}
              onClick={(e) => { e.stopPropagation(); r && onSelect && onSelect(r.node_id) }}>
              {r ? `[ref ${r.ref}] ${r.name}` : nodeId}
            </button>
          )
        })}
      </div>
    )
  }

  const renderAgentDetails = (a) => (
    <div className="agentdetail">
      <div><b>Focus</b><p>{a.focus}</p></div>
      {a.findings && <div><b>Findings</b><p>{a.findings}</p></div>}
      {'confident' in a && <div><b>Confident</b><p>{String(Boolean(a.confident))}</p></div>}
      <div><b>Refs used</b>{renderRefs(a.refs)}</div>
      {a.wantQueries?.length > 0 && <div><b>Requested searches</b><p>{a.wantQueries.join(', ')}</p></div>}
      {a.wantNodes?.length > 0 && <div><b>Requested nodes</b><p>{a.wantNodes.join(', ')}</p></div>}
      {a.wantFiles?.length > 0 && (
        <div><b>Requested source</b>
          {a.wantFiles.map((f, i) => <p key={i}>{f.path}:{f.start}-{f.end || '?'}</p>)}
        </div>
      )}
    </div>
  )

  const renderFlowItem = (item, i) => {
    if (item.kind === 'phase') {
      return <div key={i} className="flowitem">phase: {item.message || item.phase}</div>
    }
    if (item.kind === 'keywords') {
      return <div key={i} className="flowitem">round {item.round} keywords: {item.keywords.join(', ')}</div>
    }
    if (item.kind === 'agent_start') {
      const id = flowAgentId(item)
      const current = activity.find((a) => a.id === id) || item
      return (
        <button key={i} type="button" className="flowitem flowagent"
          onClick={() => toggleFlowAgent(id)}>
          <span>round {item.round} agent running: {item.focus}</span>
          {openFlowAgents[id] && renderAgentDetails(current)}
        </button>
      )
    }
    if (item.kind === 'agent_done') {
      const refs = item.refs?.length ? `, refs ${item.refs.length}` : ''
      const asks = [
        item.wantQueries?.length ? `${item.wantQueries.length} searches` : '',
        item.wantNodes?.length ? `${item.wantNodes.length} nodes` : '',
        item.wantFiles?.length ? `${item.wantFiles.length} source reads` : '',
      ].filter(Boolean).join(', ')
      const id = flowAgentId(item)
      const current = activity.find((a) => a.id === id) || item
      return (
        <button key={i} type="button" className="flowitem flowagent done"
          onClick={() => toggleFlowAgent(id)}>
          <span>round {item.round} agent done: {item.focus}{refs}{asks ? `, requested ${asks}` : ''}</span>
          {openFlowAgents[id] && renderAgentDetails(current)}
        </button>
      )
    }
    return <div key={i} className="flowitem">done: {item.stats?.rounds || 0} rounds, {item.stats?.agents_total || 0} agents</div>
  }

  return (
    <div className="ask">
      <form onSubmit={run}>
        <textarea value={q} onChange={(e) => setQ(e.target.value)} rows={2}
          placeholder="Deep question... runs parallel agents over the index + source" />
        <div className="caps">
          <label>rounds<input type="number" min="1" max="10" value={rounds}
            onChange={(e) => setRounds(+e.target.value)} /></label>
          <label>agents<input type="number" min="1" max="3" value={agents}
            onChange={(e) => setAgents(+e.target.value)} /></label>
          <label>kw<input type="number" min="1" max="4" value={kwRounds}
            onChange={(e) => setKwRounds(+e.target.value)} /></label>
        </div>
        <button type="submit" disabled={running}>{running ? 'Investigating...' : 'Run deep investigation'}</button>
      </form>
      {err && <div className="askerr">{err}</div>}
      {(running || phase) && (
        <button type="button" className={`phase flow-toggle ${showFlow ? 'on' : ''}`}
          onClick={() => setShowFlow((v) => !v)}>
          &gt; {phase}{phase === 'done' ? ' - action flow' : ''}
        </button>
      )}

      {showFlow && (
        <div className="flowbox">
          <h4>Action flow</h4>
          {flow.map(renderFlowItem)}
        </div>
      )}

      {result && (
        <div className="answer">
          <div className="atext">{renderAnswer(result.answer, result.references)}</div>
          {result.stats && (
            <div className="savings">
              {result.stats.references} refs - inspected {result.stats.nodes_inspected} nodes -
              read {result.stats.files_read} source ranges - {result.stats.llm_calls} local LLM calls -
              ~{Math.round((result.stats.estimated_full_file_chars || 0) / 4)} tokens of full files distilled
            </div>
          )}
          <h4>References</h4>
          {result.references.map((r) => (
            <div key={r.ref} className="aref" onClick={() => onSelect && onSelect(r.node_id)}>
              <span className="refnum">[{r.ref}]</span>
              <span className={`chip k-${r.kind}`}>{r.kind}</span>
              <span className="arname">{r.name}</span>
              <div className="rpath">{r.path}:{r.start_line}{r.params ? ` - ${r.params}` : ''}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function eventToAgent(evt) {
  const id = flowAgentId(evt)
  return {
    id,
    status: 'done',
    round: evt.round,
    focus: evt.focus,
    findings: evt.findings,
    refs: evt.refs || [],
    wantNodes: evt.want_nodes || [],
    wantQueries: evt.want_queries || [],
    wantFiles: evt.want_files || [],
    confident: evt.confident,
  }
}

function upsertAgent(agents, next) {
  const id = next.id || flowAgentId(next)
  const normalized = { id, refs: [], wantNodes: [], wantQueries: [], wantFiles: [], ...next }
  const index = agents.findIndex((a) => a.id === id)
  if (index === -1) return [...agents, normalized]
  return agents.map((a, i) => (i === index ? { ...a, ...normalized } : a))
}

function flowAgentId(item) {
  return `${item.round || '?'}:${item.focus || ''}`
}

function eventToFlowAgent(evt) {
  return {
    kind: 'agent_done',
    round: evt.round,
    focus: evt.focus,
    findings: evt.findings,
    refs: evt.refs || [],
    wantNodes: evt.want_nodes || [],
    wantQueries: evt.want_queries || [],
    wantFiles: evt.want_files || [],
    confident: evt.confident,
  }
}
