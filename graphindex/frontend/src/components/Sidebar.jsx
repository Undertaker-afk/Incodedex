import React from 'react'
import { LEGEND } from '../colors'

// Left rail: actions, live status, legend and rolling stats.
export default function Sidebar({ config, stats, indexing, phase, logLine, progress, onIndex, onPrune }) {
  const pct = progress && progress.total
    ? Math.min(100, Math.round((progress.done / progress.total) * 100))
    : 0
  return (
    <div className="sidebar">
      <div className="brand">graphindex</div>
      <div className="repo" title={config?.repo_path}>{config?.repo_path || '…'}</div>

      <div className="actions">
        <button className="primary" disabled={indexing} onClick={onIndex}>
          {indexing ? 'Indexing…' : 'Build index'}
        </button>
        <button onClick={onPrune} disabled={indexing}>Prune</button>
      </div>

      {indexing && <div className="phase">▸ {phase}</div>}
      {logLine && <div className="logline">{logLine}</div>}

      {indexing && progress && (
        <div className="progress">
          <div className="bar" role="progressbar"
            aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="prow">
            <span>{progress.phase}</span>
            <span>{progress.done}/{progress.total} ({pct}%)</span>
          </div>
          {progress.current && <div className="pcurrent" title={progress.current}>{progress.current}</div>}
        </div>
      )}

      <div className="legend">
        <h4>Node states</h4>
        {LEGEND.map((l) => (
          <div className="lrow" key={l.label}>
            <span className="dot" style={l.outline
              ? { borderColor: l.color, background: 'transparent', borderStyle: 'solid', borderWidth: 2 }
              : { background: l.color }} />
            {l.label}
          </div>
        ))}
      </div>

      {stats && (
        <div className="statbox">
          <h4>Last run</h4>
          <div>nodes <b>{stats.nodes}</b></div>
          <div>edges <b>{stats.edges}</b></div>
          <div>files <b>{stats.files}</b></div>
          <div>{stats.nodes_per_sec}/s · {stats.elapsed_sec}s</div>
          <div className="muted">embed: {stats.embedder}</div>
          <div className="muted">summ: {stats.summarizer}</div>
          <div className="muted">vec: {stats.vector_backend}</div>
        </div>
      )}
      <div className="cfgbox muted">
        backend: {config?.backend} · dim {config?.embed_dim}
      </div>
    </div>
  )
}
