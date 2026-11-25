import { useEffect, useRef, useState } from 'react'
import { Api, errorText, useGet } from './api'
import { Confirm, Empty, ErrorBox, Icon, Loading, Pagination, StatusBadge } from './components'
import { PreviewPanel } from './PreviewPanel'
import { dateLabel, sourceNames } from './types'
import type { AppSettings, IndexStatus, Job, Page } from './types'
import type { SearchHistory } from './searchHistory'

export function ActivityPage({
  api,
  revision,
  status,
  changed,
  openImport,
}: {
  api: Api
  revision: number
  status?: IndexStatus
  changed: (message?: string) => void
  openImport: () => void
}) {
  const [offset, setOffset] = useState(0)
  const [tick, setTick] = useState(0)
  const [selected, setSelected] = useState<number>()
  const [error, setError] = useState('')
  const [retrying, setRetrying] = useState<number>()
  const previewTrigger = useRef<HTMLButtonElement>(null)
  const jobs = useGet<Page<Job> & { worker_alive: boolean }>(
    api,
    `/api/v1/indexing-jobs?limit=30&offset=${offset}`,
    revision + tick,
  )
  useEffect(() => {
    if (jobs.data && !jobs.data.items.length && offset > 0) setOffset(Math.max(0, offset - 30))
    if (!jobs.data?.items.some((j) => j.status === 'pending' || j.status === 'running')) return
    const timer = setInterval(() => {
      if (!document.hidden) setTick((t) => t + 1)
    }, 5000)
    return () => clearInterval(timer)
  }, [jobs.data, offset])
  const counts = status?.sources_by_status ?? {}
  const summary = [
    { label: 'Fully indexed', icon: 'check', count: counts.indexed ?? 0 },
    {
      label: 'Processing',
      icon: 'activity',
      count: (counts.pending ?? 0) + (counts.processing ?? 0),
    },
    { label: 'Needs attention', icon: 'info', count: counts.failed ?? 0 },
  ]
  return (
    <>
      <dl className="activity-summary" aria-label="Library status">
        {summary.map((item) => (
          <div key={item.label}>
            <dt>
              <span className="overview-icon">
                <Icon name={item.icon} size={18} />
              </span>
              {item.label}
            </dt>
            <dd>{status ? item.count : '—'}</dd>
          </div>
        ))}
      </dl>
      <div className="list-toolbar">
        <div>
          <h2>Import activity</h2>
          <p className="fine-print">Extraction and indexing jobs, newest first.</p>
        </div>
        <button className="button small" onClick={() => setTick((t) => t + 1)}>
          <Icon name="refresh" size={16} />
          Refresh activity
        </button>
      </div>
      {error ? <ErrorBox message={error} /> : null}
      {jobs.data && !jobs.data.worker_alive ? (
        <ErrorBox message="The indexing worker is not running. Restart your local ECHO server." />
      ) : null}
      <div className={`document-workspace ${selected ? 'has-preview' : ''}`}>
        <section aria-label="Indexing activity">
          {jobs.loading ? (
            <Loading label="Loading activity" />
          ) : jobs.error ? (
            <ErrorBox message={jobs.error} retry={() => setTick((t) => t + 1)} />
          ) : jobs.data?.items.length ? (
            <>
              <div className="job-list">
                {jobs.data.items.map((job) => (
                  <article className="job-row" key={job.id}>
                    <div className="job-main">
                      <span className="file-icon">
                        <Icon name="sources" />
                      </span>
                      <div>
                        <button
                          className="text-button document-title"
                          onClick={(event) => {
                            previewTrigger.current = event.currentTarget
                            setSelected(job.source_id)
                          }}
                        >
                          {job.title}
                        </button>
                        <p className="job-details">
                          <span>{sourceNames[job.source_type]}</span>
                          <span>
                            {job.stage === 'ingestion'
                              ? 'Text extraction'
                              : job.stage === 'visual'
                                ? 'Visual indexing'
                                : 'Text indexing'}
                          </span>
                          <span>Attempt {job.attempts}</span>
                          {job.updated_at ? (
                            <time dateTime={job.updated_at}>{dateLabel(job.updated_at)}</time>
                          ) : null}
                        </p>
                      </div>
                      <StatusBadge status={job.status} />
                    </div>
                    {job.error ? (
                      <div className="job-error">
                        <Icon name="info" size={17} />
                        <span>{job.error.message}</span>
                        {job.retryable ? (
                          <button
                            className="button small"
                            disabled={retrying !== undefined}
                            onClick={async () => {
                              setRetrying(job.id)
                              setError('')
                              try {
                                await api.request(`/api/v1/indexing-jobs/${job.id}/retry`, {
                                  method: 'POST',
                                })
                                changed('Processing retry queued.')
                              } catch (error) {
                                setError(errorText(error))
                              } finally {
                                setRetrying(undefined)
                              }
                            }}
                          >
                            {retrying === job.id ? 'Retrying…' : 'Retry job'}
                          </button>
                        ) : (
                          <span className="muted">Attempt limit reached</span>
                        )}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
              <Pagination offset={offset} total={jobs.data.total} change={setOffset} />
            </>
          ) : (
            <Empty
              icon="activity"
              title="Your next import starts here."
              action={
                <button className="button" onClick={openImport}>
                  <Icon name="plus" size={16} /> Import documents
                </button>
              }
            >
              Import a document or write a note. Its extraction and indexing progress will appear
              here.
            </Empty>
          )}
        </section>
        {selected ? (
          <PreviewPanel
            key={selected}
            api={api}
            sourceId={selected}
            revision={revision}
            changed={changed}
            close={() => {
              setSelected(undefined)
              requestAnimationFrame(() => previewTrigger.current?.focus())
            }}
          />
        ) : null}
      </div>
    </>
  )
}

export function SettingsPage({
  api,
  settings,
  status,
  theme,
  toggleTheme,
  changed,
  history,
  openStorage,
}: {
  api: Api
  settings: { data?: AppSettings; loading: boolean; error?: string }
  status?: IndexStatus
  theme: string
  toggleTheme: () => void
  changed: (message?: string) => void
  history: SearchHistory
  openStorage: () => void
}) {
  const [deleting, setDeleting] = useState(false)
  return (
    <div className="settings-page">
      {settings.error ? <ErrorBox message={settings.error} retry={() => changed()} /> : null}
      <section className="settings-section">
        <div className="settings-section-heading">
          <Icon name="sun" />
          <div>
            <h2>Appearance</h2>
            <p>Make the workspace comfortable to read.</p>
          </div>
        </div>
        <div className="setting-row">
          <div>
            <strong>Color theme</strong>
            <p>
              {theme === 'light'
                ? 'Light surfaces with a calm green accent.'
                : 'Dark surfaces with comfortable text contrast.'}
            </p>
          </div>
          <button className="button" onClick={toggleTheme}>
            <Icon name={theme === 'light' ? 'moon' : 'sun'} />
            {theme === 'light' ? 'Use dark theme' : 'Use light theme'}
          </button>
        </div>
      </section>
      <section className="settings-section">
        <div className="settings-section-heading">
          <Icon name="lock" />
          <div>
            <h2>Privacy</h2>
            <p>Your library stays on this device.</p>
          </div>
        </div>
        <div className="setting-row">
          <div>
            <strong>Recent searches</strong>
            <p>
              Keep up to 12 searches in this browser. Turning this off clears the saved searches.
            </p>
          </div>
          <div className="history-controls">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={history.entries !== null}
                onChange={(event) => history.setEnabled(event.target.checked)}
              />
              Remember recent searches
            </label>
            {history.entries?.length ? (
              <button className="text-button" onClick={history.clear}>
                Clear history
              </button>
            ) : null}
          </div>
        </div>
        {history.error ? <ErrorBox message={history.error} /> : null}
        <div className="setting-row">
          <div>
            <strong>Local file access</strong>
            <p>Approve folders and control automatic indexing.</p>
          </div>
          <button className="button" onClick={openStorage}>
            Storage &amp; Permissions
          </button>
        </div>
      </section>
      <section className="settings-section">
        <div className="settings-section-heading">
          <Icon name="search" />
          <div>
            <h2>Local search</h2>
            <p>Configuration from the running server.</p>
          </div>
        </div>
        {settings.loading ? (
          <Loading label="Loading configuration" />
        ) : settings.data ? (
          <>
            <dl className="configuration">
              <div>
                <dt>OCR</dt>
                <dd>
                  {settings.data.ocr.available
                    ? 'Ready locally'
                    : settings.data.ocr.enabled
                      ? 'Language data unavailable'
                      : 'Disabled'}{' '}
                  ({settings.data.ocr.languages.join(' + ')})
                </dd>
              </div>
              <div>
                <dt>Visual image search</dt>
                <dd>
                  {status?.visual?.available
                    ? `Ready locally · ${status.visual.image_count} images`
                    : 'Local CLIP model unavailable'}
                </dd>
              </div>
              <div>
                <dt>Retrieval profile</dt>
                <dd>{settings.data.retrieval.retrieval_profile}</dd>
              </div>
              <div>
                <dt>Embedding model</dt>
                <dd>{settings.data.retrieval.embedding_model_name}</dd>
              </div>
              <div>
                <dt>Model status</dt>
                <dd>
                  {status
                    ? status.semantic_available
                      ? 'Available locally'
                      : 'Unavailable — keywords still work'
                    : 'Checking…'}
                </dd>
              </div>
              <div>
                <dt>Indexed passages</dt>
                <dd>{status?.vector_count ?? '—'}</dd>
              </div>
              <div>
                <dt>Chunk size / overlap</dt>
                <dd>
                  {settings.data.retrieval.chunk_tokens} / {settings.data.retrieval.chunk_overlap}{' '}
                  tokens
                </dd>
              </div>
              <div>
                <dt>Candidates per method</dt>
                <dd>{settings.data.retrieval.candidate_pool}</dd>
              </div>
              <div>
                <dt>Maximum file size</dt>
                <dd>{Math.round(settings.data.max_upload_bytes / 1024 / 1024)} MB</dd>
              </div>
            </dl>
            {status && !status.semantic_available ? (
              <div className="info-banner">
                <Icon name="info" />
                <span>
                  The local model is missing, unavailable, or needs index recovery. Follow the model
                  setup instructions in README, then restart ECHO. This dashboard never downloads a
                  model.
                </span>
              </div>
            ) : null}
            <p className="fine-print">
              Retrieval parameters are configured before server startup. Context weights are
              placeholders until evaluated on your tuning dataset; no accuracy improvement is
              assumed.
            </p>
          </>
        ) : null}
      </section>
      <section className="settings-section danger-zone">
        <div className="settings-section-heading">
          <Icon name="trash" />
          <div>
            <h2>Delete library</h2>
            <p>Remove the content you have imported into ECHO.</p>
          </div>
        </div>
        <div className="setting-row">
          <div>
            <strong>Delete all imported content</strong>
            <p>
              Removes stored copies, text, indexes, collections, jobs, and this browser’s recent
              searches. Your original files and prepared models are kept.
            </p>
          </div>
          <button className="button danger-outline" onClick={() => setDeleting(true)}>
            Delete all content
          </button>
        </div>
        <p className="fine-print">
          This does not erase backups or promise forensic erasure of disk blocks.
        </p>
      </section>
      {deleting ? (
        <Confirm
          title="Delete all imported content?"
          label="Permanently delete library"
          phrase="DELETE ALL"
          description="This removes the entire library, collections, and recent searches in this browser. Automatic folder indexing turns off. Original files and local models are kept."
          close={() => setDeleting(false)}
          action={async () => {
            const result = await api.json<{ status: string }>('/api/v1/library', 'DELETE', {
              confirmation: 'DELETE ALL',
            })
            history.clear()
            changed(
              result.status === 'deleted'
                ? 'Library deleted. Your original files were kept.'
                : 'Library hidden. ECHO is retrying unfinished deletions.',
            )
          }}
        />
      ) : null}
    </div>
  )
}
