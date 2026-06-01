import React, { useEffect, useState } from 'react'
import GraphView from './components/GraphView'
import Sidebar from './components/Sidebar'
import SearchBar from './components/SearchBar'
import NodeInspector from './components/NodeInspector'
import { useGraphStream } from './hooks/useGraphStream'
import { api } from './api/client'

export default function App() {
  const { nodes, links, phase, stats, indexing, logLine } = useGraphStream()
  const [config, setConfig] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => { api.config().then(setConfig).catch(() => {}) }, [])

  const onIndex = () => api.index({ summarize: true, embed: true }).catch(() => {})
  const onPrune = () => api.prune().catch(() => {})
  const selectById = (n) => setSelected(n.id || n)

  return (
    <div className="app">
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

      <div className="right">
        <NodeInspector nodeId={selected} onSelect={selectById} />
      </div>
    </div>
  )
}
