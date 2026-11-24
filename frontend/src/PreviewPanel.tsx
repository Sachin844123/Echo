import { useEffect, useRef, useState } from 'react'
import { Api, errorText, useCollections, useGet } from './api'
import { Confirm, ErrorBox, Icon, Loading, StatusBadge } from './components'
import { dateLabel, sourceNames } from './types'
import type { Preview, SearchHit, Source } from './types'
import { ImagePreview } from './ImagePreview'

export function PreviewPanel({
  api,
  sourceId,
  hit,
  revision,
  changed,
  close,
}: {
  api: Api
  sourceId: number
  hit?: SearchHit
  revision: number
  changed: (message?: string) => void
  close: () => void
}) {
  const [offset, setOffset] = useState(Math.max(0, (hit?.start_offset ?? 0) - 300))
  const [localRevision, setLocalRevision] = useState(0)
  const [rename, setRename] = useState(false)
  const [title, setTitle] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [memberships, setMemberships] = useState<number[]>([])
  const heading = useRef<HTMLHeadingElement>(null)
  const source = useGet<Source>(api, `/api/v1/sources/${sourceId}`, revision + localRevision)
  const preview = useGet<Preview>(
    api,
    `/api/v1/sources/${sourceId}/document?offset=${offset}&length=4000`,
    revision + localRevision,
  )
  const collections = useCollections(api, revision)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  useEffect(() => {
    if (source.data) setMemberships(source.data.collection_ids ?? [])
  }, [source.data])
  async function changeCollection(id: number, member: boolean) {
    setBusy(true)
    setError('')
    setMemberships((ids) => (member ? ids.filter((value) => value !== id) : [...ids, id]))
    try {
      await api.request(`/api/v1/collections/${id}/sources/${sourceId}`, {
        method: member ? 'DELETE' : 'PUT',
      })
      setLocalRevision((r) => r + 1)
      changed()
    } catch (error) {
      setMemberships(source.data?.collection_ids ?? [])
      setError(errorText(error))
    } finally {
      setBusy(false)
    }
  }
  function highlighted() {
    if (!preview.data) return null
    const points = Array.from(preview.data.text)
    if (!hit) return preview.data.text
    const start = Math.max(0, hit.start_offset - offset),
      end = Math.min(points.length, hit.end_offset - offset)
    if (start >= end) return preview.data.text
    return (
      <>
        {points.slice(0, start).join('')}
        <mark>{points.slice(start, end).join('')}</mark>
        {points.slice(end).join('')}
      </>
    )
  }
  return (
    <aside className="preview-panel" aria-label="Document preview">
      <div className="preview-toolbar">
        <span>
          <Icon name="sources" size={16} />
          Document preview
        </span>
        <button className="icon-button" onClick={close} aria-label="Close preview">
          <Icon name="close" />
        </button>
      </div>
      <div className="preview-content">
        <h2 ref={heading} tabIndex={-1}>
          {source.data?.title ?? hit?.title ?? 'Document'}
        </h2>
        {source.error ? (
          <ErrorBox message={source.error} retry={() => setLocalRevision((r) => r + 1)} />
        ) : null}
        {source.data ? (
          <>
            <div className="preview-meta">
              <span>{sourceNames[source.data.source_type]}</span>
              <span>{dateLabel(source.data.captured_at)}</span>
              <StatusBadge status={source.data.processing_status} />
            </div>
            <div className="preview-actions">
              <button
                className="button small"
                disabled={busy || ['pending', 'processing'].includes(source.data.processing_status)}
                onClick={async () => {
                  setBusy(true)
                  setError('')
                  try {
                    await api.request(`/api/v1/sources/${sourceId}/reprocess`, { method: 'POST' })
                    changed('Reprocessing queued. Follow its progress in Sources.')
                    setLocalRevision((r) => r + 1)
                  } catch (failure) {
                    setError(errorText(failure))
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                Reprocess
              </button>
              <button
                className="button small"
                onClick={() => {
                  setTitle(source.data!.title)
                  setRename((v) => !v)
                }}
              >
                Rename
              </button>
              <button className="button small danger-outline" onClick={() => setDeleting(true)}>
                <Icon name="trash" size={15} />
                Delete
              </button>
            </div>
            {rename ? (
              <form
                className="rename-form"
                onSubmit={async (e) => {
                  e.preventDefault()
                  setBusy(true)
                  setError('')
                  try {
                    await api.json(`/api/v1/sources/${sourceId}`, 'PATCH', { title })
                    setRename(false)
                    changed('Document renamed.')
                    setLocalRevision((r) => r + 1)
                  } catch (error) {
                    setError(errorText(error))
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                <label>
                  Document title
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    required
                    maxLength={200}
                  />
                </label>
                <button className="button small" disabled={busy || !title.trim()}>
                  Save title
                </button>
              </form>
            ) : null}
          </>
        ) : null}
        {error ? <ErrorBox message={error} /> : null}
        {source.data?.source_type === 'image' ? (
          <ImagePreview api={api} sourceId={sourceId} title={source.data.title} />
        ) : null}
        {hit ? (
          <section className="matched-excerpt">
            <h3>Matched passage {hit.page_number ? <span>Page {hit.page_number}</span> : null}</h3>
            <p>{hit.excerpt}</p>
            {hit.heading ? <small>{hit.heading}</small> : null}
          </section>
        ) : null}
        <section className="document-text">
          <h3>Document text</h3>
          {preview.data?.extraction_method.startsWith('image_filename') ? (
            <p className="fine-print">
              {preview.data.extraction_method === 'image_filename'
                ? 'No text was recognized.'
                : 'OCR was unavailable for this import. Check Settings and reprocess after setup.'}{' '}
              Showing the imported filename.
            </p>
          ) : preview.data?.extraction_method === 'pymupdf_text_ocr_unavailable' ? (
            <p className="fine-print">
              Showing the PDF text layer. Set up OCR and reprocess to read text in its images.
            </p>
          ) : preview.data?.extraction_method.includes('tesseract') ? (
            <p className="fine-print">
              Text includes local OCR. Recognition can contain errors; check the original when
              precision matters.
            </p>
          ) : null}
          {preview.loading ? (
            <Loading label="Loading preview" />
          ) : preview.error ? (
            <div className="info-banner">
              {source.data?.processing_status === 'pending' ||
              source.data?.processing_status === 'processing'
                ? 'The document is still being prepared. Refresh after processing finishes.'
                : 'Preview is unavailable. Check this document in Sources for processing errors.'}
              <button className="button small" onClick={() => setLocalRevision((r) => r + 1)}>
                Refresh preview
              </button>
            </div>
          ) : (
            <>
              <div className="reading-text">{highlighted()}</div>
              <div className="preview-pagination">
                <button
                  className="button small"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 4000))}
                >
                  Previous text
                </button>
                <span>
                  {offset + 1}–{Math.min(offset + 4000, preview.data?.content_length ?? 0)}
                </span>
                <button
                  className="button small"
                  disabled={!preview.data?.has_more}
                  onClick={() => setOffset(offset + 4000)}
                >
                  Next text
                </button>
              </div>
            </>
          )}
        </section>
        <section className="membership">
          <h3>In collections</h3>
          {collections.error ? (
            <ErrorBox message={collections.error} />
          ) : collections.loading ? (
            <Loading label="Loading collections" />
          ) : collections.data?.length ? (
            <div className="membership-list">
              {collections.data.map((c) => (
                <label key={c.id} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={memberships.includes(c.id)}
                    disabled={busy || !source.data}
                    onChange={() => void changeCollection(c.id, memberships.includes(c.id))}
                  />
                  <Icon name="folder" size={16} />
                  <span>{c.name}</span>
                </label>
              ))}
            </div>
          ) : (
            <p className="muted">Create a collection in Collections to organize this document.</p>
          )}
        </section>
      </div>
      {deleting ? (
        <Confirm
          title="Delete this document?"
          label="Delete document"
          description="Remove the imported copy, extracted text and search entries from ECHO. Your original file is kept."
          close={() => setDeleting(false)}
          action={async () => {
            const result = await api.request<{ status: string }>(`/api/v1/sources/${sourceId}`, {
              method: 'DELETE',
            })
            changed(
              result.status === 'deleted'
                ? 'Document deleted.'
                : 'Document hidden. ECHO will finish deleting it when storage is available.',
            )
            close()
          }}
        />
      ) : null}
    </aside>
  )
}
