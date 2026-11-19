export type SourceType = 'pdf' | 'txt' | 'markdown' | 'docx' | 'note'
export type Mode = 'keyword' | 'semantic' | 'hybrid' | 'hybrid_contextual'
export type View = 'Search' | 'Library' | 'Collections' | 'Sources' | 'Settings'
export interface Source {
  id: number
  source_type: SourceType
  title: string
  mime_type: string
  processing_status: string
  captured_at: string
  indexed_at: string | null
  created_at: string
  updated_at: string
  collection_ids?: number[]
}
export interface Collection {
  id: number
  name: string
  description: string | null
  source_count: number
}
export interface Page<T> {
  items: T[]
  total: number
}
export interface IndexStatus {
  semantic_available: boolean
  model_name: string
  error: string | null
  vector_count: number
  sources_by_status: Record<string, number>
  deletions_pending: number
  indexing_incomplete: boolean
}
export interface Job {
  id: number
  source_id: number
  title: string
  source_type: SourceType
  status: string
  stage: string
  attempts: number
  retryable: boolean
  error: { code: string; message: string } | null
}
export interface SearchHit {
  source_id: number
  chunk_id: number
  title: string
  source_type: SourceType
  captured_at: string
  excerpt: string
  page_number: number | null
  heading: string | null
  start_offset: number
  end_offset: number
  score: number
  rerank_signals?: Record<string, number>
}
export interface SearchResponse {
  mode: Mode
  results: SearchHit[]
  indexing_incomplete: boolean
}
export interface Preview {
  document_id: number
  text: string
  offset: number
  content_length: number
  has_more: boolean
}
export interface AppSettings {
  version: string
  search_history_enabled: false
  max_upload_bytes: number
  supported_types: SourceType[]
  retrieval: {
    chunk_tokens: number
    chunk_overlap: number
    candidate_pool: number
    result_limit: number
    rrf_k: number
    embedding_model_name: string
    embedding_batch_size: number
  }
  rerank_weights: Record<string, number>
}
export const sourceNames: Record<SourceType, string> = {
  pdf: 'PDF',
  txt: 'Text',
  markdown: 'Markdown',
  docx: 'Word',
  note: 'Note',
}
export const modes: { value: Mode; label: string; description: string }[] = [
  {
    value: 'hybrid',
    label: 'Hybrid',
    description: 'Combines keyword and meaning-based retrieval.',
  },
  {
    value: 'keyword',
    label: 'Keywords',
    description: 'Finds matching words in your imported documents.',
  },
  {
    value: 'semantic',
    label: 'Meaning',
    description: 'Finds related meaning using the local embedding model.',
  },
  {
    value: 'hybrid_contextual',
    label: 'Hybrid + context',
    description: 'Also considers titles, headings and optional remembered context.',
  },
]
export function dateLabel(date: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(date))
}
