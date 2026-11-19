/** Tiny, labelled TEST DATA against the actual backend; no production fixtures. */
import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const unexpected = new WeakMap<Page, string[]>()
test.beforeEach(async ({ page }) => {
  const events: string[] = []
  unexpected.set(page, events)
  page.on('pageerror', () => events.push('Unhandled browser error'))
  page.on('request', (request) => {
    if (new URL(request.url()).origin !== 'http://127.0.0.1:8237')
      events.push('Unexpected external browser request')
  })
})
test.afterEach(async ({ page }) => {
  expect(unexpected.get(page)).toEqual([])
})

const token = () => process.env.ECHO_E2E_TOKEN!
async function connect(page: Page) {
  await page.goto('/')
  await page.getByLabel('Session token', { exact: true }).fill(token())
  await page.getByRole('button', { name: 'Open workspace', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Find it again.' })).toBeVisible()
}
async function navigate(page: Page, name: string) {
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name: new RegExp(`^${name}(?: \\d+)?$`) })
    .click()
}
async function addNote(page: Page, title: string, text: string) {
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  await page.getByRole('button', { name: 'Write a note' }).click()
  await page.getByLabel('Note title').fill(title)
  await page.getByLabel('Note text').fill(text)
  await page.getByRole('button', { name: 'Save note', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
}
async function waitForText(page: Page) {
  await expect
    .poll(async () => {
      const response = await page.request.get('/api/v1/indexing-jobs?limit=100', {
        headers: { Authorization: `Bearer ${token()}` },
      })
      const body = await response.json()
      return body.items
        .filter((j: { stage: string; status: string }) => j.stage === 'ingestion')
        .every((j: { status: string }) => j.status === 'succeeded')
    })
    .toBe(true)
}
test.beforeEach(async ({ request }) => {
  const response = await request.delete('/api/v1/library', {
    headers: { Authorization: `Bearer ${token()}` },
    data: { confirmation: 'DELETE ALL' },
  })
  expect(response.ok()).toBeTruthy()
})

test('session token is memory-only, errors are visible, lock and reload clear the session', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('Session token', { exact: true }).fill('invalid'.repeat(8))
  await page.getByRole('button', { name: 'Open workspace' }).click()
  await expect(page.getByRole('alert')).toContainText('Session token')
  await page.getByLabel('Session token', { exact: true }).fill(token())
  await page.getByRole('button', { name: 'Open workspace' }).click()
  await expect(page.getByRole('heading', { name: 'Find it again.' })).toBeVisible()
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain(
    token(),
  )
  expect(await page.evaluate(() => sessionStorage.length)).toBe(0)
  await page.getByRole('button', { name: 'Lock workspace', exact: true }).click()
  await expect(page.getByLabel('Session token', { exact: true })).toHaveValue('')
  await connect(page)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Open your workspace' })).toBeVisible()
})

test('rejected browser origin prevents login with actionable guidance', async ({ page }) => {
  await page.route('**/api/v1/session/check', (route) => {
    expect(route.request().method()).toBe('POST')
    return route.fulfill({ status: 403, json: { detail: 'Origin not allowed' } })
  })
  await page.goto('/')
  await page.getByLabel('Session token', { exact: true }).fill(token())
  await page.getByRole('button', { name: 'Open workspace', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('ECHO_ALLOWED_ORIGINS')
  await expect(page.getByRole('heading', { name: 'Open your workspace' })).toBeVisible()
})

test('origin check prevents file transfer and permits retry after configuration is fixed', async ({
  page,
}) => {
  await connect(page)
  let uploads = 0
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/imports/files')) uploads++
  })
  await page.route('**/api/v1/session/check', (route) =>
    route.fulfill({ status: 403, json: { detail: 'Origin not allowed' } }),
  )
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  await page.locator('input[type=file]').setInputFiles({
    name: 'TEST-DATA-origin.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('TEST DATA origin validation before document transfer.'),
  })
  const submit = page
    .getByRole('dialog')
    .getByRole('button', { name: 'Import documents', exact: true })
  await submit.click()
  await expect(page.getByRole('alert')).toContainText('ECHO_ALLOWED_ORIGINS')
  expect(uploads).toBe(0)
  await page.unroute('**/api/v1/session/check')
  await submit.click()
  await expect(page.getByText('Queued for processing', { exact: true })).toBeVisible()
  expect(uploads).toBe(1)
})

test('import, duplicate detection, keyword search, matched preview, rename and single deletion', async ({
  page,
}) => {
  await connect(page)
  await addNote(
    page,
    'TEST DATA Solar research',
    'TEST DATA: Solar batteries store rooftop electricity. Unicode sample: 🌞 café. <script>window.evil=1</script>',
  )
  await waitForText(page)
  await addNote(
    page,
    'TEST DATA duplicate',
    'TEST DATA: Solar batteries store rooftop electricity. Unicode sample: 🌞 café. <script>window.evil=1</script>',
  )
  await expect(
    page.getByRole('status').filter({ hasText: 'already in your library' }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Keywords', exact: true }).click()
  await page.getByRole('textbox', { name: 'What do you remember?' }).fill('solar batteries')
  await page.getByRole('button', { name: 'Search', exact: true }).last().click()
  await expect(page.getByRole('button', { name: 'Preview TEST DATA Solar research' })).toBeVisible()
  await page.getByRole('button', { name: 'Preview TEST DATA Solar research' }).click()
  await expect(page.getByRole('heading', { name: 'Matched passage' })).toBeVisible()
  await expect(page.locator('.reading-text')).toContainText('<script>window.evil=1</script>')
  expect(await page.evaluate(() => 'evil' in window)).toBe(false)
  await page.screenshot({ path: 'test-results/document-preview.png', fullPage: true })
  await page.getByRole('button', { name: 'Rename', exact: true }).click()
  await page.getByLabel('Document title').fill('TEST DATA Solar archive')
  await page.getByRole('button', { name: 'Save title' }).click()
  await navigate(page, 'Library')
  await page.getByRole('button', { name: 'Preview TEST DATA Solar archive' }).click()
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.getByRole('button', { name: 'Delete document', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Make room for what matters.' })).toBeVisible()
})

test('file upload, collection membership and filters use real data', async ({ page }) => {
  await connect(page)
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  await page.locator('input[type=file]').setInputFiles({
    name: 'TEST-DATA-tides.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('TEST DATA Ocean tides change coastal water levels.'),
  })
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Import documents', exact: true })
    .click()
  await expect(page.getByText('Queued for processing', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Done', exact: true }).click()
  await waitForText(page)
  await navigate(page, 'Collections')
  await page.getByRole('button', { name: 'New collection', exact: true }).click()
  await page.getByLabel('Collection name').fill('TEST DATA Coast')
  await page.getByRole('button', { name: 'Create collection', exact: true }).last().click()
  await navigate(page, 'Library')
  await page.getByRole('button', { name: 'Preview TEST-DATA-tides' }).click()
  await page.getByRole('checkbox', { name: 'TEST DATA Coast', exact: true }).check()
  await expect(page.getByRole('checkbox', { name: 'TEST DATA Coast', exact: true })).toBeChecked()
  await navigate(page, 'Collections')
  await page.getByRole('button', { name: 'Open TEST DATA Coast' }).click()
  await expect(page.getByRole('button', { name: 'Preview TEST-DATA-tides' })).toBeVisible()
  await navigate(page, 'Search')
  await page.getByRole('button', { name: 'Keywords', exact: true }).click()
  await page.getByRole('textbox', { name: 'What do you remember?' }).fill('ocean')
  await page.getByLabel('Collection', { exact: true }).selectOption({ label: 'TEST DATA Coast' })
  await page.getByLabel('File type', { exact: true }).selectOption('pdf')
  await page.getByRole('button', { name: 'Search', exact: true }).last().click()
  await expect(page.getByRole('heading', { name: 'No matching documents' })).toBeVisible()
  await page.getByLabel('File type', { exact: true }).selectOption('txt')
  await page.getByRole('button', { name: 'Search', exact: true }).last().click()
  await expect(page.getByRole('button', { name: 'Preview TEST-DATA-tides' })).toBeVisible()
})

test('processing errors, explicit semantic failure, context controls and retry remain visible', async ({
  page,
}) => {
  await connect(page)
  await addNote(
    page,
    'TEST DATA Index failure',
    'TEST DATA Missing model does not hide keyword text.',
  )
  await waitForText(page)
  await navigate(page, 'Sources')
  await expect(page.getByRole('button', { name: 'Retry job', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Retry job', exact: true }).click()
  await expect(page.getByText('Processing retry queued.', { exact: true })).toBeVisible()
  await navigate(page, 'Search')
  await page.getByRole('button', { name: 'Hybrid + context', exact: true }).click()
  await expect(page.getByLabel('Remembered type')).toBeVisible()
  await page.getByLabel('Remembered type').selectOption('note')
  await page.getByRole('textbox', { name: 'What do you remember?' }).fill('model')
  await page.getByRole('button', { name: 'Search', exact: true }).last().click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Hybrid + context' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
})

test('delete-all requires typed confirmation and removes documents and collections', async ({
  page,
}) => {
  await connect(page)
  await addNote(page, 'TEST DATA delete all', 'TEST DATA Disposable browser-test note.')
  await navigate(page, 'Settings')
  await page.getByRole('button', { name: 'Delete all content', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Permanently delete library' })).toBeDisabled()
  await page.getByLabel('Type DELETE ALL to confirm').fill('DELETE ALL')
  await page.getByRole('button', { name: 'Permanently delete library' }).click()
  await expect(
    page.getByText('Library deleted. Your original files were kept.', { exact: true }),
  ).toBeVisible()
  await navigate(page, 'Library')
  await expect(page.getByRole('heading', { name: 'Make room for what matters.' })).toBeVisible()
})

test('keyboard navigation, modal focus, themes, responsive layout and accessibility', async ({
  page,
}) => {
  const violations = async () =>
    (
      await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
    ).violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) }))
  await page.goto('/')
  await page.screenshot({ path: 'test-results/connect-light.png', fullPage: true })
  expect(await violations()).toEqual([])
  await connect(page)
  await page.keyboard.press('Control+k')
  await expect(page.getByRole('textbox', { name: 'What do you remember?' })).toBeFocused()
  expect(await violations()).toEqual([])
  await page.screenshot({ path: 'test-results/dashboard-light.png', fullPage: true })
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  for (let i = 0; i < 9; i++) await page.keyboard.press('Tab')
  expect(await page.evaluate(() => !!document.activeElement?.closest('dialog'))).toBe(true)
  expect(await violations()).toEqual([])
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Import', exact: true })).toBeFocused()
  await page.getByRole('button', { name: 'Use dark theme', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await violations()).toEqual([])
  await page.screenshot({ path: 'test-results/dashboard-dark.png', fullPage: true })
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Toggle navigation' }).click()
  await navigate(page, 'Library')
  await expect(page.getByRole('heading', { name: 'Your library' })).toBeVisible()
  expect(await violations()).toEqual([])
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true })
})

test('queries are not persisted and stale search responses cannot overwrite newer input', async ({
  page,
}) => {
  await connect(page)
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/search', async (route) => {
    await gate
    await route.continue().catch(() => {})
  })
  await page.getByRole('button', { name: 'Keywords', exact: true }).click()
  const query = page.getByRole('textbox', { name: 'What do you remember?' })
  await query.fill('PRIVATE TEST DATA QUERY')
  await page.getByRole('button', { name: 'Search', exact: true }).last().click()
  await expect(page.getByRole('status').filter({ hasText: 'Searching your library' })).toBeVisible()
  await query.fill('new query')
  release()
  await expect(
    page.getByRole('heading', { name: 'Your memory is the starting point.' }),
  ).toBeVisible()
  expect(page.url()).not.toContain('PRIVATE')
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain(
    'PRIVATE',
  )
})

test('connection failure is recoverable and unauthorized responses lock the workspace', async ({
  page,
}) => {
  await connect(page)
  await page.route('**/api/v1/sources?**', (route) => route.abort('connectionrefused'))
  await navigate(page, 'Library')
  await expect(page.getByRole('alert')).toContainText('Cannot reach ECHO')
  await page.unroute('**/api/v1/sources?**')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Make room for what matters.' })).toBeVisible()
  await page.route('**/api/v1/sources?**', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: '{"detail":"Valid session token required"}',
    }),
  )
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Open your workspace' })).toBeVisible()
  await expect(page.getByLabel('Session token', { exact: true })).toHaveValue('')
})
