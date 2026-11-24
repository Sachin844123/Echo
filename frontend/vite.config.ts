import { createLogger, defineConfig } from 'vite'
import type { Logger } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export const localProxyPath = '^/(?:api(?:/|$)|session/open$)'

// Vite's default proxy diagnostics include the URL (and therefore filenames).
// Keep a visible transport failure without forwarding private URLs or stacks.
export function safeProxyLogger(logger: Logger = createLogger()): Logger {
  return {
    ...logger,
    error(message, options) {
      if (/\b(?:http|ws) proxy (?:socket )?error:/.test(message)) {
        logger.error(
          'ECHO API proxy connection failed. Check the backend and allowed development origin.',
          {
            timestamp: true,
          },
        )
        return
      }
      logger.error(message, options)
    },
  }
}

export default defineConfig({
  customLogger: safeProxyLogger(),
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { [localProxyPath]: { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
  build: { sourcemap: false },
})
