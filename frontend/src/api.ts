export interface Week {
  week_start: string
  week_end: string
  n_posts: number
  n_chunks: number
}

export interface ActivityDay {
  date: string
  n_posts: number
}

export interface IngestReport {
  posts: number
  comments?: number
  chunks_total: number
  chunks_new: number
  comment_fetches?: number
  fetch_s?: number
  index_s?: number
}

export interface Status {
  subreddit: string | null
  source: string
  ingested_at: string | null
  embedding_model: string | null
  embedding_dim: string | null
  weeks: Week[]
  activity: ActivityDay[]
  week_totals: { n_posts: number; n_comments: number } | null
  chunks_total: number
  last_ingest: IngestReport | null
  hybrid: boolean
  can_pull_live: boolean
  models_available: string[]
  models: Record<string, { label: string; vendor: string }>
}

export interface ReportTopic {
  name: string
  summary: string
  share_pct: number | null
  threads: number | null
}

export interface ReportPrediction {
  title: string
  confidence: number
  rationale: string
  signals: string[]
}

export interface ReportReview {
  prediction: string
  grade: 'hit' | 'partial' | 'miss'
  evidence: string
}

export interface Report {
  headline: string
  lede: string
  topics: ReportTopic[]
  standouts: string[]
  prediction_review: ReportReview[] | null
  predictions: ReportPrediction[]
}

export interface Doc {
  id: number
  created_at: string
  mode: 'rag' | 'baseline'
  model_key: string
  week_start: string
  subreddit: string
  content_md: string
  report_json: Report | null
  retrieved_chunk_ids: string[] | null
  retrieval_mode: string | null
  latency_ms: number
  input_tokens: number
  output_tokens: number
  cost_usd: number | null
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
  cluster?: number
  title: string | null
  snippet: string | null
  week_start: string | null
  retrieved_count: number
}

export interface ClusterInfo {
  id: number
  label: string
  n: number
}

export interface Embeddings {
  embedding_model: string | null
  method?: 'pca' | 'umap'
  clusters?: ClusterInfo[]
  points: EmbeddingPoint[]
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
    avg_cost_usd: number | null
  }[]
}

export type StageKey = 'crawl' | 'reduce' | 'embed' | 'retrieve' | 'write'

export interface StageEvent {
  stage: StageKey
  status?: 'cached' | 'start' | 'end'
  detail?: string
  chunks?: number
  mode?: string
  retrieval_ms?: number
  latency_ms?: number
  model_key?: string
  output_tokens?: number
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
  compare: (body: {
    week_start: string
    kind: string
    model_a: string
    model_b?: string
  }) =>
    request<Comparison>('/api/compare', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  latestComparison: (kind: string) =>
    request<Comparison>(`/api/comparisons/latest?kind=${kind}`),
  embeddings: () => request<Embeddings>('/api/embeddings'),
  stats: () => request<Stats>('/api/stats'),
  ingestWeek: () =>
    request<{ report: IngestReport; weeks: Week[] }>('/api/ingest/week', {
      method: 'POST',
    }),
}

/** SSE generation. Calls back per stage event; resolves with the finished
 * Doc or rejects on an error event / broken stream. */
export function generateStream(
  params: { week_start: string; model_key: string; mode?: 'rag' | 'baseline' },
  onStage: (ev: StageEvent) => void,
): Promise<Doc> {
  const qs = new URLSearchParams({
    week_start: params.week_start,
    model_key: params.model_key,
    mode: params.mode ?? 'rag',
  })
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/generate/stream?${qs}`)
    // Close before settling and never act twice: EventSource auto-reconnects
    // on any connection close it didn't initiate, which would re-run the
    // whole (paid) generation server-side.
    let settled = false
    const settle = (fn: () => void) => {
      if (settled) return
      settled = true
      es.close()
      fn()
    }
    es.addEventListener('stage', (e) => {
      if (!settled) onStage(JSON.parse((e as MessageEvent).data))
    })
    es.addEventListener('done', (e) => {
      const data = (e as MessageEvent).data
      settle(() => resolve(JSON.parse(data)))
    })
    es.addEventListener('error', (e) => {
      const data = (e as MessageEvent).data
      settle(() =>
        reject(new Error(data ? JSON.parse(data).detail : 'stream failed')),
      )
    })
  })
}
