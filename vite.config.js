import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// During development the backend runs on port 8000 (see backend/README.md);
// requests to /api are forwarded there, so no CORS setup is needed locally.
const backend = { '/api': 'http://127.0.0.1:8000' }

export default defineConfig({
  plugins: [react()],
  server: { proxy: backend },
  preview: { proxy: backend },
})
