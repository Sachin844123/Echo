import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'

const paths: Record<string, ReactNode> = {
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  library: (
    <>
      <path d="M4 4h4v16H4zM11 4h4v16h-4zM18 5l3 14" />
    </>
  ),
  folder: <path d="M3 7V5h6l2 3h10v12H3z" />,
  activity: <path d="M3 12h4l3-7 4 14 3-7h4" />,
  history: <path d="M3 10a9 9 0 1 1 2 8M3 5v5h5m4-3v5l3 2" />,
  storage: <path d="M3 14 6 5h12l3 9v5H3zm0 0h18m-5 2.5h1m-4 0h.1" />,
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="9" r="1.5" />
      <path d="m4 17 5-4 3 2 4-5 5 6" />
    </>
  ),
  sources: (
    <>
      <path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h6" />
    </>
  ),
  settings: (
    <>
      <path d="M4 7h16M4 17h16" />
      <circle cx="9" cy="7" r="3" />
      <circle cx="15" cy="17" r="3" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  lock: (
    <>
      <rect x="5" y="10" width="14" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V3m-4 4 4-4 4 4M4 15v6h16v-6" />
    </>
  ),
  check: <path d="m5 12 4 4L20 5" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1 1M18 18l1 1M5 19l1-1M18 6l1-1" />
    </>
  ),
  moon: <path d="M20 15A8 8 0 0 1 9 4a8 8 0 1 0 11 11Z" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6M12 7v1" />
    </>
  ),
  trash: (
    <>
      <path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5" />
    </>
  ),
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
}
export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.sources}
    </svg>
  )
}
export function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span>
        ECHO<span className="brand-caption">Document workspace</span>
      </span>
    </div>
  )
}
export function ErrorBox({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <Icon name="info" />
      <span>{message}</span>
      {retry ? (
        <button className="button small" onClick={retry}>
          Retry
        </button>
      ) : null}
    </div>
  )
}
export function Empty({
  icon = 'library',
  title,
  children,
  action,
}: {
  icon?: string
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon name={icon} size={28} />
      </div>
      <h2>{title}</h2>
      <div className="empty-copy">{children}</div>
      {action}
    </div>
  )
}
export function Loading({ label = 'Loading documents' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="loading-dot" aria-hidden="true" />
      {label}…
    </div>
  )
}
export function HighlightedText({ text, words }: { text: string; words: ReadonlySet<string> }) {
  return text
    .split(/([\p{L}\p{N}_]+)/gu)
    .map((piece, index) =>
      words.has(piece.toLocaleLowerCase()) ? <mark key={index}>{piece}</mark> : piece,
    )
}
export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`status-badge status-${status}`}>
      <span aria-hidden="true" />
      {(
        {
          indexed: 'Indexed',
          succeeded: 'Complete',
          pending: 'Queued',
          processing: 'Processing',
          running: 'Processing',
          failed: 'Needs attention',
        } as Record<string, string>
      )[status] ?? status}
    </span>
  )
}
export function Modal({
  title,
  close,
  children,
}: {
  title: string
  close: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()
  useEffect(() => {
    const dialog = ref.current!
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialog.showModal()
    return () => {
      dialog.close()
      if (previous?.isConnected) previous.focus()
    }
  }, [])
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={id}
      onCancel={(event) => {
        event.preventDefault()
        close()
      }}
    >
      <header className="modal-header">
        <h2 id={id}>{title}</h2>
        <button className="icon-button" onClick={close} aria-label="Close dialog">
          <Icon name="close" />
        </button>
      </header>
      {children}
    </dialog>
  )
}
export function Confirm({
  title,
  description,
  label,
  action,
  close,
  phrase,
}: {
  title: string
  description: string
  label: string
  action: () => Promise<void>
  close: () => void
  phrase?: string
}) {
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return (
    <Modal
      title={title}
      close={() => {
        if (!busy) close()
      }}
    >
      <form
        className="modal-body"
        onSubmit={async (e) => {
          e.preventDefault()
          if (busy || (phrase && typed !== phrase)) return
          setBusy(true)
          setError('')
          try {
            await action()
            close()
          } catch (e) {
            setError(e instanceof Error ? e.message : 'The action failed. Try again.')
            setBusy(false)
          }
        }}
      >
        <p>{description}</p>
        {phrase ? (
          <label>
            Type {phrase} to confirm
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </label>
        ) : null}
        {error ? <ErrorBox message={error} /> : null}
        <footer className="dialog-actions">
          <button type="button" className="button" onClick={close} disabled={busy}>
            Cancel
          </button>
          <button className="button danger" disabled={busy || (!!phrase && typed !== phrase)}>
            {busy ? 'Working…' : label}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
export function Pagination({
  offset,
  total,
  size = 30,
  change,
}: {
  offset: number
  total: number
  size?: number
  change: (offset: number) => void
}) {
  if (!total) return null
  return (
    <div className="pagination">
      <span>
        {offset + 1}–{Math.min(offset + size, total)} of {total}
      </span>
      <div className="flex gap-2">
        <button
          className="button small"
          disabled={!offset}
          onClick={() => change(Math.max(0, offset - size))}
        >
          Previous
        </button>
        <button
          className="button small"
          disabled={offset + size >= total}
          onClick={() => change(offset + size)}
        >
          Next
        </button>
      </div>
    </div>
  )
}
