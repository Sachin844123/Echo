import { useEffect, useMemo, useRef, useState } from 'react'
import { Api, errorText, useCollections } from './api'
import { Empty, ErrorBox, HighlightedText, Icon, Loading } from './components'
import { PreviewPanel } from './PreviewPanel'
import { dateLabel, modes, sourceNames } from './types'
import type { IndexStatus, Mode, SearchHit, SearchResponse } from './types'

export function SearchPage({
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
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<Mode>('hybrid')
  const [type, setType] = useState('')
  const [collection, setCollection] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [contextType, setContextType] = useState('')
  const [contextCollection, setContextCollection] = useState('')
  const [correctSpelling, setCorrectSpelling] = useState<boolean>()
  const [response, setResponse] = useState<SearchResponse>()
  const [submitted, setSubmitted] = useState('')
  const [selected, setSelected] = useState<SearchHit>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const active = useRef<AbortController | null>(null)
  const previewTrigger = useRef<HTMLButtonElement>(null)
  const effectiveQuery = response?.query_analysis?.effective_query ?? submitted
  const highlightWords = useMemo(
    () => new Set(effectiveQuery.toLocaleLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? []),
    [effectiveQuery],
  )
  const collections = useCollections(api, revision)
  const previousRevision = useRef(revision)
  useEffect(() => () => active.current?.abort(), [])
  useEffect(() => {
    if (previousRevision.current !== revision) {
      previousRevision.current = revision
      active.current?.abort()
      setResponse(undefined)
      setBusy(false)
      setSubmitted('')
    }
  }, [revision])
  const modified = () => {
    active.current?.abort()
    setBusy(false)
    setResponse(undefined)
    setSubmitted('')
    setSelected(undefined)
    setError('')
  }
  async function search() {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setError('')
    setSelected(undefined)
    setResponse(undefined)
    if (!query.trim()) return
    if (from && to && from > to) {
      setError('The start date must be on or before the end date.')
      return
    }
    setBusy(true)
    setSubmitted(query.trim())
    try {
      const result = await api.json<SearchResponse>(
        '/api/v1/search',
        'POST',
        {
          query: query.trim(),
          mode,
          correct_spelling: correctSpelling,
          limit: 10,
          source_types: mode === 'visual' ? ['image'] : type ? [type] : [],
          collection_id: collection ? Number(collection) : null,
          captured_from: from ? new Date(`${from}T00:00:00`).toISOString() : null,
          captured_to: to ? new Date(`${to}T23:59:59.999`).toISOString() : null,
          context: {
            source_types: contextType ? [contextType] : [],
            collection_id: contextCollection ? Number(contextCollection) : null,
          },
        },
        controller.signal,
      )
      if (!controller.signal.aborted) setResponse(result)
    } catch (error) {
      if (!controller.signal.aborted) setError(errorText(error))
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  return (
    <>
      <form
        className="search-form"
        onSubmit={(e) => {
          e.preventDefault()
          void search()
        }}
      >
        <div className="search-input-row">
          <Icon name="search" size={24} />
          <label className="sr-only" htmlFor="memory-query">
            What do you remember?
          </label>
          <input
            id="memory-query"
            placeholder="A phrase, an idea, a detail…"
            value={query}
            maxLength={2000}
            onChange={(e) => {
              modified()
              setQuery(e.target.value)
            }}
            autoComplete="off"
          />
          <button className="button primary" disabled={busy || !query.trim()}>
            {busy ? 'Searching…' : 'Search'}
            <Icon name="arrow" size={18} />
          </button>
        </div>
        <div className="search-options">
          <div className="mode-tabs" role="group" aria-label="Search method">
            {modes.map((m) => (
              <button
                type="button"
                key={m.value}
                aria-pressed={mode === m.value}
                title={m.description}
                onClick={() => {
                  modified()
                  setMode(m.value)
                }}
              >
                {m.label}
              </button>
            ))}
          </div>
          <span className="search-scope">
            <Icon name="library" size={14} />
            Your local library
          </span>
        </div>
        <div className="filters">
          <label>
            File type
            <select
              aria-label="File type"
              value={mode === 'visual' ? 'image' : type}
              disabled={mode === 'visual'}
              onChange={(e) => {
                modified()
                setType(e.target.value)
              }}
            >
              <option value="">All types</option>
              {Object.entries(sourceNames).map(([v, name]) => (
                <option key={v} value={v}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Collection
            <select
              aria-label="Collection"
              value={collection}
              disabled={collections.loading || !!collections.error}
              onChange={(e) => {
                modified()
                setCollection(e.target.value)
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
          <label>
            Captured from
            <input
              type="date"
              value={from}
              onChange={(e) => {
                modified()
                setFrom(e.target.value)
              }}
            />
          </label>
          <label>
            Captured to
            <input
              type="date"
              value={to}
              onChange={(e) => {
                modified()
                setTo(e.target.value)
              }}
            />
          </label>
          {type || collection || from || to ? (
            <button
              type="button"
              className="text-button clear-filters"
              onClick={() => {
                modified()
                setType('')
                setCollection('')
                setFrom('')
                setTo('')
              }}
            >
              Clear filters
            </button>
          ) : null}
        </div>
        {mode === 'hybrid_contextual' ? (
          <div className="context-options">
            <div>
              <strong>A little more context</strong>
              <p>Optional clues change ranking, without excluding other sources.</p>
            </div>
            <label>
              Remembered type
              <select
                aria-label="Remembered type"
                value={contextType}
                onChange={(e) => {
                  modified()
                  setContextType(e.target.value)
                }}
              >
                <option value="">No preference</option>
                {Object.entries(sourceNames).map(([v, name]) => (
                  <option key={v} value={v}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Remembered collection
              <select
                aria-label="Remembered collection"
                value={contextCollection}
                onChange={(e) => {
                  modified()
                  setContextCollection(e.target.value)
                }}
              >
                <option value="">No preference</option>
                {collections.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}
      </form>
      {collections.error ? <ErrorBox message={collections.error} /> : null}
      {mode !== 'visual' ? (
        <label className="checkbox-row search-spelling">
          <input
            type="checkbox"
            checked={correctSpelling ?? status?.spelling_correction ?? true}
            onChange={(e) => {
              modified()
              setCorrectSpelling(e.target.checked)
            }}
          />
          Correct likely spelling mistakes using my library
        </label>
      ) : (
        <div className="info-banner">
          Describe an imported image, for example “a red car”. To find words inside an image, use
          Keywords or Hybrid with the Image filter.
          {status?.visual && !status.visual.available
            ? ' The local visual model is unavailable; check Settings.'
            : ''}
        </div>
      )}
      {status && !status.semantic_available && mode !== 'keyword' && mode !== 'visual' ? (
        <div className="info-banner">
          <Icon name="info" />
          <span>
            Meaning-based search is unavailable. Check the local model in Settings or search by
            keywords.
          </span>
          <button
            className="button small"
            onClick={() => {
              modified()
              setMode('keyword')
            }}
          >
            Use keywords
          </button>
        </div>
      ) : null}
      {error ? <ErrorBox message={error} retry={() => void search()} /> : null}
      <div className={`document-workspace ${selected ? 'has-preview' : ''}`}>
        <section className="results" aria-label="Search results" aria-busy={busy}>
          {busy ? (
            <Loading label="Searching your library" />
          ) : response ? (
            <>
              <div className="section-bar" role="status">
                <h2>
                  {response.results.length} result{response.results.length === 1 ? '' : 's'}
                </h2>
                <span>
                  {mode === 'visual'
                    ? 'Imported images matched by appearance'
                    : 'Best passage from each document'}
                </span>
              </div>
              {response.query_analysis?.corrections.length ? (
                <div className="info-banner">
                  Searching for: {response.query_analysis.effective_query}. Turn off spelling
                  correction to search your exact wording.
                </div>
              ) : null}
              {response.candidate_scan_truncated ? (
                <div className="info-banner">
                  The candidate scan limit was reached. Try a more specific query or a collection
                  filter.
                </div>
              ) : null}
              {response.indexing_incomplete ? (
                <div className="info-banner">
                  Some documents are still processing or need attention. Results may be incomplete.
                </div>
              ) : null}
              {response.results.length ? (
                <div className="result-list">
                  {response.results.map((hit) => (
                    <button
                      className={`result-row ${selected?.source_id === hit.source_id ? 'selected' : ''}`}
                      key={hit.source_id}
                      onClick={(event) => {
                        previewTrigger.current = event.currentTarget
                        setSelected(hit)
                      }}
                      aria-label={`Preview ${hit.title}`}
                      aria-describedby={`result-meta-${hit.source_id}`}
                      aria-pressed={selected?.source_id === hit.source_id}
                    >
                      <span className={`file-icon type-${hit.source_type}`}>
                        <Icon name={hit.source_type === 'image' ? 'image' : 'sources'} size={18} />
                      </span>
                      <span className="result-body">
                        <strong>{hit.title}</strong>
                        <span className="row-meta" id={`result-meta-${hit.source_id}`}>
                          {sourceNames[hit.source_type]}
                          <span aria-hidden="true">·</span>
                          {dateLabel(hit.captured_at)}
                          {mode !== 'visual' && hit.page_number ? (
                            <span>Page {hit.page_number}</span>
                          ) : null}
                        </span>
                        {mode !== 'visual' ? (
                          <span className="excerpt">
                            <HighlightedText text={hit.excerpt} words={highlightWords} />
                          </span>
                        ) : null}
                        {hit.heading ? <span className="row-heading">{hit.heading}</span> : null}
                      </span>
                      <Icon name="arrow" size={17} />
                    </button>
                  ))}
                </div>
              ) : (
                <Empty icon="search" title="No matching documents">
                  Try fewer words, a related idea, or remove a filter. ECHO only searches content
                  already in your library.
                </Empty>
              )}
            </>
          ) : (
            <div className="search-rest">
              <div className="section-bar">
                <h2>Your memory is the starting point.</h2>
                <span>No search history saved</span>
              </div>
              <div className="search-guidance">
                <div>
                  <Icon name="search" size={23} />
                  <h3>A few words</h3>
                  <p>Use a phrase, a name, or a detail that stayed with you.</p>
                </div>
                <div>
                  <Icon name="sources" size={23} />
                  <h3>The idea behind it</h3>
                  <p>Describe the subject in your own words with Hybrid or Meaning.</p>
                </div>
                <div>
                  <Icon name="folder" size={23} />
                  <h3>A place to look</h3>
                  <p>Narrow the search by file type, collection, or capture date.</p>
                </div>
              </div>
              <div className="library-invitation">
                <span className="empty-icon">
                  <Icon name="library" size={26} />
                </span>
                <div>
                  <h3>Build a library worth returning to.</h3>
                  <p>Import your papers, documents and notes to make them searchable.</p>
                </div>
                <button className="button" onClick={openImport}>
                  Import documents
                  <Icon name="plus" size={16} />
                </button>
              </div>
            </div>
          )}
        </section>
        {selected ? (
          <PreviewPanel
            key={`${selected.source_id}-${selected.chunk_id}`}
            api={api}
            sourceId={selected.source_id}
            hit={mode === 'visual' ? undefined : selected}
            highlightWords={highlightWords}
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
