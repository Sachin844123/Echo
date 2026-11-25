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
async function openWorkspace(page: Page) {
  await page.goto('/')
  const permission = page.getByRole('dialog', { name: 'Allow ECHO to access local files?' })
  const search = page.getByRole('heading', { name: 'Find it again.' })
  await expect(permission.or(search)).toBeVisible()
  if (await permission.isVisible()) {
    await permission.getByRole('button', { name: 'Save permission' }).click()
  }
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
async function waitForText(page: Page, timeout = 15000) {
  await expect
    .poll(
      async () => {
        const response = await page.request.get('/api/v1/indexing-jobs?limit=100', {
          headers: { Authorization: `Bearer ${token()}` },
        })
        const body = await response.json()
        return body.items
          .filter((j: { stage: string; status: string }) => j.stage === 'ingestion')
          .map((j: { status: string; error: { code: string } | null }) => j.error?.code ?? j.status)
          .filter((status: string) => status !== 'succeeded')
      },
      { timeout },
    )
    .toEqual([])
}
test.beforeEach(async ({ request }) => {
  const response = await request.delete('/api/v1/library', {
    headers: { Authorization: `Bearer ${token()}` },
    data: { confirmation: 'DELETE ALL' },
  })
  expect(response.ok()).toBeTruthy()
})

test('onboarding shows all access levels, persists denial, and keeps the workspace usable', async ({
  page,
}) => {
  await page.goto('/')
  const permission = page.getByRole('dialog', { name: 'Allow ECHO to access local files?' })
  await expect(permission).toBeVisible()
  for (const option of [
    'All Accessible Local Files',
    'Personal Folders Only',
    'Selected Folders Only',
    'Deny Access',
  ]) {
    await expect(permission.getByRole('radio', { name: new RegExp(option) })).toBeVisible()
  }
  await expect(permission.getByRole('radio', { name: /Deny Access/ })).toBeChecked()
  await permission.getByRole('radio', { name: /Selected Folders Only/ }).check()
  await permission
    .getByLabel('Approved folders, one absolute path per line')
    .fill('relative-TEST-DATA')
  await permission.getByRole('button', { name: 'Save permission' }).click()
  await expect(permission.getByRole('alert')).toContainText('Use absolute paths')
  await permission.getByRole('radio', { name: /Deny Access/ }).check()
  await permission.getByRole('button', { name: 'Save permission' }).click()
  await expect(page.getByRole('heading', { name: 'Find it again.' })).toBeVisible()
  await expect(page.getByLabel('Session token', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Lock workspace' })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Find it again.' })).toBeVisible()
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual(['echo.theme.v1'])
  expect(await page.evaluate(() => sessionStorage.length)).toBe(0)
  expect(await page.context().cookies()).toEqual([])
  await navigate(page, 'Storage')
  await expect(page.getByRole('heading', { name: 'Storage & Permissions' })).toBeVisible()
  await expect(page.getByText('Deny Access', { exact: true })).toBeVisible()
})

test('an origin rejection explains the setup issue and startup can be retried', async ({
  page,
}) => {
  await page.route('**/session/open', (route) => {
    expect(route.request().method()).toBe('POST')
    return route.fulfill({ status: 403, json: { detail: 'Origin not allowed' } })
  })
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('ECHO_ALLOWED_ORIGINS')
  await page.unroute('**/session/open')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Find it again.' })).toBeVisible()
})

test('origin check prevents file transfer and permits retry after configuration is fixed', async ({
  page,
}) => {
  await openWorkspace(page)
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
  await openWorkspace(page)
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
  await expect(page.locator('.matched-excerpt mark')).toHaveText(['Solar', 'batteries'])
  await page.getByRole('button', { name: 'Close preview' }).click()
  await expect(page.getByRole('button', { name: 'Preview TEST DATA Solar research' })).toBeFocused()
  await page.keyboard.press('Enter')
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
  await openWorkspace(page)
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

test('image OCR, visual search and authenticated image preview work locally', async ({ page }) => {
  test.setTimeout(120000)
  await openWorkspace(page)
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  await page.locator('input[type=file]').setInputFiles('tests/fixtures/TEST-DATA-scan.png')
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Import documents', exact: true })
    .click()
  await expect(page.getByText('Queued for processing', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Done', exact: true }).click()
  await waitForText(page, 45000)
  await page.getByRole('button', { name: 'Keywords', exact: true }).click()
  await page.getByRole('textbox', { name: 'What do you remember?' }).fill('orchid')
  await page.getByLabel('File type', { exact: true }).selectOption('image')
  await page.getByRole('button', { name: 'Search', exact: true }).last().click()
  await page.getByRole('button', { name: 'Preview TEST-DATA-scan' }).click()
  await expect(page.getByRole('img', { name: 'TEST-DATA-scan', exact: true })).toBeVisible()
  await expect(page.locator('.reading-text')).toContainText('ORCHID')
  await page.screenshot({ path: 'test-results/image-ocr-preview.png', fullPage: true })
  await page.getByRole('button', { name: 'Close preview', exact: true }).click()
  await expect
    .poll(
      async () => {
        const response = await page.request.get('/api/v1/indexing-jobs', {
          headers: { Authorization: `Bearer ${token()}` },
        })
        return (await response.json()).items.find(
          (job: { stage: string }) => job.stage === 'visual',
        )?.status
      },
      { timeout: 90000 },
    )
    .toBe('succeeded')
  await page.getByRole('button', { name: 'Images', exact: true }).click()
  await page.getByRole('textbox', { name: 'What do you remember?' }).fill('a page of printed text')
  await page.getByRole('button', { name: 'Search', exact: true }).last().click()
  await expect(page.getByRole('button', { name: 'Preview TEST-DATA-scan' })).toBeVisible()
})

test('spelling correction is visible and can be disabled', async ({ page }) => {
  await openWorkspace(page)
  await addNote(
    page,
    'TEST DATA Guidelines for FP',
    'TEST DATA guidelines for FP submission and evaluation.',
  )
  await waitForText(page)
  await page.getByRole('button', { name: 'Keywords', exact: true }).click()
  await page.getByRole('textbox', { name: 'What do you remember?' }).fill('guideliness of fp')
  await page.getByRole('button', { name: 'Search', exact: true }).last().click()
  await expect(page.getByText(/Searching for: guidelines of fp/)).toBeVisible()
  await page
    .getByRole('checkbox', { name: 'Correct likely spelling mistakes using my library' })
    .uncheck()
  await page.getByRole('button', { name: 'Search', exact: true }).last().click()
  await expect(page.getByText(/Searching for: guidelines of fp/)).not.toBeVisible()
})

test('processing errors, explicit semantic failure, context controls and retry remain visible', async ({
  page,
}) => {
  await openWorkspace(page)
  await addNote(
    page,
    'TEST DATA Index failure',
    'TEST DATA Missing model does not hide keyword text.',
  )
  await waitForText(page)
  await page.getByRole('button', { name: 'View activity' }).click()
  await expect(page.getByRole('heading', { name: 'Activity', exact: true })).toBeVisible()
  await expect(page.locator('.job-details time').first()).toBeVisible()
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
  await openWorkspace(page)
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
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) }))
  await openWorkspace(page)
  await page.keyboard.press('Control+k')
  await expect(page.getByRole('textbox', { name: 'What do you remember?' })).toBeFocused()
  const filters = page.getByRole('button', { name: 'Filters', exact: true })
  await filters.click()
  await expect(filters).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByLabel('File type')).not.toBeVisible()
  await filters.click()
  await expect(page.getByLabel('File type')).toBeVisible()
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
  const toggle = page.getByRole('button', { name: 'Toggle navigation' })
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('navigation').getByRole('button', { name: 'Search' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(toggle).toBeFocused()
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await page.keyboard.press('Enter')
  await navigate(page, 'Library')
  await expect(page.getByRole('heading', { name: 'Your library' })).toBeVisible()
  expect(await violations()).toEqual([])
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 667, height: 375 })
  const openImport = page.getByRole('button', { name: 'Import', exact: true })
  await expect(openImport).toHaveCSS('transition-duration', '0s')
  await openImport.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveCSS('animation-name', 'none')
  expect((await dialog.boundingBox())!.height).toBeLessThan(375)
  expect(await violations()).toEqual([])
})

test('a stored theme is applied before React starts', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('echo.theme.v1', 'dark'))
  await page.route('**/assets/index-*.js', (route) => route.abort())
  await page.goto('/')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await page.locator('html').evaluate((root) => getComputedStyle(root).colorScheme)).toBe(
    'dark',
  )
  await expect(page.locator('#root')).toBeEmpty()
})

test('recent searches require opt-in and can be reused, removed, and cleared', async ({ page }) => {
  const key = 'echo.recent-searches.v1'
  await openWorkspace(page)
  const input = page.getByRole('textbox', { name: 'What do you remember?' })
  const recent = page.getByRole('region', { name: 'Recent searches' })
  const search = page.getByRole('main').getByRole('button', { name: 'Search', exact: true })
  await page.getByRole('button', { name: 'Keywords', exact: true }).click()
  await input.fill('TEST DATA private query')
  await search.click()
  await expect(page.getByRole('heading', { name: 'No matching documents' })).toBeVisible()
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBeNull()
  await page.getByRole('button', { name: 'Recent', exact: true }).click()
  await recent.getByRole('button', { name: 'Enable recent searches' }).click()
  await expect(recent).toContainText('Run a search to add it here.')
  await input.fill('TEST DATA cedar notebook')
  await search.click()
  await expect(page.getByRole('heading', { name: 'No matching documents' })).toBeVisible()
  await search.click()
  await expect(page.getByRole('heading', { name: 'No matching documents' })).toBeVisible()
  await page.reload()
  const saved = recent.getByRole('button', { name: /^TEST DATA cedar notebook/ })
  await expect(saved).toHaveCount(1)
  await saved.click()
  await expect(input).toBeFocused()
  await expect(input).toHaveValue('TEST DATA cedar notebook')
  await expect(page.getByRole('button', { name: 'Keywords', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await recent.getByRole('button', { name: 'Remove search: TEST DATA cedar notebook' }).click()
  await expect(saved).toHaveCount(0)
  await expect(recent.getByRole('heading')).toBeFocused()
  await search.click()
  await expect(page.getByRole('heading', { name: 'No matching documents' })).toBeVisible()
  await navigate(page, 'Settings')
  await page.getByRole('button', { name: 'Clear history', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: 'Remember recent searches' })).toBeChecked()
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBe('[]')
  await navigate(page, 'Search')
  await page.getByRole('button', { name: 'Keywords', exact: true }).click()
  await input.fill('TEST DATA maple notebook')
  await search.click()
  await expect(page.getByRole('heading', { name: 'No matching documents' })).toBeVisible()
  await navigate(page, 'Settings')
  await page.getByRole('checkbox', { name: 'Remember recent searches' }).uncheck()
  expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBeNull()
  await navigate(page, 'Search')
  await expect(recent.getByRole('button', { name: 'Enable recent searches' })).toBeVisible()
})

test('queries are not persisted and stale search responses cannot overwrite newer input', async ({
  page,
}) => {
  await openWorkspace(page)
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
  await expect(page.getByRole('region', { name: 'Recent searches' })).toBeVisible()
  expect(page.url()).not.toContain('PRIVATE')
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain(
    'PRIVATE',
  )
})

test('connection failure is recoverable and an expired session renews automatically', async ({
  page,
}) => {
  await openWorkspace(page)
  await page.route('**/api/v1/sources?**', (route) => route.abort('connectionrefused'))
  await navigate(page, 'Library')
  await expect(page.getByRole('alert')).toContainText('Cannot reach ECHO')
  await page.unroute('**/api/v1/sources?**')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Make room for what matters.' })).toBeVisible()
  let requests = 0
  await page.route('**/api/v1/sources?**', (route) => {
    requests++
    return requests === 1
      ? route.fulfill({ status: 401, json: { detail: 'Valid session token required' } })
      : route.continue()
  })
  const renewed = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/session/open' && response.ok(),
  )
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await renewed
  await expect(page.getByRole('heading', { name: 'Make room for what matters.' })).toBeVisible()
  expect(requests).toBe(2)
})
