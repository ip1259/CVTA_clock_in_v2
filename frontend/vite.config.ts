import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd());

  return {
    plugins: [vue()],
    css: {
      preprocessorOptions: {
        scss: {
          // Point to variables.scss and fix the typo (@/ instead of @./)
          additionalData: `@use "@/styles/variables.scss" as *;`,
        },
      },
    },
    server: {
      proxy: {
        '/api': {
          target: env.VITE_CVTA_API_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
        }
      }
    },
    resolve: {
      alias: {
        '@': '/src',
      },
    },
    build: {
      outDir: '../dist',
      emptyOutDir: true
    }
  }
})
