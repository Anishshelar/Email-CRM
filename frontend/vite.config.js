import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api':          'http://localhost:8000',
      '/analytics':    'http://localhost:8000',
      '/rag':          'http://localhost:8000',
      '/agent':        'http://localhost:8000',
      '/dashboard':    'http://localhost:8000',
      '/threads':      'http://localhost:8000',
      '/respond':      'http://localhost:8000',
      '/drafts':       'http://localhost:8000',
      '/intelligence': 'http://localhost:8000',
      '/audit':        'http://localhost:8000',
      '/contacts':     'http://localhost:8000',
      '/health':       'http://localhost:8000',
    },
  },
})
