/**
 * Vite 构建配置。
 *
 * 开发环境不硬编码后端地址：`/api` 与 `/static` 统一通过 proxy 转发到本地 FastAPI 服务，
 * 这样前端代码里的请求路径与生产部署保持一致（生产由 Nginx 承担同样的转发职责）。
 */
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

/** 本地后端服务地址（FastAPI 默认监听 8000） */
const BACKEND_ORIGIN = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 接口请求
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
      // 失败截图与 Allure 报告等静态资源
      '/static': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // 拆包：把体积最大的 ECharts / Element Plus 单独拆出，避免首屏 chunk 过大
        manualChunks: {
          echarts: ['echarts'],
          'element-plus': ['element-plus', '@element-plus/icons-vue'],
          vue: ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
})
