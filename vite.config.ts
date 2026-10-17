import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: parseInt(process.env.PORT || '5173'),
    proxy: { '/api': process.env.AMBER_API || 'http://127.0.0.1:8000' },
  },
})
