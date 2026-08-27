import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('element-plus')) return 'vendor-element-plus'
          if (id.includes('@element-plus') || id.includes('lucide-vue-next')) return 'vendor-icons'
          if (id.includes('@amap')) return 'vendor-amap'
          if (id.includes('vue-router') || id.includes('pinia') || id.includes('/vue/')) return 'vendor-vue'
          if (id.includes('axios')) return 'vendor-axios'
        },
      },
    },
  },
  server: {
    allowedHosts: [
      '8ddbb5a.r30.cpolar.top',
    ],
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
      '/_AMapService': process.env.VITE_AMAP_PROXY_TARGET || 'http://127.0.0.1:8080',
    },
  },
  test: { environment: 'jsdom' },
})
