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
  search: (q, opts = {}) => {
    const p = new URLSearchParams({ q, ...opts })
    return getJSON(`/api/search?${p.toString()}`)
  },
  index: (opts) => postJSON('/api/index', opts),
  prune: () => postJSON('/api/prune', {}),
}

export function connectSocket(onEvent, onHello) {
  const socket = io(BASE || '/', { transports: ['websocket', 'polling'] })
  socket.on('index_event', onEvent)
  if (onHello) socket.on('hello', onHello)
  return socket
}
