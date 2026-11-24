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

function requestError(
  status: number,
  body: { detail?: string; error?: { code?: string; message?: string } } | null,
) {
  if (status === 403 && body?.detail === 'Origin not allowed')
    return new ApiError(
      403,
      'origin_not_allowed',
      'This dashboard address is not allowed by the local server. Open ECHO from the address shown in its terminal, or check ECHO_ALLOWED_ORIGINS in frontend/README.md.',
    )
  return new ApiError(
    status,
    body?.error?.code ?? 'request_failed',
    body?.error?.message ??
      (status === 401
        ? 'The local connection expired. Try again.'
        : 'The request could not be completed. Check the local server and try again.'),
  )
}

/** The dashboard obtains its session automatically and keeps it in memory. */
export class Api {
  private pending = new Set<AbortController>()
  private lifetime = new AbortController()
  private token = ''
  private connecting?: Promise<void>
  dispose() {
    this.lifetime.abort()
    this.token = ''
    this.pending.forEach((c) => c.abort())
    this.pending.clear()
  }
  start(): Promise<void> {
    this.lifetime.signal.throwIfAborted()
    if (this.token) return Promise.resolve()
    if (!this.connecting)
      this.connecting = this.openSession().finally(() => {
        this.connecting = undefined
      })
    return this.connecting
  }
  private async openSession() {
    try {
      const response = await fetch('/session/open', {
        method: 'POST',
        mode: 'same-origin',
        credentials: 'omit',
        redirect: 'error',
        cache: 'no-store',
        headers: { 'X-Echo-Dashboard': '1' },
        signal: this.lifetime.signal,
      })
      const body = await response.json().catch(() => null)
      if (!response.ok) throw requestError(response.status, body)
      if (typeof body?.session !== 'string' || !/^[A-Za-z0-9_-]{43,128}$/.test(body.session))
        throw new ApiError(
          response.status,
          'invalid_session',
          'The local server returned an invalid session. Restart ECHO and try again.',
        )
      this.lifetime.signal.throwIfAborted()
      this.token = body.session
    } catch (error) {
      if (error instanceof ApiError || this.lifetime.signal.aborted) throw error
      throw new ApiError(
        0,
        'connection_failed',
        'Cannot reach ECHO. Start the local server and try again.',
      )
    }
  }
  async request<T>(path: string, options: RequestInit = {}, binary = false): Promise<T> {
    this.lifetime.signal.throwIfAborted()
    if (!path.startsWith('/api/v1/')) throw new Error('Invalid API path')
    const controller = new AbortController()
    this.pending.add(controller)
    const abort = () => controller.abort()
    options.signal?.addEventListener('abort', abort, { once: true })
    if (options.signal?.aborted) controller.abort()
    try {
      const send = (token: string) => {
        controller.signal.throwIfAborted()
        const headers = new Headers(options.headers)
        headers.set('Authorization', `Bearer ${token}`)
        return fetch(path, {
          ...options,
          headers,
          signal: controller.signal,
          cache: 'no-store',
          credentials: 'omit',
          redirect: 'error',
          referrerPolicy: 'no-referrer',
        })
      }
      await this.start()
      const sentToken = this.token
      let response = await send(sentToken)
      if (response.status === 401) {
        // The server rejects a stale session before the route reads or changes data.
        await response.body?.cancel()
        if (this.token === sentToken) this.token = ''
        await this.start()
        response = await send(this.token)
      }
      const body =
        response.ok && binary ? await response.blob() : await response.json().catch(() => null)
      if (!response.ok) throw requestError(response.status, body)
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
