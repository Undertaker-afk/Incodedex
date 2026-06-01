// Owns the live graph state: loads the initial graph, then applies streamed
// pipeline events (node_add / node_update / edge_add / node_remove) in place.
//
// Two important details that keep the graph from "spinning":
//   1. node updates MUTATE the existing node object (Object.assign) so the
//      force simulation's x/y/vx/vy are preserved — replacing the object would
//      teleport the node every update.
//   2. we only publish a new nodes array (which reheats the sim) when something
//      actually changed (dirty flag), so once streaming stops the graph settles.
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
  const dirty = useRef(false)

  const commit = useCallback(() => {
    setNodes(Array.from(nodeMap.current.values()))
  }, [])

  const loadInitial = useCallback(async () => {
    const g = await api.graph()
    nodeMap.current = new Map(g.nodes.map((n) => [n.id, { ...n }]))
    linkSet.current = new Set(g.edges.map((e) => e.id))
    setLinks(g.edges.map((e) => ({ ...e })))
    commit()
  }, [commit])

  useEffect(() => {
    loadInitial().catch(() => {})
    const socket = connectSocket((evt) => {
      switch (evt.type) {
        case 'node_add': {
          if (!nodeMap.current.has(evt.id)) nodeMap.current.set(evt.id, { ...evt })
          else Object.assign(nodeMap.current.get(evt.id), evt)
          dirty.current = true
          break
        }
        case 'node_update': {
          const cur = nodeMap.current.get(evt.id)
          if (cur) Object.assign(cur, evt)           // preserve x/y position
          else nodeMap.current.set(evt.id, { ...evt })
          dirty.current = true
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
          dirty.current = true
          break
        }
        case 'phase': setPhase(evt.message || evt.phase); setIndexing(true); break
        case 'log': setLogLine(evt.message || ''); break
        case 'stats': setStats(evt); break
        case 'done':
          setStats(evt); setIndexing(false); setPhase('done')
          dirty.current = true
          setTimeout(() => loadInitial().catch(() => {}), 200)
          break
        default: break
      }
    })
    // Publish a fresh nodes array only when something changed — this lets the
    // force simulation cool down and stop once streaming is idle.
    const timer = setInterval(() => {
      if (dirty.current) { dirty.current = false; commit() }
    }, 300)
    return () => { socket.close(); clearInterval(timer) }
  }, [loadInitial, commit])

  return { nodes, links, phase, stats, indexing, logLine, reload: loadInitial }
}
