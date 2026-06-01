// Owns the live graph state: loads the initial graph, then applies streamed
// pipeline events (node_add / node_update / edge_add / node_remove) in place so
// the graph grows and recolours node-by-node during indexing.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, connectSocket } from '../api/client'

export function useGraphStream() {
  const [nodes, setNodes] = useState([])
  const [links, setLinks] = useState([])
  const [phase, setPhase] = useState('')
  const [stats, setStats] = useState(null)
  const [indexing, setIndexing] = useState(false)
  const [logLine, setLogLine] = useState('')
  const nodeMap = useRef(new Map())
  const linkSet = useRef(new Set())

  const commit = useCallback(() => {
    setNodes(Array.from(nodeMap.current.values()))
  }, [])

  const upsertNode = useCallback((n) => {
    const cur = nodeMap.current.get(n.id) || {}
    nodeMap.current.set(n.id, { ...cur, ...n })
  }, [])

  const loadInitial = useCallback(async () => {
    const g = await api.graph()
    nodeMap.current = new Map(g.nodes.map((n) => [n.id, n]))
    linkSet.current = new Set(g.edges.map((e) => e.id))
    setLinks(g.edges.map((e) => ({ ...e })))
    commit()
  }, [commit])

  useEffect(() => {
    loadInitial().catch(() => {})
    const socket = connectSocket((evt) => {
      switch (evt.type) {
        case 'node_add':
        case 'node_update': {
          upsertNode(evt)
          break
        }
        case 'edge_add': {
          if (!linkSet.current.has(evt.id)) {
            linkSet.current.add(evt.id)
            setLinks((prev) => [...prev, { id: evt.id, source: evt.source, target: evt.target, kind: evt.kind, resolved: evt.resolved }])
          }
          break
        }
        case 'node_remove': {
          nodeMap.current.delete(evt.id)
          commit()
          break
        }
        case 'phase': setPhase(evt.message || evt.phase); setIndexing(true); break
        case 'log': setLogLine(evt.message || ''); break
        case 'stats': setStats(evt); break
        case 'done': setStats(evt); setIndexing(false); setPhase('done'); commit(); loadInitial().catch(() => {}); break
        default: break
      }
    })
    // throttle re-render of nodes during streaming
    const timer = setInterval(commit, 250)
    return () => { socket.close(); clearInterval(timer) }
  }, [loadInitial, upsertNode, commit])

  return { nodes, links, phase, stats, indexing, logLine, reload: loadInitial }
}
