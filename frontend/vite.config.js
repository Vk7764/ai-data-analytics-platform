import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replace(/\\/g, "/");

          if (!normalized.includes("node_modules")) {
            return;
          }

          if (
            normalized.includes("/react/") ||
            normalized.includes("/react-dom/") ||
            normalized.includes("/scheduler/")
          ) {
            return "vendor-react";
          }

          if (
            normalized.includes("/recharts/") ||
            normalized.includes("/d3-") ||
            normalized.includes("/victory-vendor/") ||
            normalized.includes("/react-smooth/")
          ) {
            return "vendor-charts";
          }

          return "vendor";
        },
      },
    },
  },
  server: {
    allowedHosts: true,
  },
})