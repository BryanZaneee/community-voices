// Adapter layer: real API responses -> the design's view-model shapes.
import type {
  ClusterInfo,
  Comparison,
  Doc,
  EmbeddingPoint,
  Embeddings,
} from './api'

// Topic/cluster palette from the design tokens (neutral gray = long tail).
export const CLUSTER_COLORS = [
  '#7A8B22', '#5B6770', '#B08C1E', '#2E7D5B', '#A65A2E', '#9A9A90',
]

export const ACCENT = '#7A8B22'

export const fmt = (n: number | null | undefined): string =>
  n == null ? '—' : n.toLocaleString('en-US')

export const fmtSecs = (ms: number | null | undefined): string =>
  ms == null ? '—' : `${(ms / 1000).toFixed(1)}s`

export const fmtUsd = (v: number | null | undefined): string =>
  v == null ? '—' : `$${v.toFixed(3)}`

/** "games@lemmy.world" -> { name: "c/games", instance: "lemmy.world" } */
export function communityIdentity(subreddit: string | null) {
  if (!subreddit) return { name: '—', instance: '', initial: '?' }
  const [name, instance] = subreddit.includes('@')
    ? subreddit.split('@')
    : [subreddit, '']
  const clean = name.replace(/^r\//, '')
  return {
    name: subreddit.includes('@') ? `c/${clean}` : `r/${clean}`,
    instance,
    initial: clean[0]?.toUpperCase() ?? '?',
  }
}

export function weekRange(weekStart: string, weekEnd: string): string {
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
  const s = new Date(weekStart + 'T00:00:00Z')
  const e = new Date(weekEnd + 'T00:00:00Z')
  return `${s.toLocaleDateString('en-US', { ...opts, timeZone: 'UTC' })} – ${e.toLocaleDateString('en-US', { ...opts, timeZone: 'UTC' })}`
}

// ---------------------------------------------------------------- A/B ----

export interface Segment {
  text: string
  cite?: number // grounded claim (cites a retrieved post title)
  vague?: boolean // unverifiable-claim heuristic
}

export interface AbBlock {
  heading?: string
  segs: Segment[]
}

const HEDGES =
  /\b(likely|probably|perhaps|possibly|presumably|generally|typically|often|usually|may have|might have|would have|tend(?:s)? to|it is possible|cannot be confirmed|hard to say|no doubt|as always|commonly)\b/i

/** Split markdown into displayable blocks with grounded/vague segments.
 * Grounded = *italicized post titles* (the RAG prompt's citation format).
 * Vague = sentences that hedge (LLM-only tell). */
export function segmentDoc(md: string, side: 'rag' | 'base'): AbBlock[] {
  const blocks: AbBlock[] = []
  let cite = 0
  for (const raw of md.split(/\n{2,}/)) {
    let block = raw.trim()
    if (!block || block.startsWith('# ')) continue // drop the H1
    if (block.startsWith('##')) {
      // only the first line is the heading; re-process the rest as body text
      const nl = block.indexOf('\n')
      const headingLine = nl === -1 ? block : block.slice(0, nl)
      blocks.push({
        heading: headingLine.replace(/^#+\s*/, '').replace(/\*\*/g, ''),
        segs: [],
      })
      if (nl === -1) continue
      block = block.slice(nl + 1).trim()
      if (!block) continue
    }
    const text = block
      .replace(/^\s*[-*]\s+/gm, '')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/\n+/g, ' ')
    const segs: Segment[] = []
    const pushPlain = (t: string) => {
      if (!t) return
      if (side === 'base') {
        // sentence-level hedge detection
        for (const sentence of t.split(/(?<=[.!?])\s+/)) {
          if (!sentence) continue
          segs.push(
            HEDGES.test(sentence)
              ? { text: sentence + ' ', vague: true }
              : { text: sentence + ' ' },
          )
        }
      } else {
        segs.push({ text: t })
      }
    }
    let last = 0
    for (const match of text.matchAll(/\*([^*\n]+)\*/g)) {
      pushPlain(text.slice(last, match.index))
      if (side === 'rag') {
        cite += 1
        segs.push({ text: match[1], cite })
      } else {
        // an italicized "title" with no retrieval behind it is unverifiable
        segs.push({ text: match[1], vague: true })
      }
      last = (match.index ?? 0) + match[0].length
    }
    pushPlain(text.slice(last))
    if (segs.length) blocks.push({ segs })
  }
  return blocks
}

export const citationCount = (md: string): number =>
  [...md.matchAll(/\*([^*\n]+)\*/g)].filter((m) => !m[0].startsWith('**'))
    .length

export interface MetricRow {
  name: string
  rag: string
  base: string
  win: 'rag' | 'base' | 'even'
}

export function metricRows(comp: Comparison): MetricRow[] {
  const rag = comp.doc_b // rag_vs_baseline: A = baseline, B = RAG
  const base = comp.doc_a
  const rows: MetricRow[] = []
  const lower = (a: number, b: number): 'rag' | 'base' | 'even' =>
    a === b ? 'even' : a < b ? 'rag' : 'base'
  rows.push({
    name: 'Cost / report',
    rag: fmtUsd(rag.cost_usd),
    base: fmtUsd(base.cost_usd),
    win: lower(rag.cost_usd ?? 0, base.cost_usd ?? 0),
  })
  rows.push({
    name: 'Generation time',
    rag: fmtSecs(rag.latency_ms),
    base: fmtSecs(base.latency_ms),
    win: lower(rag.latency_ms, base.latency_ms),
  })
  rows.push({
    name: 'Input tokens',
    rag: fmt(rag.input_tokens),
    base: fmt(base.input_tokens),
    win: lower(rag.input_tokens, base.input_tokens),
  })
  rows.push({
    name: 'Output tokens',
    rag: fmt(rag.output_tokens),
    base: fmt(base.output_tokens),
    win: 'even',
  })
  // baseline has no retrieval, so nothing it writes is a verifiable citation
  const ragCites = citationCount(rag.content_md)
  rows.push({
    name: 'Verifiable citations',
    rag: String(ragCites),
    base: '0',
    win: ragCites > 0 ? 'rag' : 'even',
  })
  rows.push({
    name: 'Chunks retrieved',
    rag: String(rag.retrieved_chunk_ids?.length ?? 0),
    base: '0',
    win: 'rag',
  })
  return rows
}

export const CRITERIA_LABELS: Record<string, { label: string; note: string }> = {
  specificity: {
    label: 'Specificity',
    note: 'concrete posts, names, numbers vs. vague generalities',
  },
  evidence: {
    label: 'Evidence',
    note: 'claims grounded in real cited discussions vs. unsupported',
  },
  temporal_grounding: {
    label: 'Temporal grounding',
    note: 'reflects that specific week vs. timeless filler',
  },
  usefulness: {
    label: 'Usefulness',
    note: 'how informative for someone catching up',
  },
}

// --------------------------------------------------------- embeddings ----

export interface VmCluster extends ClusterInfo {
  color: string
  hits: number
}

export interface VmPoint extends EmbeddingPoint {
  nx: number // normalized [0.03, 0.97]
  ny: number
  color: string
}

export function scatterModel(emb: Embeddings): {
  clusters: VmCluster[]
  points: VmPoint[]
  maxHits: number
} {
  const rawClusters = emb.clusters?.length
    ? emb.clusters
    : [{ id: 0, label: 'all chunks', n: emb.points.length }]
  // biggest cluster gets the accent color, long tail goes gray
  const ordered = [...rawClusters].sort((a, b) => b.n - a.n)
  const colorById = new Map<number, string>()
  ordered.forEach((c, i) =>
    colorById.set(c.id, CLUSTER_COLORS[Math.min(i, CLUSTER_COLORS.length - 1)]),
  )

  const xs = emb.points.map((p) => p.x)
  const ys = emb.points.map((p) => p.y)
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)]
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)]
  const norm = (v: number, lo: number, hi: number) =>
    hi === lo ? 0.5 : 0.03 + (0.94 * (v - lo)) / (hi - lo)

  let maxHits = 1
  const points: VmPoint[] = emb.points.map((p) => {
    maxHits = Math.max(maxHits, p.retrieved_count)
    return {
      ...p,
      nx: norm(p.x, x0, x1),
      ny: norm(p.y, y0, y1),
      color: colorById.get(p.cluster ?? 0) ?? CLUSTER_COLORS[5],
    }
  })

  const hitsByCluster = new Map<number, number>()
  for (const p of points) {
    const key = p.cluster ?? 0
    hitsByCluster.set(key, (hitsByCluster.get(key) ?? 0) + p.retrieved_count)
  }
  const clusters: VmCluster[] = ordered.map((c) => ({
    ...c,
    color: colorById.get(c.id)!,
    hits: hitsByCluster.get(c.id) ?? 0,
  }))
  return { clusters, points, maxHits }
}

// -------------------------------------------------------------- report ----

/** Newest RAG doc for a week, else newest doc for the week. */
export function pickDoc(docs: Doc[], weekStart: string): Doc | null {
  const inWeek = docs.filter((d) => d.week_start === weekStart)
  return inWeek.find((d) => d.mode === 'rag') ?? inWeek[0] ?? null
}
