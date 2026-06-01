import React, { useEffect, useRef, useState } from 'react'
import GraphView from './components/GraphView'
import Sidebar from './components/Sidebar'
import SearchBar from './components/SearchBar'
import NodeInspector from './components/NodeInspector'
import AskPanel from './components/AskPanel'
import ExtendedAskPanel from './components/ExtendedAskPanel'
import { useGraphStream } from './hooks/useGraphStream'
import { api } from './api/client'

export default function App() {
  const { nodes, links, phase, stats, indexing, logLine } = useGraphStream()
  const [config, setConfig] = useState(null)
  const [selected, setSelected] = useState(null)
  const [tab, setTab] = useState('inspect')
  const [dock, setDock] = useState('right')
  const [sidebarWidth, setSidebarWidth] = useState(320)
  const dragRef = useRef({ active: false, startX: 0, startWidth: 320 })

  useEffect(() => { api.config().then(setConfig).catch(() => {}) }, [])

  useEffect(() => {
    const onMove = (e) => {
      if (!dragRef.current.active) return
      const delta = e.clientX - dragRef.current.startX
      const dir = dock === 'right' ? -1 : 1
      const next = dragRef.current.startWidth + delta * dir
      const clamped = Math.min(720, Math.max(240, next))
      setSidebarWidth(clamped)
    }
    const onUp = () => {
      if (!dragRef.current.active) return
      dragRef.current.active = false
      document.body.style.cursor = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [dock])

  const onIndex = () => api.index({ summarize: true, embed: true }).catch(() => {})
  const onPrune = () => api.prune().catch(() => {})
  const selectById = (n) => { setSelected(n.id || n); setTab('inspect') }

  const startResize = (e) => {
    e.preventDefault()
    dragRef.current = { active: true, startX: e.clientX, startWidth: sidebarWidth }
    document.body.style.cursor = 'col-resize'
  }

  return (
    <div className={`app ${dock === 'left' ? 'dock-left' : ''}`}
      style={{ '--right-w': `${sidebarWidth}px` }}>
      <div className="left">
        <Sidebar config={config} stats={stats} indexing={indexing} phase={phase}
          logLine={logLine} onIndex={onIndex} onPrune={onPrune} />
        <SearchBar onSelect={(r) => selectById(r)} />
      </div>

      <div className="center">
        <div className="topbar">
          <span className="title">Graph view</span>
          <span className="count">{nodes.length} nodes · {links.length} edges</span>
        </div>
        <div className="graphwrap">
          <GraphView nodes={nodes} links={links} onSelect={selectById}
            selectedId={selected} />
        </div>
      </div>

      <div className={`right ${dock === 'left' ? 'dock-left' : ''}`}>
        <div className="tabs">
          <button className={tab === 'inspect' ? 'tab on' : 'tab'}
            onClick={() => setTab('inspect')}>Inspector</button>
          <button className={tab === 'ask' ? 'tab on' : 'tab'}
            onClick={() => setTab('ask')}>Ask</button>
          <button className={tab === 'deep' ? 'tab on' : 'tab'}
            onClick={() => setTab('deep')}>Deep ask</button>
          <button className="dock-btn" onClick={() => setDock(dock === 'right' ? 'left' : 'right')}>
            Dock {dock === 'right' ? 'left' : 'right'}
          </button>
        </div>
        <div className="resize-handle" onMouseDown={startResize} title="Drag to resize" />
        {/* All panels stay mounted (toggled via CSS) so a question and its
            output survive switching to the Inspector to read a reference and
            back — no need to re-ask. */}
        <div className="right-content">
          <div style={{ display: tab === 'inspect' ? 'block' : 'none' }}>
            <NodeInspector nodeId={selected} onSelect={selectById} />
          </div>
          <div style={{ display: tab === 'ask' ? 'block' : 'none' }}>
            <AskPanel onSelect={selectById} />
          </div>
          <div style={{ display: tab === 'deep' ? 'block' : 'none' }}>
            <ExtendedAskPanel onSelect={selectById} />
          </div>
        </div>
      </div>
    </div>
  )
}
