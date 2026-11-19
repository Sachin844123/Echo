import { useEffect, useState } from 'react'
import type { Collection, Page } from './types'

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

/** A session is memory-only. Disposal cancels all reads and prevents later writes. */
export class Api {
  private pending = new Set<AbortController>()
  private disposed = false
  constructor(
    private token: string,
    private unauthorized: () => void,
  ) {}
  dispose() {
    this.disposed = true
    this.token = ''
    this.pending.forEach((c) => c.abort())
    this.pending.clear()
  }
  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    if (this.disposed) throw new DOMException('Session closed', 'AbortError')
    if (!path.startsWith('/api/v1/')) throw new Error('Invalid API path')
    const controller = new AbortController()
    this.pending.add(controller)
    const abort = () => controller.abort()
    options.signal?.addEventListener('abort', abort, { once: true })
    if (options.signal?.aborted) controller.abort()
    try {
      const response = await fetch(path, {
        ...options,
        signal: controller.signal,
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
        referrerPolicy: 'no-referrer',
        headers: { ...options.headers, Authorization: `Bearer ${this.token}` },
      })
      const body = await response.json().catch(() => null)
      if (response.status === 401) this.unauthorized()
      if (response.status === 403 && body?.detail === 'Origin not allowed')
        throw new ApiError(
          403,
          'origin_not_allowed',
          'This dashboard address is not allowed by the local server. Open http://127.0.0.1:8000/, or restart the backend with this exact development address in ECHO_ALLOWED_ORIGINS (see frontend/README.md).',
        )
      if (!response.ok)
        throw new ApiError(
          response.status,
          body?.error?.code ?? 'request_failed',
          body?.error?.message ??
            (response.status === 401
              ? 'Session token was not accepted. Connect again.'
              : 'The request could not be completed. Check the local server and try again.'),
        )
      return body as T
    } catch (error) {
      if (
        error instanceof ApiError ||
        (error instanceof DOMException && error.name === 'AbortError')
      )
        throw error
      throw new ApiError(
        0,
        'connection_failed',
        'Cannot reach ECHO. Check that the local server is running, then retry.',
      )
    } finally {
      this.pending.delete(controller)
      options.signal?.removeEventListener('abort', abort)
    }
  }
  json<T>(path: string, method: string, body: unknown, signal?: AbortSignal) {
    return this.request<T>(path, {
      method,
      body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json' },
      signal,
    })
  }
}
export function errorText(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : 'This action could not be completed. Try again.'
}

export function useGet<T>(api: Api, path: string | null, revision = 0) {
  const [state, setState] = useState<{ data?: T; loading: boolean; error?: string }>({
    loading: true,
  })
  useEffect(() => {
    const controller = new AbortController()
    setState({ loading: !!path })
    if (path)
      api
        .request<T>(path, { signal: controller.signal })
        .then((data) => {
          if (!controller.signal.aborted) setState({ data, loading: false })
        })
        .catch((error) => {
          if (!controller.signal.aborted) setState({ error: errorText(error), loading: false })
        })
    return () => controller.abort()
  }, [api, path, revision])
  return state
}

export function useCollections(api: Api, revision: number) {
  const [state, setState] = useState<{ data?: Collection[]; loading: boolean; error?: string }>({
    loading: true,
  })
  useEffect(() => {
    const controller = new AbortController()
    setState({ loading: true })
    async function load() {
      const items: Collection[] = []
      let total = 1
      for (let offset = 0; offset < total; offset += 100) {
        const page = await api.request<Page<Collection>>(
          `/api/v1/collections?limit=100&offset=${offset}`,
          { signal: controller.signal },
        )
        items.push(...page.items)
        total = page.total
        if (!page.items.length) break
      }
      if (!controller.signal.aborted) setState({ data: items, loading: false })
    }
    void load().catch((error) => {
      if (!controller.signal.aborted) setState({ loading: false, error: errorText(error) })
    })
    return () => controller.abort()
  }, [api, revision])
  return state
}
