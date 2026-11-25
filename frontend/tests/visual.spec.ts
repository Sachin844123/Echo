/** Opt-in screenshots of the real workspace with tiny, labelled TEST DATA. */
import path from 'node:path'
import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const target = process.env.ECHO_VISUAL_CAPTURE_DIR
const verify = process.env.ECHO_VISUAL_VERIFY === '1'

test('capture the workspace in both themes and viewport sizes', async ({ page }) => {
  test.skip(!target, 'Set ECHO_VISUAL_CAPTURE_DIR to capture screenshots')
  test.setTimeout(600000)
  const save = (name: string) =>
    page.screenshot({
      path: path.join(target!, `${name}.png`),
      fullPage: true,
      animations: 'disabled',
    })
  await page.goto('/')
  const consent = page.getByRole('dialog', { name: 'Allow ECHO to access local files?' })
  await expect(consent).toBeVisible()
  await save('light-desktop-onboarding')
  await consent.getByRole('button', { name: 'Save permission' }).click()
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  await save('light-desktop-import')
  await page.getByRole('button', { name: 'Write a note' }).click()
  await page.getByLabel('Note title').fill('TEST DATA Solar research')
  await page
    .getByLabel('Note text')
    .fill(
      'TEST DATA. Solar batteries store rooftop electricity. Heat and discharge cycles affect their lifetime. The trial compared battery output during cloudy spring mornings.',
    )
  await page.getByRole('button', { name: 'Save note' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const auth = { headers: { Authorization: `Bearer ${process.env.ECHO_E2E_TOKEN!}` } }
  await expect
    .poll(async () => {
      const response = await page.request.get('/api/v1/indexing-jobs?limit=100', auth)
      const body = await response.json()
      return body.items.some(
        (job: { stage: string; status: string }) =>
          job.stage === 'ingestion' && job.status === 'succeeded',
      )
    })
    .toBe(true)
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  const navigate = async (view: string) => {
    if (!(await nav.isVisible())) {
      await page.getByRole('button', { name: 'Toggle navigation' }).click()
    }
    await nav.getByRole('button', { name: new RegExp(`^${view}(?: \\d+)?$`) }).click()
  }
  await navigate('Collections')
  await page.getByRole('button', { name: 'New collection' }).click()
  await page.getByLabel('Collection name').fill('TEST DATA Field notes')
  await page.getByRole('button', { name: 'Create collection' }).click()
  await expect(page.getByText('TEST DATA Field notes', { exact: true })).toBeVisible()
  for (const theme of ['light', 'dark']) {
    if (theme === 'dark') {
      await page.getByRole('banner').getByRole('button', { name: 'Use dark theme' }).click()
    }
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    for (const [size, width, height] of [
      ['desktop', 1440, 1000],
      ['narrow', 375, 812],
    ] as const) {
      await page.setViewportSize({ width, height })
      for (const [view, ready] of [
        ['Search', 'Find it again.'],
        ['Library', 'TEST DATA Solar research'],
        ['Collections', 'TEST DATA Field notes'],
        ['Sources', 'TEST DATA Solar research'],
        ['Storage', 'Deny Access'],
        ['Settings', 'Local search'],
      ]) {
        await navigate(view)
        await expect(page.getByText(ready, { exact: true }).first()).toBeVisible()
        await page.evaluate(() => window.scrollTo(0, 0))
        await save(`${theme}-${size}-${view.toLowerCase()}`)
        if (verify) {
          const label = `${theme} ${size} ${view}`
          expect
            .soft(
              await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
              `No horizontal overflow in ${label}`,
            )
            .toBe(true)
          const report = await new AxeBuilder({ page })
            .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
            .analyze()
          expect
            .soft(
              report.violations.map((issue) => ({
                rule: issue.id,
                elements: issue.nodes.map((node) => node.target),
              })),
              `Accessibility checks for ${label}`,
            )
            .toEqual([])
        }
        if (view === 'Search') {
          await page.getByRole('button', { name: 'Keywords', exact: true }).click()
          await page.getByRole('textbox', { name: 'What do you remember?' }).fill('solar batteries')
          await page.getByRole('main').getByRole('button', { name: 'Search', exact: true }).click()
          await page.getByRole('button', { name: 'Preview TEST DATA Solar research' }).click()
          await expect(page.getByRole('heading', { name: 'Matched passage' })).toBeVisible()
          await page.evaluate(() => window.scrollTo(0, 0))
          await save(`${theme}-${size}-preview`)
        }
      }
    }
  }
})
