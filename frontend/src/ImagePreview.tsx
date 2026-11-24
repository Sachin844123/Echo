import { useEffect, useState } from 'react'
import { Api, errorText } from './api'
import { ErrorBox, Loading } from './components'

/** Authenticated fetch: bearer tokens never appear in an image URL or storage. */
export function ImagePreview({
  api,
  sourceId,
  title,
}: {
  api: Api
  sourceId: number
  title: string
}) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    let objectUrl = ''
    setUrl('')
    setError('')
    void api
      .request<Blob>(`/api/v1/sources/${sourceId}/image`, { signal: controller.signal }, true)
      .then((blob) => {
        if (!controller.signal.aborted) {
          objectUrl = URL.createObjectURL(blob)
          setUrl(objectUrl)
        }
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(errorText(failure))
      })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [api, sourceId])
  return error ? (
    <ErrorBox message={error} />
  ) : url ? (
    <img className="image-preview" src={url} alt={title} />
  ) : (
    <Loading label="Loading image" />
  )
}
