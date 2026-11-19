import { useEffect, useState } from 'react'
import { Api, errorText, useCollections, useGet } from './api'
import {
  Confirm,
  Empty,
  ErrorBox,
  Icon,
  Loading,
  Modal,
  Pagination,
  StatusBadge,
} from './components'
import { PreviewPanel } from './PreviewPanel'
import { dateLabel, sourceNames } from './types'
import type { Collection, Page, Source } from './types'

type Props = {
  api: Api
  revision: number
  changed: (message?: string) => void
  openImport: () => void
}
export function LibraryPage({
  api,
  revision,
  changed,
  openImport,
  collectionId,
}: Props & { collectionId?: number }) {
  const [offset, setOffset] = useState(0)
  const [type, setType] = useState('')
  const [collection, setCollection] = useState('')
  const [selected, setSelected] = useState<number>()
  const [tick, setTick] = useState(0)
  const path = `/api/v1/sources?limit=30&offset=${offset}${type ? `&source_type=${type}` : ''}${collectionId || collection ? `&collection_id=${collectionId || collection}` : ''}`
  const sources = useGet<Page<Source>>(api, path, revision + tick)
  const collections = useCollections(api, revision)
  useEffect(() => {
    if (sources.data && !sources.data.items.length && offset > 0)
      setOffset(Math.max(0, offset - 30))
    if (!sources.data?.items.some((s) => ['pending', 'processing'].includes(s.processing_status)))
      return
    const timer = setInterval(() => {
      if (!document.hidden) setTick((t) => t + 1)
    }, 5000)
    return () => clearInterval(timer)
  }, [sources.data, offset])
  return (
    <>
      <div className="list-toolbar">
        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-field">
            File type
            <select
              aria-label="File type"
              value={type}
              onChange={(e) => {
                setType(e.target.value)
                setOffset(0)
              }}
            >
              <option value="">All types</option>
              {Object.entries(sourceNames).map(([value, name]) => (
                <option key={value} value={value}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          {!collectionId ? (
            <label className="inline-field">
              Collection
              <select
                aria-label="Collection"
                value={collection}
                onChange={(e) => {
                  setCollection(e.target.value)
                  setOffset(0)
                }}
              >
                <option value="">All collections</option>
                {collections.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        <button className="button small" onClick={() => setTick((t) => t + 1)}>
          <Icon name="refresh" size={16} />
          Refresh
        </button>
      </div>
      {collections.error ? <ErrorBox message={collections.error} /> : null}
      <div className={`document-workspace ${selected ? 'has-preview' : ''}`}>
        <section className="library-list" aria-label="Documents">
          {sources.loading ? (
            <Loading />
          ) : sources.error ? (
            <ErrorBox message={sources.error} retry={() => setTick((t) => t + 1)} />
          ) : sources.data?.items.length ? (
            <>
              <div className="section-bar">
                <h2>
                  {sources.data.total} document{sources.data.total === 1 ? '' : 's'}
                </h2>
                <span>Recently captured first</span>
              </div>
              <div className="library-table">
                <div className="library-table-header" aria-hidden="true">
                  <span>Name</span>
                  <span>Captured</span>
                  <span>Status</span>
                </div>
                {sources.data.items.map((source) => (
                  <button
                    key={source.id}
                    className={`library-row ${selected === source.id ? 'selected' : ''}`}
                    aria-label={`Preview ${source.title}`}
                    aria-pressed={selected === source.id}
                    onClick={() => setSelected(source.id)}
                  >
                    <span className="document-name">
                      <span className={`file-icon type-${source.source_type}`}>
                        <Icon name="sources" />
                      </span>
                      <span>
                        <strong>{source.title}</strong>
                        <small>{sourceNames[source.source_type]}</small>
                      </span>
                    </span>
                    <span className="captured-date">{dateLabel(source.captured_at)}</span>
                    <StatusBadge status={source.processing_status} />
                  </button>
                ))}
              </div>
              <Pagination offset={offset} total={sources.data.total} change={setOffset} />
            </>
          ) : (
            <Empty
              title={
                collectionId || collection
                  ? 'No documents in this collection'
                  : type
                    ? 'No documents of this type'
                    : 'Make room for what matters.'
              }
            >
              {collectionId || collection
                ? 'Open a document in Library and select this collection in its preview.'
                : 'Import a document or write a note. ECHO will prepare it for local search.'}
              <div className="empty-action">
                <button className="button primary" onClick={openImport}>
                  <Icon name="plus" size={18} />
                  Import documents
                </button>
              </div>
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
            close={() => setSelected(undefined)}
          />
        ) : null}
      </div>
    </>
  )
}
export function CollectionsPage(props: Props) {
  const { api, revision, changed } = props
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Collection>()
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<Collection>()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const rows = useGet<Page<Collection>>(
    api,
    `/api/v1/collections?offset=${offset}&limit=30`,
    revision,
  )
  useEffect(() => {
    if (rows.data && !rows.data.items.length && offset) setOffset(Math.max(0, offset - 30))
  }, [rows.data, offset])
  return (
    <>
      <div className="list-toolbar">
        <div>
          {selected ? (
            <button className="text-button" onClick={() => setSelected(undefined)}>
              All collections / <strong>{selected.name}</strong>
            </button>
          ) : (
            <span className="muted">
              Organize by project, topic, or whatever makes sense to you.
            </span>
          )}
        </div>
        <button
          className="button"
          onClick={() => {
            setCreating(true)
            setName('')
            setDescription('')
            setError('')
          }}
        >
          <Icon name="plus" size={16} />
          New collection
        </button>
      </div>
      {selected ? (
        <LibraryPage key={selected.id} {...props} collectionId={selected.id} />
      ) : rows.loading ? (
        <Loading label="Loading collections" />
      ) : rows.error ? (
        <ErrorBox message={rows.error} retry={() => changed()} />
      ) : rows.data?.items.length ? (
        <>
          <div className="collections-grid">
            {rows.data.items.map((c) => (
              <div className="collection-card" key={c.id}>
                <button
                  className="collection-open"
                  onClick={() => setSelected(c)}
                  aria-label={`Open ${c.name}`}
                >
                  <span className="collection-icon">
                    <Icon name="folder" size={28} />
                  </span>
                  <strong>{c.name}</strong>
                  <p>{c.description || 'A place for related documents.'}</p>
                  <span>
                    {c.source_count} document{c.source_count === 1 ? '' : 's'}
                  </span>
                </button>
                <button
                  className="icon-button collection-delete"
                  aria-label={`Delete collection ${c.name}`}
                  onClick={() => setDeleting(c)}
                >
                  <Icon name="trash" size={16} />
                </button>
              </div>
            ))}
          </div>
          <Pagination offset={offset} total={rows.data.total} change={setOffset} />
        </>
      ) : (
        <Empty
          icon="folder"
          title="Give related reading a home."
          action={
            <button
              className="button primary"
              onClick={() => {
                setCreating(true)
                setName('')
                setDescription('')
                setError('')
              }}
            >
              <Icon name="plus" size={16} />
              Create a collection
            </button>
          }
        >
          Group documents by a research topic or project. A document can belong to more than one
          collection.
        </Empty>
      )}
      {creating ? (
        <Modal
          title="New collection"
          close={() => {
            if (!busy) setCreating(false)
          }}
        >
          <form
            className="modal-body form-stack"
            onSubmit={async (e) => {
              e.preventDefault()
              setBusy(true)
              setError('')
              try {
                await api.json('/api/v1/collections', 'POST', {
                  name,
                  description: description || null,
                })
                changed('Collection created. Add documents from their preview.')
                setCreating(false)
              } catch (error) {
                setError(errorText(error))
              } finally {
                setBusy(false)
              }
            }}
          >
            <label>
              Collection name
              <input
                required
                autoFocus
                value={name}
                maxLength={200}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              Description <span className="optional">optional</span>
              <textarea
                rows={3}
                maxLength={2000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            {error ? <ErrorBox message={error} /> : null}
            <div className="dialog-actions">
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => setCreating(false)}
              >
                Cancel
              </button>
              <button className="button primary" disabled={busy || !name.trim()}>
                {busy ? 'Creating…' : 'Create collection'}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
      {deleting ? (
        <Confirm
          title="Delete this collection?"
          label="Delete collection"
          description="The collection will be removed. Its documents stay in your library."
          close={() => setDeleting(undefined)}
          action={async () => {
            await api.request(`/api/v1/collections/${deleting.id}`, { method: 'DELETE' })
            changed('Collection deleted. Documents were kept.')
            if (selected?.id === deleting.id) setSelected(undefined)
          }}
        />
      ) : null}
    </>
  )
}
