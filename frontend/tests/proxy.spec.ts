/** Real Vite transport and ephemeral backend; all payloads are labelled TEST DATA. */
import { createServer as createHttpServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { test, expect } from '@playwright/test'
import { createLogger, createServer } from 'vite'
import { safeProxyLogger } from '../vite.config'

async function proxy(target: string, messages: unknown[] = []) {
  const logger = createLogger('silent')
  logger.error = (message, options) => {
    messages.push({ message, options })
  }
  const server = await createServer({
    configFile: false,
    customLogger: safeProxyLogger(logger),
    optimizeDeps: { noDiscovery: true, include: [] },
    server: {
      host: '127.0.0.1',
      port: 0,
      hmr: false,
      proxy: { '/api': { target, changeOrigin: true } },
    },
  })
  await server.listen()
  const address = server.httpServer!.address() as AddressInfo
  return { server, url: `http://127.0.0.1:${address.port}` }
}

test('Vite preserves token and exact Origin checks, and forwards an allowed upload', async ({
  request,
}) => {
  const { server, url } = await proxy('http://127.0.0.1:8237')
  const authorization = { Authorization: `Bearer ${process.env.ECHO_E2E_TOKEN!}` }
  try {
    expect((await request.post(`${url}/api/v1/session/check`)).status()).toBe(401)
    const denied = await request.post(`${url}/api/v1/session/check`, {
      headers: { ...authorization, Origin: 'http://127.0.0.1:5173' },
    })
    expect(denied.status()).toBe(403)
    expect(await denied.json()).toEqual({ detail: 'Origin not allowed' })
    const headers = { ...authorization, Origin: 'http://127.0.0.1:8238' }
    const allowed = await request.post(`${url}/api/v1/session/check`, { headers })
    expect(allowed.status()).toBe(200)
    const upload = await request.post(`${url}/api/v1/imports/files?filename=TEST-DATA-proxy.txt`, {
      headers: { ...headers, 'Content-Type': 'application/octet-stream' },
      data: Buffer.from('TEST DATA real development proxy upload.'),
    })
    expect(upload.status()).toBe(202)
    expect((await upload.json()).source_id).toBeGreaterThan(0)
  } finally {
    await server.close()
  }
})

test('upstream connection reset stays visible without logging filenames or raw errors', async ({
  request,
}) => {
  const upstream = createHttpServer((incoming) => incoming.socket.destroy())
  await new Promise<void>((resolve) => upstream.listen(0, '127.0.0.1', resolve))
  const address = upstream.address() as AddressInfo
  const messages: unknown[] = []
  const { server, url } = await proxy(`http://127.0.0.1:${address.port}`, messages)
  try {
    const response = await request.post(
      `${url}/api/v1/imports/files?filename=PRIVATE-TEST-DATA.pdf`,
      {
        data: Buffer.from('TEST DATA reset only; no valid document is imported.'),
      },
    )
    expect(response.status()).toBe(502)
    expect(messages).toEqual([
      {
        message:
          'ECHO API proxy connection failed. Check the backend and allowed development origin.',
        options: { timestamp: true },
      },
    ])
  } finally {
    await server.close()
    await new Promise<void>((resolve, reject) =>
      upstream.close((error) => (error ? reject(error) : resolve())),
    )
  }
})
