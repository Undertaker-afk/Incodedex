import React, { useEffect, useState } from 'react'
import { api } from '../api/client'

// Detail panel for a selected node: summary, tags, code intelligence
// (callers/callees, inheritance, references) resolved from the backend.
export default function NodeInspector({ nodeId, onSelect }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    if (!nodeId) { setData(null); return }
    api.node(nodeId).then(setData).catch(() => setData(null))
  }, [nodeId])

  if (!nodeId) return <div className="inspector empty">Select a node to inspect.</div>
  if (!data || data.error) return <div className="inspector">Loading…</div>
  const n = data.node
  const Section = ({ title, items }) => items?.length ? (
    <div className="isec">
      <h4>{title} <span>{items.length}</span></h4>
      {items.map((x) => (
        <div key={x.id} className="ilink" onClick={() => onSelect && onSelect(x)}>
          <span className={`chip k-${x.kind}`}>{x.kind}</span> {x.name}
          <span className="ipath">{x.path}</span>
        </div>
      ))}
    </div>
  ) : null

  return (
    <div className="inspector">
      <div className="ihead">
        <span className={`chip k-${n.kind}`}>{n.kind}</span>
        <span className="iname">{n.name}</span>
      </div>
      <div className="ipath">{n.path}:{n.start_line}</div>
      {n.signature && <pre className="isig">{n.signature}</pre>}
      {n.summary && <p className="isum">{n.summary}</p>}
      {n.tags?.length > 0 && (
        <div className="itags">{n.tags.map((t) => <span key={t} className="tag">{t}</span>)}</div>
      )}
      {n.flags?.length > 0 && (
        <div className="iflags">{n.flags.map((f) => <span key={f} className="flag">⚠ {f}</span>)}</div>
      )}
      <div className="imeta">degree {n.degree} · {n.language} · {n.state}</div>
      <Section title="Callers" items={data.callers} />
      <Section title="Callees" items={data.callees} />
      <Section title="Inherits from" items={data.ancestors} />
      <Section title="Subclasses" items={data.descendants} />
      <Section title="References" items={data.references} />
    </div>
  )
}
