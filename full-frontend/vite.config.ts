import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from "path"

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      // Fallback when VITE_API_BASE_URL is unset — forwards /api/* to the FastAPI backend
      "/api": {
        target: "http://localhost:8052",
        changeOrigin: true,
      },
    },
  },
})
