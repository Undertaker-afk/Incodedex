import React, { useEffect, useMemo, useRef } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { nodeFill, hasWarning, WARNING_OUTLINE } from '../colors'

// The Obsidian-style force-directed graph. Nodes are drawn as circles sized by
// degree, coloured by lifecycle state, with a purple ring for warnings.
export default function GraphView({ nodes, links, onSelect, selectedId }) {
  const fgRef = useRef()
  const data = useMemo(() => ({ nodes, links }), [nodes, links])

  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return
    fg.d3Force('charge')?.strength(-40)
    fg.d3Force('link')?.distance(28)
  }, [])

  return (
    <ForceGraph2D
      ref={fgRef}
      graphData={data}
      backgroundColor="#0d1117"
      cooldownTicks={120}
      warmupTicks={20}
      nodeRelSize={3}
      nodeLabel={(n) => `${n.kind}: ${n.label || n.id}\n${n.path || ''}`}
      linkColor={(l) => (l.resolved === false ? 'rgba(240,136,62,0.35)' : 'rgba(140,150,170,0.22)')}
      linkWidth={(l) => (l.kind === 'inherits' ? 1.4 : 0.6)}
      onNodeClick={(n) => onSelect && onSelect(n)}
      nodeCanvasObject={(node, ctx, scale) => {
        const deg = node.degree || 0
        const r = Math.max(2.2, Math.min(10, 2.2 + Math.sqrt(deg) * 1.4))
        ctx.beginPath()
        ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false)
        ctx.fillStyle = nodeFill(node)
        ctx.fill()
        if (hasWarning(node)) {
          ctx.lineWidth = 1.6 / scale
          ctx.strokeStyle = WARNING_OUTLINE
          ctx.stroke()
        }
        if (node.id === selectedId) {
          ctx.lineWidth = 2.2 / scale
          ctx.strokeStyle = '#ffffff'
          ctx.stroke()
        }
        if (scale > 3 && (node.is_hub || node.id === selectedId)) {
          ctx.fillStyle = '#c9d1d9'
          ctx.font = `${3.2}px sans-serif`
          ctx.fillText(node.label || '', node.x + r + 1, node.y + 1)
        }
      }}
      nodePointerAreaPaint={(node, color, ctx) => {
        const deg = node.degree || 0
        const r = Math.max(3, Math.min(11, 2.2 + Math.sqrt(deg) * 1.4))
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false)
        ctx.fill()
      }}
    />
  )
}
