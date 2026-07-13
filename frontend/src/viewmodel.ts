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
  '#2E7D5B', '#5B6770', '#B08C1E', '#7A8B22', '#A65A2E', '#9A9A90',
]

export const ACCENT = '#2E7D5B'

export const fmt = (n: number | null | undefined): string =>
  n == null ? '-' : n.toLocaleString('en-US')

export const fmtSecs = (ms: number | null | undefined): string =>
  ms == null ? '-' : `${(ms / 1000).toFixed(1)}s`

export const fmtUsd = (v: number | null | undefined): string =>
  v == null ? '-' : `$${v.toFixed(3)}`

/** "games@lemmy.world" -> { name: "c/games", instance: "lemmy.world" } */
export function communityIdentity(subreddit: string | null, source?: string) {
  if (!subreddit) return { name: '-', instance: '', initial: '?' }
  if (source === 'hackernews') {
    return { name: 'Hacker News', instance: 'news.ycombinator.com', initial: 'Y' }
  }
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
  return `${s.toLocaleDateString('en-US', { ...opts, timeZone: 'UTC' })} to ${e.toLocaleDateString('en-US', { ...opts, timeZone: 'UTC' })}`
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
      .replace(/^_(.+)_$/s, '$1') // topic meta lines (_N% · N threads_)
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

/** Character-weighted claim composition of a segmented doc. */
export interface ClaimStats {
  grounded: number // count of cited spans
  hedged: number // count of hedged/unverifiable spans
  groundedChars: number
  hedgedChars: number
  neutralChars: number
  totalChars: number
}

export function claimStats(blocks: AbBlock[]): ClaimStats {
  const s: ClaimStats = {
    grounded: 0, hedged: 0,
    groundedChars: 0, hedgedChars: 0, neutralChars: 0, totalChars: 0,
  }
  for (const b of blocks) {
    for (const seg of b.segs) {
      const n = seg.text.length
      s.totalChars += n
      if (seg.cite != null) {
        s.grounded += 1
        s.groundedChars += n
      } else if (seg.vague) {
        s.hedged += 1
        s.hedgedChars += n
      } else {
        s.neutralChars += n
      }
    }
  }
  return s
}

export interface MetricRow {
  name: string
  note: string
  rag: string
  base: string
  ragN: number
  baseN: number
  win: 'rag' | 'base' | 'even'
  delta: string
}

const ratio = (hi: number, lo: number): string =>
  lo > 0 ? `${(hi / lo).toFixed(1)}×` : '-'

export function metricRows(
  comp: Comparison,
  ragStats: ClaimStats,
  baseStats: ClaimStats,
): MetricRow[] {
  const rag = comp.doc_b // rag_vs_baseline: A = baseline, B = RAG
  const base = comp.doc_a
  const lower = (a: number, b: number): 'rag' | 'base' | 'even' =>
    a === b ? 'even' : a < b ? 'rag' : 'base'
  const ragCost = rag.cost_usd ?? 0
  const baseCost = base.cost_usd ?? 0
  const rows: MetricRow[] = [
    {
      name: 'Cost / report',
      note: 'retrieved context is paid input',
      rag: fmtUsd(rag.cost_usd),
      base: fmtUsd(base.cost_usd),
      ragN: ragCost,
      baseN: baseCost,
      win: lower(ragCost, baseCost),
      delta: `${ratio(Math.max(ragCost, baseCost), Math.min(ragCost, baseCost))} ${ragCost > baseCost ? 'more' : 'less'}`,
    },
    {
      name: 'Generation time',
      note: 'retrieval + a longer prompt',
      rag: fmtSecs(rag.latency_ms),
      base: fmtSecs(base.latency_ms),
      ragN: rag.latency_ms,
      baseN: base.latency_ms,
      win: lower(rag.latency_ms, base.latency_ms),
      delta: `${((rag.latency_ms - base.latency_ms) / 1000).toFixed(1)}s slower`,
    },
    {
      name: 'Input tokens',
      note: 'the chunks the model reads',
      rag: fmt(rag.input_tokens),
      base: fmt(base.input_tokens),
      ragN: rag.input_tokens,
      baseN: base.input_tokens,
      win: lower(rag.input_tokens, base.input_tokens),
      delta: `${ratio(rag.input_tokens, base.input_tokens)} the context`,
    },
    {
      name: 'Output tokens',
      note: 'both write a full report',
      rag: fmt(rag.output_tokens),
      base: fmt(base.output_tokens),
      ragN: rag.output_tokens,
      baseN: base.output_tokens,
      win: 'even',
      delta: '≈ even',
    },
    {
      // baseline has no retrieval, so nothing it writes is verifiable
      name: 'Verifiable citations',
      note: 'claims that trace to a real thread',
      rag: String(ragStats.grounded),
      base: '0',
      ragN: ragStats.grounded,
      baseN: 0,
      win: ragStats.grounded > 0 ? 'rag' : 'even',
      delta: `${ragStats.grounded} vs 0`,
    },
    {
      name: 'Hedged claims',
      note: '"likely", "probably", invented titles',
      rag: String(ragStats.hedged),
      base: String(baseStats.hedged),
      ragN: ragStats.hedged,
      baseN: baseStats.hedged,
      win: lower(ragStats.hedged, baseStats.hedged),
      delta: `${ragStats.hedged} vs ${baseStats.hedged}`,
    },
  ]
  return rows.filter((r) => r.ragN > 0 || r.baseN > 0) // drop empty rows
}

/** Pros/cons bullets for the verdict panel, from real run numbers. */
export function prosCons(
  comp: Comparison,
  ragStats: ClaimStats,
  baseStats: ClaimStats,
): { pros: string[]; cons: string[] } {
  const rag = comp.doc_b
  const base = comp.doc_a
  const judge = comp.judge?.scores
  const pros = [
    `${ragStats.grounded} claims trace to real retrieved threads; the baseline has 0 verifiable claims`,
    `covers this exact week: grounded on ${rag.retrieved_chunk_ids?.length ?? 0} chunks scoped to the covered window`,
  ]
  if (baseStats.hedged > ragStats.hedged) {
    pros.push(
      `${ragStats.hedged} hedged statements vs ${baseStats.hedged} in the baseline`,
    )
  }
  if (judge) {
    const ragTotal = Object.values(judge.b).reduce((a, v) => a + v, 0)
    const baseTotal = Object.values(judge.a).reduce((a, v) => a + v, 0)
    pros.push(`blind judge scores it ${ragTotal}/20 vs ${baseTotal}/20`)
  }
  const cons = [
    `${ratio(rag.cost_usd ?? 0, base.cost_usd ?? 0)} the cost per report (${fmtUsd(rag.cost_usd)} vs ${fmtUsd(base.cost_usd)})`,
    `${((rag.latency_ms - base.latency_ms) / 1000).toFixed(1)}s slower end-to-end (retrieval + a ${ratio(rag.input_tokens, base.input_tokens)} larger prompt)`,
    'needs the crawl to have run: no ingest, no grounding',
  ]
  return { pros, cons }
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
