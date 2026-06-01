// Single source of truth for the node colour state machine — mirrors
// graphindex/graph/model.py STATE_COLORS. Drives the live graph in GraphView.

export const STATE_COLORS = {
  discovered: '#9aa0a6', // gray  – file/symbol found
  parsed: '#f2c744',     // yellow – AST parsed
  embedded: '#4f8ff7',   // blue   – vector stored
  summarized: '#3fb950', // green  – summarized/tagged
  hub: '#f85149',        // red    – high-degree hub
  unresolved: '#f0883e', // orange – unresolved reference
}

export const WARNING_OUTLINE = '#a371f7' // purple – duplicate / dead-code

export function nodeFill(node) {
  if (node.state === 'unresolved' || node.kind === 'external') return STATE_COLORS.unresolved
  if (node.is_hub) return STATE_COLORS.hub
  return STATE_COLORS[node.state] || STATE_COLORS.discovered
}

export function hasWarning(node) {
  return Array.isArray(node.flags) && node.flags.length > 0
}

export const LEGEND = [
  { color: STATE_COLORS.discovered, label: 'discovered' },
  { color: STATE_COLORS.parsed, label: 'parsed' },
  { color: STATE_COLORS.embedded, label: 'embedded' },
  { color: STATE_COLORS.summarized, label: 'summarized' },
  { color: STATE_COLORS.hub, label: 'hub (high degree)' },
  { color: STATE_COLORS.unresolved, label: 'unresolved ref' },
  { color: WARNING_OUTLINE, label: 'duplicate / dead code', outline: true },
]
