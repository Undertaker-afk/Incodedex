import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build into ./dist (served by the Flask backend). During `vite dev`, API and
// websocket calls are proxied to the backend on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/socket.io': { target: 'http://localhost:8000', ws: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
