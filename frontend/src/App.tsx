import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Api, errorText, useGet } from './api'
import { Brand, ErrorBox, Icon, Loading } from './components'
import { SearchPage } from './SearchPage'
import { LibraryPage, CollectionsPage } from './LibraryPage'
import { ActivityPage, SettingsPage } from './SystemPages'
import { ImportDialog } from './ImportDialog'
import { StorageConsent, StoragePage } from './StoragePage'
import { useSearchHistory } from './searchHistory'
import type { StorageStatus } from './StoragePage'
import type { AppSettings, IndexStatus, View } from './types'

const nav: { view: View; icon: string }[] = [
  { view: 'Search', icon: 'search' },
  { view: 'Library', icon: 'library' },
  { view: 'Collections', icon: 'folder' },
  { view: 'Activity', icon: 'activity' },
  { view: 'Storage', icon: 'storage' },
  { view: 'Settings', icon: 'settings' },
]
function initialTheme(): 'light' | 'dark' {
  const value = document.documentElement.dataset.theme
  if (value === 'light' || value === 'dark') return value
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}
export function App() {
  const [theme, setTheme] = useState(initialTheme)
  const [api, setApi] = useState<Api | null>(null)
  const [storage, setStorage] = useState<StorageStatus>()
  const [startupError, setStartupError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const client = new Api()
    let active = true
    void client
      .start()
      .then(() => client.request<StorageStatus>('/api/v1/storage'))
      .then(
        (value) => {
          if (active) {
            setStorage(value)
            setApi(client)
          }
        },
        (error) => {
          if (active) setStartupError(errorText(error))
        },
      )
    return () => {
      active = false
      client.dispose()
    }
  }, [attempt])
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('echo.theme.v1', theme)
    } catch {
      /* No persistence required. */
    }
  }, [theme])
  const toggleTheme = () => setTheme((t) => (t === 'light' ? 'dark' : 'light'))
  return api && storage ? (
    <Workspace api={api} theme={theme} toggleTheme={toggleTheme} storage={storage} />
  ) : (
    <main className="workspace-startup">
      <Brand />
      {startupError ? (
        <ErrorBox
          message={startupError}
          retry={() => {
            setStartupError('')
            setAttempt((current) => current + 1)
          }}
        />
      ) : (
        <Loading label="Opening your workspace" />
      )}
    </main>
  )
}
function Workspace({
  api,
  theme,
  toggleTheme,
  storage,
}: {
  api: Api
  theme: string
  toggleTheme: () => void
  storage: StorageStatus
}) {
  const [view, setView] = useState<View>('Search')
  const [revision, setRevision] = useState(0)
  const [importing, setImporting] = useState(false)
  const [menu, setMenu] = useState(false)
  const [status, setStatus] = useState<IndexStatus>()
  const [statusError, setStatusError] = useState('')
  const [notice, setNotice] = useState('')
  const [storageStatus, setStorageStatus] = useState(storage)
  const [onboarding, setOnboarding] = useState(storage.mode === null)
  const heading = useRef<HTMLHeadingElement>(null)
  const navigation = useRef<HTMLElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const history = useSearchHistory()
  const settings = useGet<AppSettings>(api, '/api/v1/settings', revision)
  const refresh = useCallback(() => setRevision((r) => r + 1), [])
  const changed = useCallback(
    (message?: string) => {
      refresh()
      if (message) setNotice(message)
    },
    [refresh],
  )
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      if (!document.hidden) {
        try {
          const value = await api.request<IndexStatus>('/api/v1/index/status', {
            signal: controller.signal,
          })
          if (!controller.signal.aborted) {
            setStatus(value)
            setStatusError('')
          }
        } catch (e) {
          if (!controller.signal.aborted) setStatusError(errorText(e))
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 5000)
    }
    void poll()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [api, revision])
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        (e.ctrlKey || e.metaKey) &&
        e.key.toLowerCase() === 'k' &&
        !document.querySelector('dialog[open]')
      ) {
        e.preventDefault()
        setView('Search')
        setMenu(false)
        requestAnimationFrame(() => document.getElementById('memory-query')?.focus())
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])
  useLayoutEffect(() => {
    if (menu) navigation.current?.querySelector<HTMLButtonElement>('[aria-current]')?.focus()
  }, [menu])
  function navigate(next: View) {
    setView(next)
    setMenu(false)
    setNotice('')
    requestAnimationFrame(() => heading.current?.focus())
  }
  const counts = status?.sources_by_status ?? {}
  const count = Object.values(counts).reduce((sum, n) => sum + n, 0)
  const pending = (counts.pending ?? 0) + (counts.processing ?? 0)
  return (
    <div className="workspace">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <aside
        className={`sidebar ${menu ? 'is-open' : ''}`}
        onKeyDown={(event) => {
          if (menu && event.key === 'Escape') {
            setMenu(false)
            menuButton.current?.focus()
          }
        }}
        onBlur={(event) => {
          if (
            menu &&
            event.relatedTarget &&
            event.relatedTarget !== menuButton.current &&
            !event.currentTarget.contains(event.relatedTarget)
          )
            setMenu(false)
        }}
      >
        <Brand />
        <div className="workspace-label">Personal workspace</div>
        <nav id="workspace-navigation" ref={navigation} aria-label="Main navigation">
          {nav.map((item) => (
            <button
              key={item.view}
              className={`nav-link ${view === item.view ? 'active' : ''}`}
              aria-current={view === item.view ? 'page' : undefined}
              onClick={() => navigate(item.view)}
            >
              <Icon name={item.icon} />
              <span>{item.view}</span>
              {item.view === 'Library' && status ? (
                <span className="nav-count">{count}</span>
              ) : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-status">
            <span className={`status-dot ${statusError ? 'warning' : ''}`} />
            <div>
              {statusError ? 'Connection interrupted' : 'Local workspace'}
              <small>
                {pending
                  ? `${pending} document${pending === 1 ? '' : 's'} processing`
                  : 'Stored on this device'}
              </small>
            </div>
          </div>
        </div>
      </aside>
      <div className="workspace-content">
        <header className="topbar">
          <div className="flex items-center gap-3">
            <button
              className="icon-button mobile-menu"
              ref={menuButton}
              aria-label="Toggle navigation"
              aria-expanded={menu}
              aria-controls="workspace-navigation"
              onClick={() => setMenu((m) => !m)}
            >
              <Icon name="menu" />
            </button>
            <span className="breadcrumb">
              <span className="breadcrumb-root">Workspace</span>
              <span className="breadcrumb-root" aria-hidden="true">
                /
              </span>
              <strong>{view}</strong>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="privacy-label">
              <Icon name="lock" size={14} />
              Local only
            </span>
            <button
              className="icon-button"
              aria-label={`Use ${theme === 'light' ? 'dark' : 'light'} theme`}
              onClick={toggleTheme}
            >
              <Icon name={theme === 'light' ? 'moon' : 'sun'} />
            </button>
            <button className="button primary" onClick={() => setImporting(true)}>
              <Icon name="plus" size={18} />
              <span>Import</span>
            </button>
          </div>
        </header>
        <main id="main-content" className="main-content" tabIndex={-1}>
          {view !== 'Search' ? (
            <header className="page-heading">
              <div>
                <h1 ref={heading} tabIndex={-1}>
                  {view === 'Library'
                    ? 'Your library'
                    : view === 'Storage'
                      ? 'Storage & Permissions'
                      : view}
                </h1>
                <p>
                  {
                    {
                      Library: 'Your documents and notes, together in one place.',
                      Collections: 'Keep related reading together.',
                      Activity: 'Follow each import from capture to searchable content.',
                      Storage: 'Choose what ECHO can read and manage automatic indexing.',
                      Settings: 'Your workspace, your device, your controls.',
                    }[view]
                  }
                </p>
              </div>
            </header>
          ) : null}
          {notice ? (
            <div className="notice" role="status">
              <Icon name="check" />
              <span>{notice}</span>
              <button
                className="icon-button"
                onClick={() => setNotice('')}
                aria-label="Dismiss notification"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          ) : null}
          {statusError ? <ErrorBox message={statusError} retry={refresh} /> : null}
          {status?.deletions_pending ? (
            <div className="info-banner" role="status">
              {status.deletions_pending} deletion(s) are waiting for local storage. Removed items
              stay hidden while ECHO retries.
            </div>
          ) : null}
          {view === 'Search' ? (
            <SearchPage
              headingRef={heading}
              api={api}
              revision={revision}
              status={status}
              history={history}
              changed={changed}
              openImport={() => setImporting(true)}
              openActivity={() => navigate('Activity')}
            />
          ) : null}
          {view === 'Library' ? (
            <LibraryPage
              api={api}
              revision={revision}
              changed={changed}
              openImport={() => setImporting(true)}
            />
          ) : null}
          {view === 'Collections' ? (
            <CollectionsPage
              api={api}
              revision={revision}
              changed={changed}
              openImport={() => setImporting(true)}
            />
          ) : null}
          {view === 'Activity' ? (
            <ActivityPage
              api={api}
              revision={revision}
              status={status}
              changed={changed}
              openImport={() => setImporting(true)}
            />
          ) : null}
          {view === 'Settings' ? (
            <SettingsPage
              api={api}
              settings={settings}
              status={status}
              theme={theme}
              toggleTheme={toggleTheme}
              changed={changed}
              history={history}
              openStorage={() => navigate('Storage')}
            />
          ) : null}
          {view === 'Storage' ? (
            <StoragePage
              api={api}
              initial={storageStatus}
              changed={(value) => {
                setStorageStatus(value)
                refresh()
              }}
            />
          ) : null}
        </main>
        <footer className="workspace-footer">
          <span>
            <Icon name="lock" size={13} />
            {history.entries === null
              ? 'Local workspace. Recent searches off.'
              : 'Local workspace. Recent searches stay in this browser.'}
          </span>
          <span>ECHO {settings.data?.version ?? ''}</span>
        </footer>
      </div>
      {importing ? (
        <ImportDialog
          api={api}
          maxBytes={settings.data?.max_upload_bytes ?? 20 * 1024 * 1024}
          close={() => setImporting(false)}
          changed={changed}
        />
      ) : null}
      {onboarding ? (
        <StorageConsent
          api={api}
          status={storageStatus}
          close={() => setOnboarding(false)}
          saved={(value) => {
            setStorageStatus(value)
            refresh()
          }}
        />
      ) : null}
    </div>
  )
}
