import { useMemo, useState, useSyncExternalStore } from 'react'
import { modes } from './types'
import type { Mode } from './types'

const key = 'echo.recent-searches.v1'
const changed = 'echo:recent-searches'
const limit = 12

export type RecentSearch = { query: string; mode: Mode; searchedAt: string }

function snapshot() {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function decode(raw: string | null): RecentSearch[] | null {
  if (raw === null) return null
  try {
    const value: unknown = JSON.parse(raw)
    if (!Array.isArray(value)) return null
    return value.slice(0, limit).filter((entry): entry is RecentSearch => {
      return (
        typeof entry?.query === 'string' &&
        entry.query.trim().length > 0 &&
        entry.query.length <= 2000 &&
        modes.some((mode) => mode.value === entry.mode) &&
        typeof entry.searchedAt === 'string' &&
        Number.isFinite(Date.parse(entry.searchedAt))
      )
    })
  } catch {
    return null
  }
}

function subscribe(update: () => void) {
  function onStorage(event: StorageEvent) {
    if (event.key === key || event.key === null) update()
  }
  addEventListener('storage', onStorage)
  addEventListener(changed, update)
  return () => {
    removeEventListener('storage', onStorage)
    removeEventListener(changed, update)
  }
}

export function useSearchHistory() {
  const raw = useSyncExternalStore(subscribe, snapshot)
  const entries = useMemo(() => decode(raw), [raw])
  const [error, setError] = useState('')

  function save(next: RecentSearch[] | null) {
    try {
      if (next === null) localStorage.removeItem(key)
      else localStorage.setItem(key, JSON.stringify(next))
      setError('')
      dispatchEvent(new Event(changed))
    } catch {
      setError('This browser could not update your recent searches.')
    }
  }

  return {
    entries,
    error,
    setEnabled(enabled: boolean) {
      save(enabled ? (decode(snapshot()) ?? []) : null)
    },
    clear() {
      if (decode(snapshot()) !== null) save([])
    },
    remove(search: RecentSearch) {
      const current = decode(snapshot())
      if (current) save(current.filter((entry) => !sameSearch(entry, search)))
    },
    remember(query: string, mode: Mode) {
      const current = decode(snapshot())
      if (!current) return
      const search = { query, mode, searchedAt: new Date().toISOString() }
      save([search, ...current.filter((entry) => !sameSearch(entry, search))].slice(0, limit))
    },
  }
}

function sameSearch(a: RecentSearch, b: RecentSearch) {
  return a.query === b.query && a.mode === b.mode
}

export type SearchHistory = ReturnType<typeof useSearchHistory>
