import { useEffect, useRef, useState } from 'react'
import { Api, errorText } from './api'
import { ErrorBox, Icon, Modal } from './components'

type ImportResult = { source_id: number; job_id: number; duplicate: boolean }
export function ImportDialog({
  api,
  maxBytes,
  close,
  changed,
}: {
  api: Api
  maxBytes: number
  close: () => void
  changed: (message?: string) => void
}) {
  const [kind, setKind] = useState<'files' | 'note'>('files')
  const [files, setFiles] = useState<File[]>([])
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [outcomes, setOutcomes] = useState<{ name: string; message: string; failed: boolean }[]>([])
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const select = (items: FileList | null) => {
    if (busy || !items) return
    setError('')
    setOutcomes([])
    setFiles(Array.from(items))
  }
  return (
    <Modal
      title="Add to your library"
      close={() => {
        if (!busy) close()
      }}
    >
      <div className="modal-body">
        <div className="segmented" role="group" aria-label="Import type">
          <button
            aria-pressed={kind === 'files'}
            disabled={busy}
            onClick={() => {
              setKind('files')
              setError('')
            }}
          >
            Documents
          </button>
          <button
            aria-pressed={kind === 'note'}
            disabled={busy}
            onClick={() => {
              setKind('note')
              setError('')
            }}
          >
            Write a note
          </button>
        </div>
        <form
          onSubmit={async (e) => {
            e.preventDefault()
            if (busy) return
            setError('')
            setOutcomes([])
            if (
              kind === 'files' &&
              (!files.length ||
                files.length > 50 ||
                files.some((f) => f.size > maxBytes || !f.size))
            ) {
              setError(
                `Choose 1–50 nonempty documents, each at most ${Math.round(maxBytes / 1024 / 1024)} MB.`,
              )
              return
            }
            setBusy(true)
            controller.current = new AbortController()
            try {
              // Detect an Origin/configuration change before streaming any documents.
              await api.request('/api/v1/session/check', {
                method: 'POST',
                signal: controller.current.signal,
              })
              if (kind === 'note') {
                const result = await api.json<ImportResult>(
                  '/api/v1/imports/notes',
                  'POST',
                  { title, text },
                  controller.current.signal,
                )
                changed(
                  result.duplicate
                    ? 'This note is already in your library.'
                    : 'Note added. Follow its progress in Sources.',
                )
                close()
              } else {
                const rows = []
                for (const file of files) {
                  if (controller.current.signal.aborted) break
                  try {
                    const result = await api.request<ImportResult>(
                      `/api/v1/imports/files?filename=${encodeURIComponent(file.name)}`,
                      {
                        method: 'POST',
                        body: file,
                        headers: { 'Content-Type': 'application/octet-stream' },
                        signal: controller.current.signal,
                      },
                    )
                    rows.push({
                      name: file.name,
                      message: result.duplicate ? 'Already in library' : 'Queued for processing',
                      failed: false,
                    })
                  } catch (error) {
                    if (controller.current.signal.aborted) break
                    rows.push({ name: file.name, message: errorText(error), failed: true })
                  }
                  setOutcomes([...rows])
                }
                changed()
                setFiles([])
              }
            } catch (error) {
              if (!controller.current.signal.aborted) setError(errorText(error))
            } finally {
              setBusy(false)
            }
          }}
        >
          {kind === 'files' ? (
            <>
              <div
                className="dropzone"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  select(e.dataTransfer.files)
                }}
              >
                <Icon name="upload" size={28} />
                <strong>Bring your documents here</strong>
                <p>
                  PDF, TXT, Markdown, Word, PNG or JPEG
                  <br />
                  Up to {Math.round(maxBytes / 1024 / 1024)} MB each
                </p>
                <label className="button">
                  Choose files
                  <input
                    className="file-input"
                    type="file"
                    multiple
                    accept=".pdf,.txt,.md,.markdown,.docx,.png,.jpg,.jpeg"
                    disabled={busy}
                    onChange={(e) => select(e.target.files)}
                  />
                </label>
              </div>
              {files.length ? (
                <ul className="file-list">
                  {files.map((f, i) => (
                    <li key={i}>
                      <Icon name="sources" size={16} />
                      <span>{f.name}</span>
                      <small>{Math.max(1, Math.round(f.size / 1024))} KB</small>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <div className="form-stack">
              <label>
                Note title
                <input
                  required
                  maxLength={200}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  disabled={busy}
                />
              </label>
              <label>
                Note text
                <textarea
                  required
                  rows={9}
                  maxLength={100000}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  disabled={busy}
                />
              </label>
            </div>
          )}
          {error ? <ErrorBox message={error} /> : null}
          {outcomes.length ? (
            <ul className="import-outcomes" aria-live="polite">
              {outcomes.map((row, i) => (
                <li key={i} className={row.failed ? 'failed' : ''}>
                  <Icon name={row.failed ? 'info' : 'check'} size={16} />
                  <div>
                    <strong>{row.name}</strong>
                    <span>{row.message}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
          <p className="fine-print">
            ECHO keeps a local copy. Original files stay where they are. OCR reads scanned PDFs and
            images locally; Images search also matches visual descriptions. Language and visual
            models must be available on this device.
          </p>
          <footer className="dialog-actions">
            <button type="button" className="button" disabled={busy} onClick={close}>
              {outcomes.length ? 'Done' : 'Cancel'}
            </button>
            <button
              className="button primary"
              disabled={busy || (kind === 'files' ? !files.length : !title.trim() || !text.trim())}
            >
              {busy ? 'Importing…' : kind === 'files' ? 'Import documents' : 'Save note'}
            </button>
          </footer>
        </form>
      </div>
    </Modal>
  )
}
