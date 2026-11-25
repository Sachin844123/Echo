import { useEffect, useState } from 'react'
import { Api, errorText, useGet } from './api'
import { Confirm, Empty, ErrorBox, Loading, Modal, Pagination, StatusBadge } from './components'
import type { Page } from './types'

type Mode = 'all' | 'personal' | 'selected' | 'deny'
type Action = 'pause' | 'resume' | 'cancel' | 'rescan'
export interface StorageStatus {
  mode: Mode | null
  state: 'active' | 'paused' | 'cancelled'
  phase: 'scanning' | 'idle'
  roots: string[]
  exclusions: string[]
  extensions: string[]
  files: number
  indexed_files: number
  stored_bytes: number
  pending_jobs: number
  failed_jobs: number
  purging_sources: number
  progress: Record<string, number>
  errors: { code: string; message: string; count: number }[]
}
type Options = {
  fixed_drives: string[]
  personal_folders: string[]
  supported_extensions: string[]
}
type IndexedFile = { path: string; bytes: number; source_id: number; status: string }

const modes: { value: Mode; title: string; help: string }[] = [
  {
    value: 'all',
    title: 'All Accessible Local Files',
    help: 'Eligible files on the fixed drives shown below.',
  },
  {
    value: 'personal',
    title: 'Personal Folders Only',
    help: 'Desktop, Documents, Downloads, and Pictures where available.',
  },
  { value: 'selected', title: 'Selected Folders Only', help: 'Only the local folders you enter.' },
  { value: 'deny', title: 'Deny Access', help: 'Use ECHO with manually imported files and notes.' },
]
const lines = (value: string) =>
  value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
const size = (bytes: number) =>
  bytes < 1024
    ? `${bytes} B`
    : bytes < 1024 ** 2
      ? `${(bytes / 1024).toFixed(1)} KiB`
      : `${(bytes / 1024 ** 2).toFixed(1)} MiB`

export function StorageConsent({
  api,
  status,
  close,
  saved,
}: {
  api: Api
  status: StorageStatus
  close: () => void
  saved: (value: StorageStatus) => void
}) {
  const options = useGet<Options>(api, '/api/v1/storage/options')
  const [mode, setMode] = useState<Mode>(status.mode ?? 'deny')
  const [folders, setFolders] = useState(status.mode === 'selected' ? status.roots.join('\n') : '')
  const [exclusions, setExclusions] = useState(status.exclusions.join('\n'))
  const [extensions, setExtensions] = useState(status.extensions)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const choices = mode === 'all' ? options.data?.fixed_drives : options.data?.personal_folders
  return (
    <Modal
      title={status.mode === null ? 'Allow ECHO to access local files?' : 'Storage permissions'}
      close={() => !busy && close()}
    >
      <form
        className="modal-body storage-form"
        onSubmit={async (event) => {
          event.preventDefault()
          if (busy) return
          setError('')
          setBusy(true)
          try {
            const value = await api.json<StorageStatus>('/api/v1/storage/permission', 'PUT', {
              mode,
              confirm: true,
              folders: mode === 'selected' ? lines(folders) : [],
              exclusions: mode === 'deny' ? [] : lines(exclusions),
              extensions: mode === 'deny' ? status.extensions : extensions,
            })
            saved(value)
            close()
          } catch (failure) {
            setError(errorText(failure))
          } finally {
            setBusy(false)
          }
        }}
      >
        <p>
          ECHO can read and index eligible files in the folders you approve. Original files stay in
          place, and indexing runs on this device.
        </p>
        <fieldset className="permission-choices" disabled={busy}>
          <legend>Choose an access level</legend>
          {modes.map((item) => (
            <label className="permission-choice" key={item.value}>
              <input
                type="radio"
                name="storage-mode"
                value={item.value}
                checked={mode === item.value}
                onChange={() => setMode(item.value)}
              />
              <span>
                <strong>{item.title}</strong>
                <small>{item.help}</small>
              </span>
            </label>
          ))}
        </fieldset>
        {mode === 'all' || mode === 'personal' ? (
          <section>
            <h3>{mode === 'all' ? 'Fixed drives' : 'Personal folder locations'}</h3>
            {options.loading ? (
              <Loading label="Checking local locations" />
            ) : options.error ? (
              <ErrorBox message={options.error} />
            ) : choices?.length ? (
              <ul className="storage-paths">
                {choices.map((path) => (
                  <li key={path}>{path}</li>
                ))}
              </ul>
            ) : (
              <p>No locations available for this access level.</p>
            )}
          </section>
        ) : null}
        {mode === 'selected' ? (
          <label>
            Approved folders, one absolute path per line
            <textarea
              value={folders}
              onChange={(event) => setFolders(event.target.value)}
              rows={3}
              placeholder={'C:\\Users\\YourName\\Documents'}
              disabled={busy}
              required
            />
          </label>
        ) : null}
        {mode !== 'deny' ? (
          <>
            <label>
              Excluded folders, one absolute path per line
              <textarea
                value={exclusions}
                onChange={(event) => setExclusions(event.target.value)}
                rows={2}
                disabled={busy}
              />
            </label>
            <fieldset className="storage-type-list" disabled={busy}>
              <legend>File types to index</legend>
              {(options.data?.supported_extensions ?? status.extensions).map((ext) => (
                <label className="checkbox-row" key={ext}>
                  <input
                    type="checkbox"
                    checked={extensions.includes(ext)}
                    onChange={(event) =>
                      setExtensions((current) =>
                        event.target.checked
                          ? [...current, ext]
                          : current.filter((item) => item !== ext),
                      )
                    }
                  />
                  {ext}
                </label>
              ))}
            </fieldset>
          </>
        ) : (
          <p className="fine-print">
            Denying access stops monitoring and purges copies indexed only through local access.
            Manual imports stay in your library.
          </p>
        )}
        {error ? <ErrorBox message={error} /> : null}
        <footer className="dialog-actions">
          <button className="button" type="button" onClick={close} disabled={busy}>
            {status.mode === null ? 'Not now' : 'Cancel'}
          </button>
          <button
            className="button primary"
            disabled={
              busy ||
              (mode !== 'deny' && !extensions.length) ||
              ((mode === 'all' || mode === 'personal') && !choices?.length)
            }
          >
            {busy ? 'Saving…' : 'Save permission'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}

export function StoragePage({
  api,
  initial,
  changed,
}: {
  api: Api
  initial: StorageStatus
  changed: (value: StorageStatus) => void
}) {
  const [status, setStatus] = useState(initial)
  const [offset, setOffset] = useState(0)
  const [edit, setEdit] = useState(false)
  const [revoke, setRevoke] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [pollError, setPollError] = useState('')
  const files = useGet<Page<IndexedFile>>(
    api,
    `/api/v1/storage/files?offset=${offset}`,
    status.files +
      (status.progress.queued ?? 0) +
      (status.progress.linked ?? 0) +
      status.indexed_files,
  )
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        if (!document.hidden) {
          const value = await api.request<StorageStatus>('/api/v1/storage', {
            signal: controller.signal,
          })
          if (!controller.signal.aborted) {
            setStatus(value)
            setPollError('')
          }
        }
      } catch (failure) {
        if (!controller.signal.aborted) setPollError(errorText(failure))
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 2500)
      }
    }
    void poll()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [api])
  function saved(value: StorageStatus) {
    setStatus(value)
    setOffset(0)
    changed(value)
  }
  async function control(action: Action) {
    setBusy(true)
    setError('')
    try {
      saved(await api.json<StorageStatus>('/api/v1/storage/control', 'POST', { action }))
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
    }
  }
  const enabled = status.roots.length > 0
  return (
    <div className="settings-page storage-page">
      {error || pollError ? <ErrorBox message={error || pollError} /> : null}
      <section className="settings-section">
        <div className="section-bar">
          <h2>Local file access</h2>
          <button className="button" onClick={() => setEdit(true)}>
            Review permission
          </button>
        </div>
        <p className="storage-mode">
          {modes.find((item) => item.value === status.mode)?.title ??
            'Permission has not been set.'}
        </p>
        {enabled ? (
          <>
            <h3>Approved folders</h3>
            <ul className="storage-paths">
              {status.roots.map((path) => (
                <li key={path}>{path}</li>
              ))}
            </ul>
            {status.exclusions.length ? (
              <>
                <h3>Excluded folders</h3>
                <ul className="storage-paths">
                  {status.exclusions.map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
              </>
            ) : null}
            <p className="fine-print">Types: {status.extensions.join(', ')}</p>
            <button className="button danger-outline" onClick={() => setRevoke(true)}>
              Revoke and purge
            </button>
          </>
        ) : (
          <p className="fine-print">Manual imports are available with any access level.</p>
        )}
      </section>
      <section className="settings-section">
        <div className="section-bar">
          <h2>Automatic indexing</h2>
          <span className="plain-badge" role="status">
            {enabled
              ? status.phase === 'scanning'
                ? 'Scanning'
                : status.state === 'active'
                  ? 'Monitoring'
                  : status.state
              : 'Off'}
          </span>
        </div>
        <dl className="configuration">
          <div>
            <dt>Indexed files</dt>
            <dd>
              {status.indexed_files} of {status.files}
            </dd>
          </div>
          <div>
            <dt>Stored source copies</dt>
            <dd>{size(status.stored_bytes)}</dd>
          </div>
          <div>
            <dt>Files examined</dt>
            <dd>{status.progress.examined ?? 0}</dd>
          </div>
          <div>
            <dt>Pending indexing jobs</dt>
            <dd>{status.pending_jobs}</dd>
          </div>
        </dl>
        {status.purging_sources ? (
          <p role="status">Removing {status.purging_sources} indexed source copies.</p>
        ) : null}
        {enabled ? (
          <div className="storage-actions">
            {status.state === 'active' ? (
              <button className="button" disabled={busy} onClick={() => void control('pause')}>
                Pause
              </button>
            ) : (
              <button className="button" disabled={busy} onClick={() => void control('resume')}>
                Resume
              </button>
            )}
            <button
              className="button"
              disabled={busy || status.state === 'cancelled'}
              onClick={() => void control('cancel')}
            >
              Cancel indexing
            </button>
            <button className="button" disabled={busy} onClick={() => void control('rescan')}>
              Rescan
            </button>
          </div>
        ) : null}
        {status.errors.length ? (
          <ul className="storage-paths" aria-label="Indexing errors">
            {status.errors.map((item) => (
              <li key={item.code}>
                {item.message} ({item.count})
              </li>
            ))}
          </ul>
        ) : null}
      </section>
      <section className="settings-section">
        <h2>Files in approved folders</h2>
        {files.error ? (
          <ErrorBox message={files.error} />
        ) : files.loading ? (
          <Loading label="Loading monitored files" />
        ) : files.data?.total ? (
          <>
            <ul className="storage-files">
              {files.data.items.map((file) => (
                <li key={file.path}>
                  <span>{file.path}</span>
                  <span>{size(file.bytes)}</span>
                  <StatusBadge status={file.status} />
                </li>
              ))}
            </ul>
            <Pagination offset={offset} total={files.data.total} change={setOffset} />
          </>
        ) : (
          <Empty icon="folder" title="No files tracked yet">
            Approve a folder or wait for the next scan.
          </Empty>
        )}
      </section>
      {edit ? (
        <StorageConsent api={api} status={status} close={() => setEdit(false)} saved={saved} />
      ) : null}
      {status.failed_jobs ? (
        <p role="status">
          {status.failed_jobs} processing jobs failed. Open Activity for job details and retries.
        </p>
      ) : null}
      {revoke ? (
        <Confirm
          title="Revoke local file access?"
          description="ECHO will stop monitoring these folders and delete automatically indexed copies. Original files and manual imports stay in place."
          label="Revoke and purge"
          close={() => setRevoke(false)}
          action={async () =>
            saved(
              await api.json<StorageStatus>('/api/v1/storage/permission', 'PUT', {
                mode: 'deny',
                confirm: true,
              }),
            )
          }
        />
      ) : null}
    </div>
  )
}
