import { useRef } from 'react'
import { ErrorBox, Icon } from './components'
import { dateLabel, modes } from './types'
import type { IndexStatus } from './types'
import type { RecentSearch, SearchHistory } from './searchHistory'

export function RecentSearches({
  history,
  reuse,
}: {
  history: SearchHistory
  reuse: (entry: RecentSearch) => void
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  return (
    <section className="overview-panel" aria-label="Recent searches">
      <header className="overview-header">
        <span className="overview-icon">
          <Icon name="history" />
        </span>
        <div>
          <h2 ref={heading} tabIndex={-1}>
            Recent searches
          </h2>
          <p>{history.entries === null ? 'Off by default' : 'Saved in this browser'}</p>
        </div>
        {history.entries?.length ? (
          <button
            className="text-button"
            onClick={() => {
              history.clear()
              heading.current?.focus()
            }}
          >
            Clear history
          </button>
        ) : null}
      </header>
      {history.error ? <ErrorBox message={history.error} /> : null}
      {history.entries === null ? (
        <div className="overview-empty">
          <p>Save your last 12 searches in this browser so you can pick up where you left off.</p>
          <button
            className="button small"
            onClick={() => {
              history.setEnabled(true)
              heading.current?.focus()
            }}
          >
            Enable recent searches
          </button>
        </div>
      ) : history.entries.length ? (
        <ul className="recent-list">
          {history.entries.map((entry) => (
            <li key={JSON.stringify([entry.query, entry.mode])}>
              <button className="recent-query" onClick={() => reuse(entry)}>
                <Icon name="search" size={16} />
                <span>
                  <strong>{entry.query}</strong>
                  <small>
                    {modes.find((mode) => mode.value === entry.mode)?.label}
                    <span aria-hidden="true"> · </span>
                    <time dateTime={entry.searchedAt}>{dateLabel(entry.searchedAt)}</time>
                  </small>
                </span>
                <Icon name="arrow" size={16} />
              </button>
              <button
                className="icon-button recent-remove"
                aria-label={`Remove search: ${entry.query}`}
                onClick={() => {
                  history.remove(entry)
                  heading.current?.focus()
                }}
              >
                <Icon name="close" size={16} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="overview-empty">
          <p>Run a search to add it here.</p>
        </div>
      )}
    </section>
  )
}

export function LibraryActivity({
  status,
  openActivity,
  openImport,
}: {
  status?: IndexStatus
  openActivity: () => void
  openImport: () => void
}) {
  const counts = status?.sources_by_status ?? {}
  return (
    <section className="overview-panel" aria-label="Library activity">
      <header className="overview-header">
        <span className="overview-icon">
          <Icon name="activity" />
        </span>
        <div>
          <h2>Library activity</h2>
          <p>Document indexing</p>
        </div>
      </header>
      <dl className="overview-metrics">
        <div>
          <dt>Fully indexed</dt>
          <dd>{status ? (counts.indexed ?? 0) : '—'}</dd>
        </div>
        <div>
          <dt>Processing</dt>
          <dd>{status ? (counts.pending ?? 0) + (counts.processing ?? 0) : '—'}</dd>
        </div>
        <div>
          <dt>Needs attention</dt>
          <dd>{status ? (counts.failed ?? 0) : '—'}</dd>
        </div>
      </dl>
      <div className="overview-actions">
        <button className="button small" onClick={openActivity}>
          View activity <Icon name="arrow" size={15} />
        </button>
        <button className="text-button" onClick={openImport}>
          Import documents
        </button>
      </div>
    </section>
  )
}
