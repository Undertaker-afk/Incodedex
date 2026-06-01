// REST + WebSocket client. Same-origin when served by Flask; proxied in dev.
import { io } from 'socket.io-client'

const BASE = '' // same origin

export async function getJSON(path) {
  const r = await fetch(BASE + path)
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json()
}

export async function postJSON(path, body) {
  const r = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  })
  return r.json()
}

export const api = {
  graph: () => getJSON('/api/graph'),
  config: () => getJSON('/api/config'),
  stats: () => getJSON('/api/stats'),
  node: (id) => getJSON(`/api/node/${id}`),
  nodeSource: (id) => getJSON(`/api/node/${id}/source`),
  search: (q, opts = {}) => {
    const p = new URLSearchParams({ q, ...opts })
    return getJSON(`/api/search?${p.toString()}`)
  },
  index: (opts) => postJSON('/api/index', opts),
  prune: () => postJSON('/api/prune', {}),
  ask: (q, k = 8) => postJSON('/api/ask', { question: q, k }),
  extendedAsk: (opts) => postJSON('/api/extended_ask', opts),
}

// Long-polling only: the server runs Flask-SocketIO under Werkzeug's
// threading mode, which does not handle the websocket transport reliably
// (server-side returns 500 "write() before start_response"). Polling is the
// supported transport for this deployment.
const SOCKET_OPTS = { transports: ['polling'], upgrade: false }

export function connectSocket(onEvent, onHello) {
  const socket = io(BASE || '/', SOCKET_OPTS)
  socket.on('index_event', onEvent)
  if (onHello) socket.on('hello', onHello)
  return socket
}

// Separate listener for extended_ask streaming (the "ext_event" channel).
export function connectExtSocket(onEvent) {
  const socket = io(BASE || '/', SOCKET_OPTS)
  socket.on('ext_event', onEvent)
  return socket
}
