export interface Week {
  week_start: string
  week_end: string
  n_posts: number
}

export interface Status {
  subreddit: string | null
  weeks: Week[]
  can_pull_live: boolean
  models_available: string[]
  models: Record<string, { label: string; vendor: string }>
}

export interface Doc {
  id: number
  created_at: string
  mode: 'rag' | 'baseline'
  model_key: string
  week_start: string
  subreddit: string
  content_md: string
  retrieved_chunk_ids: string[] | null
  retrieval_mode: string | null
  latency_ms: number
  input_tokens: number
  output_tokens: number
}

export interface JudgeCriteria {
  specificity: number
  evidence: number
  temporal_grounding: number
  usefulness: number
}

export interface Judge {
  scores: { a: JudgeCriteria; b: JudgeCriteria } | null
  winner: 'a' | 'b' | 'tie'
  rationale: string
}

export interface Comparison {
  id: number
  kind: string
  created_at: string
  doc_a: Doc
  doc_b: Doc
  judge: Judge | null
  extra: { chunk_overlap_jaccard: number | null } | null
}

export interface EmbeddingPoint {
  id: string
  path: string
  heading: string
  x: number
  y: number
  title: string | null
  week_start: string | null
  retrieved_count: number
}

export interface Stats {
  total_retrievals: number
  chunks_total: number
  chunks_never_retrieved: number
  top_chunks: {
    chunk_id: string
    retrieved_count: number
    last_retrieved_at: string
    title: string | null
    heading_path: string
    snippet: string
  }[]
  per_model: {
    model_key: string
    docs: number
    avg_latency_ms: number
    avg_input_tokens: number
    avg_output_tokens: number
  }[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      detail = (await resp.json()).detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return resp.json()
}

export const api = {
  status: () => request<Status>('/api/status'),
  documents: (weekStart?: string) =>
    request<Doc[]>(
      `/api/documents${weekStart ? `?week_start=${weekStart}` : ''}`,
    ),
  generate: (body: {
    week_start: string
    mode: 'rag' | 'baseline'
    model_key: string
  }) =>
    request<Doc>('/api/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  compare: (body: {
    week_start: string
    kind: string
    model_a: string
    model_b?: string
    retrieval_a?: string
    retrieval_b?: string
  }) =>
    request<Comparison>('/api/compare', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  latestComparison: (kind: string) =>
    request<Comparison>(`/api/comparisons/latest?kind=${kind}`),
  embeddings: () =>
    request<{ embedding_model: string | null; points: EmbeddingPoint[] }>(
      '/api/embeddings',
    ),
  stats: () => request<Stats>('/api/stats'),
  ingestWeek: () =>
    request<{ report: Record<string, number>; weeks: Week[] }>(
      '/api/ingest/week',
      { method: 'POST' },
    ),
}
