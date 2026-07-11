import { useEffect, useState } from 'react'
import { MeshGradient } from '@paper-design/shaders-react'
import { api, type Doc, type Stats, type Status } from '../api'

type MetricKey = 'cost' | 'latency' | 'tokens'

const METRICS = {
  cost: {
    label: 'Cost',
    pick: (d: Doc) => d.cost_usd,
    fmt: (v: number) => `$${v.toFixed(4)}`,
  },
  latency: {
    label: 'Latency',
    pick: (d: Doc) => d.latency_ms,
    fmt: (v: number) => `${(v / 1000).toFixed(1)}s`,
  },
  tokens: {
    label: 'Tokens',
    pick: (d: Doc) => d.input_tokens + d.output_tokens,
    fmt: (v: number) => `${Math.round(v).toLocaleString()} tok`,
  },
} as const

const PALETTES = {
  rag: ['#ff5c38', '#eec26a', '#ffa06b', '#b33a1f'],
  baseline: ['#4ee1c2', '#3f7fd9', '#7fd0ff', '#1f8a74'],
}

// ponytail: each MeshGradient is one WebGL context; page bg uses one and
// browsers allow ~16 — past this cap we fall back to the solid fills.
const MAX_MESH_BARS = 12

const avg = (ds: Doc[], pick: (d: Doc) => number | null): number | null => {
  const vs = ds.map(pick).filter((v): v is number => v != null)
  return vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null
}

export default function StatsTab({ status, week }: { status: Status; week: string }) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [docs, setDocs] = useState<Doc[] | null>(null)

  useEffect(() => {
    api.stats().then(setStats)
  }, [])

  useEffect(() => {
    setDocs(null)
    if (week) api.documents(week).then(setDocs)
  }, [week])

  if (!stats) return <div className="panel"><div className="empty">Loading…</div></div>

  const coverage =
    stats.chunks_total > 0
      ? Math.round(
          ((stats.chunks_total - stats.chunks_never_retrieved) /
            stats.chunks_total) *
            100,
        )
      : 0

  return (
    <>
      <div className="tiles">
        <div className="tile">
          <div className="value">{stats.total_retrievals}</div>
          <div className="label">total retrievals</div>
        </div>
        <div className="tile">
          <div className="value">{stats.chunks_total}</div>
          <div className="label">chunks indexed</div>
        </div>
        <div className="tile">
          <div className="value">{coverage}%</div>
          <div className="label">of chunks ever retrieved</div>
        </div>
        <div className="tile">
          <div className="value">{stats.chunks_never_retrieved}</div>
          <div className="label">never retrieved</div>
        </div>
      </div>

      <RagVsBaselineChart docs={docs} models={status.models} week={week} />

      {stats.per_model.length > 0 && (
        <div className="panel">
          <div className="panel-title">Generation stats by model</div>
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th className="num">Docs</th>
                <th className="num">Avg latency</th>
                <th className="num">Avg input tok</th>
                <th className="num">Avg output tok</th>
                <th className="num">Avg cost</th>
              </tr>
            </thead>
            <tbody>
              {stats.per_model.map((m) => (
                <tr key={m.model_key}>
                  <td>{status.models[m.model_key]?.label ?? m.model_key}</td>
                  <td className="num">{m.docs}</td>
                  <td className="num">{(m.avg_latency_ms / 1000).toFixed(1)}s</td>
                  <td className="num">{m.avg_input_tokens}</td>
                  <td className="num">{m.avg_output_tokens}</td>
                  <td className="num">
                    {m.avg_cost_usd != null ? `$${m.avg_cost_usd.toFixed(4)}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="panel">
        <div className="panel-title">
          Most retrieved chunks — the voices the documents are built from
        </div>
        {stats.top_chunks.length === 0 ? (
          <div className="empty">Nothing retrieved yet — generate a document.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th className="num">Count</th>
                <th>Post · section</th>
                <th>Last retrieved</th>
              </tr>
            </thead>
            <tbody>
              {stats.top_chunks.map((c) => (
                <tr key={c.chunk_id}>
                  <td className="num" style={{ color: 'var(--accent)', fontWeight: 700 }}>
                    {c.retrieved_count}×
                  </td>
                  <td>
                    {c.title ?? c.chunk_id}
                    <span className="snippet">{c.snippet}</span>
                  </td>
                  <td style={{ fontFamily: 'var(--mono)', fontSize: 11.5, whiteSpace: 'nowrap' }}>
                    {c.last_retrieved_at?.replace('T', ' ').slice(0, 16)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}

function RagVsBaselineChart({
  docs,
  models,
  week,
}: {
  docs: Doc[] | null
  models: Status['models']
  week: string
}) {
  const [metric, setMetric] = useState<MetricKey>('cost')
  const { pick, fmt } = METRICS[metric]

  const groups = new Map<string, { rag: Doc[]; baseline: Doc[] }>()
  for (const d of docs ?? []) {
    if (!groups.has(d.model_key)) groups.set(d.model_key, { rag: [], baseline: [] })
    groups.get(d.model_key)![d.mode].push(d)
  }
  const registry = Object.keys(models)
  const rows = [...groups.entries()]
    .map(([key, g]) => ({
      key,
      label: models[key]?.label ?? key,
      rag: avg(g.rag, pick),
      baseline: avg(g.baseline, pick),
    }))
    .sort((a, b) => {
      const ia = registry.indexOf(a.key)
      const ib = registry.indexOf(b.key)
      return (ia === -1 ? registry.length : ia) - (ib === -1 ? registry.length : ib)
    })
  const max = Math.max(0, ...rows.flatMap((r) => [r.rag ?? 0, r.baseline ?? 0]))
  const animated = rows.length * 2 <= MAX_MESH_BARS

  return (
    <div className="panel">
      <div className="panel-title">This week: RAG vs no-RAG · {week}</div>
      {docs === null ? (
        <div className="empty">Loading…</div>
      ) : rows.length === 0 || max === 0 ? (
        <div className="empty">
          No documents generated for this week yet — generate some on the Document tab.
        </div>
      ) : (
        <>
          <div className="meta-row">
            <div className="tabs mini">
              {(Object.keys(METRICS) as MetricKey[]).map((k) => (
                <button
                  key={k}
                  className={k === metric ? 'active' : ''}
                  onClick={() => setMetric(k)}
                >
                  {METRICS[k].label}
                </button>
              ))}
            </div>
            <span className="chip accent">RAG</span>
            <span className="chip teal">no-RAG</span>
          </div>
          {rows.map((r) => (
            <div className="ragbar-row" key={r.key}>
              <div className="ragbar-label">{r.label}</div>
              <div className="ragbar-tracks">
                <MeshBar value={r.rag} max={max} mode="rag" fmt={fmt} animated={animated} />
                <MeshBar
                  value={r.baseline}
                  max={max}
                  mode="baseline"
                  fmt={fmt}
                  animated={animated}
                />
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

function MeshBar({
  value,
  max,
  mode,
  fmt,
  animated,
}: {
  value: number | null
  max: number
  mode: 'rag' | 'baseline'
  fmt: (v: number) => string
  animated: boolean
}) {
  if (value == null) {
    return (
      <div className="ragbar-track">
        <span className="ragbar-none">—</span>
      </div>
    )
  }
  const w = Math.max((value / max) * 100, 2)
  const inside = w > 72
  return (
    <div className="ragbar-track">
      <div className={`ragbar-fill ${mode}`} style={{ width: `${w}%` }}>
        {animated && (
          <MeshGradient
            className="ragbar-mesh"
            colors={PALETTES[mode]}
            distortion={0.8}
            swirl={0.5}
            speed={0.25}
          />
        )}
      </div>
      <span
        className={inside ? 'ragbar-value inside' : 'ragbar-value'}
        style={inside ? { right: `calc(${100 - w}% + 8px)` } : { left: `calc(${w}% + 8px)` }}
      >
        {fmt(value)}
      </span>
    </div>
  )
}
