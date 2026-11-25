import { randomBytes } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { defineConfig } from '@playwright/test'

const root = fileURLToPath(new URL('..', import.meta.url))
process.env.ECHO_E2E_TOKEN ??= randomBytes(32).toString('base64url')
const python = path.join(
  root,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)
export default defineConfig({
  testDir: './tests',
  testMatch: '*.spec.ts',
  workers: 1,
  fullyParallel: false,
  timeout: 60000,
  expect: { timeout: 15000 },
  use: {
    baseURL: 'http://127.0.0.1:8237',
    browserName: 'chromium',
    channel: process.env.ECHO_TEST_BROWSER ?? 'msedge',
    viewport: { width: 1440, height: 1000 },
    colorScheme: 'light',
    trace: 'off',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: `"${python}" tests/serve_backend.py`,
    url: 'http://127.0.0.1:8237/',
    // First imports of the native indexing dependencies can be slow on Windows.
    timeout: 240000,
    reuseExistingServer: false,
  },
})
