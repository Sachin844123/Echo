import { useCallback, useEffect, useRef, useState } from 'react'
import { Api, errorText, useGet } from './api'
import { Brand, ErrorBox, Icon } from './components'
import { SearchPage } from './SearchPage'
import { LibraryPage, CollectionsPage } from './LibraryPage'
import { SourcesPage, SettingsPage } from './SystemPages'
import { ImportDialog } from './ImportDialog'
import type { AppSettings, IndexStatus, View } from './types'

const nav: { view: View; icon: string }[] = [
  { view: 'Search', icon: 'search' },
  { view: 'Library', icon: 'library' },
  { view: 'Collections', icon: 'folder' },
  { view: 'Sources', icon: 'sources' },
  { view: 'Settings', icon: 'settings' },
]
function initialTheme(): 'light' | 'dark' {
  try {
    const value = localStorage.getItem('echo.theme.v1')
    if (value === 'light' || value === 'dark') return value
  } catch {
    /* Storage is optional. */
  }
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}
export function App() {
  const [theme, setTheme] = useState(initialTheme)
  const [api, setApi] = useState<Api | null>(null)
  const [expired, setExpired] = useState(false)
  const disconnect = useCallback(() => {
    setApi((current) => {
      current?.dispose()
      return null
    })
  }, [])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('echo.theme.v1', theme)
    } catch {
      /* No persistence required. */
    }
  }, [theme])
  const toggleTheme = () => setTheme((t) => (t === 'light' ? 'dark' : 'light'))
  return api ? (
    <Workspace api={api} disconnect={disconnect} theme={theme} toggleTheme={toggleTheme} />
  ) : (
    <Connect
      theme={theme}
      toggleTheme={toggleTheme}
      expired={expired}
      connect={(token) => {
        const session = new Api(token, () => {
          disconnect()
          setExpired(true)
        })
        return session
          .request('/api/v1/health')
          .then(() => {
            setExpired(false)
            setApi(session)
          })
          .catch((error) => {
            session.dispose()
            throw error
          })
      }}
    />
  )
}
function Connect({
  connect,
  theme,
  toggleTheme,
  expired,
}: {
  connect: (token: string) => Promise<void>
  theme: string
  toggleTheme: () => void
  expired: boolean
}) {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return (
    <main className="connect-page">
      <header className="connect-header">
        <Brand />
        <button
          className="icon-button"
          onClick={toggleTheme}
          aria-label={`Use ${theme === 'light' ? 'dark' : 'light'} theme`}
        >
          <Icon name={theme === 'light' ? 'moon' : 'sun'} />
        </button>
      </header>
      <div className="connect-layout">
        <section className="connect-intro">
          <div className="local-label">
            <span className="status-dot" />
            On your device
          </div>
          <h1>
            Your reading.
            <br />
            Within reach.
          </h1>
          <p>Find a document by the words you remember, the idea it held, or where you put it.</p>
          <div className="connect-principle">
            <Icon name="library" />
            <span>Only documents you import.</span>
          </div>
          <div className="connect-principle">
            <Icon name="lock" />
            <span>Stored and searched locally.</span>
          </div>
        </section>
        <section className="connect-card" aria-labelledby="connect-title">
          <div className="empty-icon">
            <Icon name="lock" size={24} />
          </div>
          <h2 id="connect-title">Open your workspace</h2>
          <p>Use the session token from your local ECHO server.</p>
          <form
            onSubmit={async (e) => {
              e.preventDefault()
              if (busy) return
              setBusy(true)
              setError('')
              try {
                await connect(token.trim())
                setToken('')
              } catch (e) {
                setError(errorText(e))
                setBusy(false)
              }
            }}
          >
            <label>
              Session token
              <input
                type="password"
                name="echo-session"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                required
                minLength={43}
                maxLength={128}
                autoFocus
              />
            </label>
            {error ? (
              <ErrorBox message={error} />
            ) : expired ? (
              <ErrorBox message="Your session ended. Enter the current server token to reconnect." />
            ) : null}
            <button className="button primary connect-button" disabled={busy || !token.trim()}>
              {busy ? 'Connecting…' : 'Open workspace'}
              <Icon name="arrow" />
            </button>
          </form>
          <p className="fine-print">
            <Icon name="lock" size={14} />
            Your token stays in this tab's memory. Closing or reloading the page locks the
            workspace.
          </p>
          <details className="connection-help">
            <summary>Where do I find my token?</summary>
            <p>
              In the PowerShell window used to start ECHO, run <code>$env:ECHO_SESSION_TOKEN</code>.
              Paste that value above. It is not an account password.
            </p>
          </details>
        </section>
      </div>
      <footer className="connect-footer">
        <span>ECHO</span>
        <span>A local library for your own documents.</span>
      </footer>
    </main>
  )
}
function Workspace({
  api,
  disconnect,
  theme,
  toggleTheme,
}: {
  api: Api
  disconnect: () => void
  theme: string
  toggleTheme: () => void
}) {
  const [view, setView] = useState<View>('Search')
  const [revision, setRevision] = useState(0)
  const [importing, setImporting] = useState(false)
  const [menu, setMenu] = useState(false)
  const [status, setStatus] = useState<IndexStatus>()
  const [statusError, setStatusError] = useState('')
  const [notice, setNotice] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)
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
      <aside className={`sidebar ${menu ? 'is-open' : ''}`}>
        <Brand />
        <div className="workspace-label">Personal workspace</div>
        <nav aria-label="Main navigation">
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
          <button className="nav-link" onClick={disconnect}>
            <Icon name="lock" />
            Lock workspace
          </button>
        </div>
      </aside>
      <div className="workspace-content">
        <header className="topbar">
          <div className="flex items-center gap-3">
            <button
              className="icon-button mobile-menu"
              aria-label="Toggle navigation"
              aria-expanded={menu}
              onClick={() => setMenu((m) => !m)}
            >
              <Icon name="menu" />
            </button>
            <span className="breadcrumb">
              Workspace <span aria-hidden="true">/</span> <strong>{view}</strong>
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
          <header className="page-heading">
            <div>
              <h1 ref={heading} tabIndex={-1}>
                {view === 'Search' ? 'Find it again.' : view === 'Library' ? 'Your library' : view}
              </h1>
              <p>
                {
                  {
                    Search: 'Start with what you remember. Search only what you’ve imported.',
                    Library: 'Your documents and notes, together in one place.',
                    Collections: 'Keep related reading together.',
                    Sources: 'Follow each import from capture to searchable content.',
                    Settings: 'Your workspace, your device, your controls.',
                  }[view]
                }
              </p>
            </div>
            {view === 'Search' ? (
              <span className="shortcut">
                <kbd>Ctrl</kbd>
                <kbd>K</kbd> to search
              </span>
            ) : null}
          </header>
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
              api={api}
              revision={revision}
              status={status}
              changed={changed}
              openImport={() => setImporting(true)}
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
          {view === 'Sources' ? (
            <SourcesPage api={api} revision={revision} status={status} changed={changed} />
          ) : null}
          {view === 'Settings' ? (
            <SettingsPage
              api={api}
              settings={settings}
              status={status}
              theme={theme}
              toggleTheme={toggleTheme}
              disconnect={disconnect}
              changed={changed}
            />
          ) : null}
        </main>
        <footer className="workspace-footer">
          <span>
            <Icon name="lock" size={13} />
            No cloud sync. No search history.
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
    </div>
  )
}
