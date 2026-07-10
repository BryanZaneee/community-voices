import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, type EmbeddingPoint } from '../api'

// Validated categorical palette for dark surfaces (dataviz reference instance,
// fixed order — weeks map to slots newest-first, never re-cycled on filtering).
const WEEK_COLORS = ['#3987e5', '#199e70', '#c98500', '#9085e9', '#e66767']
const OTHER_COLOR = '#5d6373'

function PointTooltip({ active, payload }: {
  active?: boolean
  payload?: { payload: EmbeddingPoint }[]
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div
      style={{
        background: 'var(--panel-solid)',
        border: '1px solid var(--line-strong)',
        borderRadius: 10,
        padding: '10px 14px',
        maxWidth: 320,
        fontFamily: 'var(--mono)',
        fontSize: 12,
      }}
    >
      <div style={{ color: 'var(--text)', marginBottom: 4 }}>
        {p.title ?? p.path}
      </div>
      {p.heading && (
        <div style={{ color: 'var(--text-dim)' }}>§ {p.heading}</div>
      )}
      <div style={{ color: 'var(--text-dim)', marginTop: 4 }}>
        week {p.week_start ?? '—'} · retrieved {p.retrieved_count}×
      </div>
    </div>
  )
}

export default function EmbeddingsTab() {
  const [points, setPoints] = useState<EmbeddingPoint[]>([])
  const [model, setModel] = useState<string | null>(null)

  useEffect(() => {
    api.embeddings().then((d) => {
      setPoints(d.points)
      setModel(d.embedding_model)
    })
  }, [])

  const weeks = useMemo(
    () =>
      [...new Set(points.map((p) => p.week_start).filter(Boolean))].sort(
        (a, b) => (a! < b! ? 1 : -1),
      ) as string[],
    [points],
  )

  const groups = useMemo(
    () =>
      weeks.map((w, i) => ({
        week: w,
        color: WEEK_COLORS[i] ?? OTHER_COLOR,
        points: points.filter((p) => p.week_start === w),
      })),
    [weeks, points],
  )

  if (!points.length) {
    return (
      <div className="panel">
        <div className="empty">No embeddings yet — run the ingest first.</div>
      </div>
    )
  }

  return (
    <div className="panel">
      <div className="panel-title">
        Embedding map · {points.length} chunks · PCA of{' '}
        {model ?? 'embeddings'} → 2D
      </div>
      <p style={{ color: 'var(--text-dim)', fontSize: 13.5, maxWidth: '70ch', marginBottom: 6 }}>
        Every dot is one indexed chunk of community discussion, projected from
        embedding space onto its two principal components — chunks about the
        same story cluster together. Dot size grows with how often the RAG
        pipeline retrieved that chunk.
      </p>
      <div
        style={{
          display: 'flex',
          gap: 16,
          flexWrap: 'wrap',
          fontFamily: 'var(--mono)',
          fontSize: 11.5,
          color: 'var(--text-dim)',
          margin: '10px 0 4px',
        }}
      >
        {groups.map((g) => (
          <span key={g.week} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: g.color,
                display: 'inline-block',
              }}
            />
            week of {g.week}
          </span>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={520}>
        <ScatterChart margin={{ top: 16, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.05)" />
          <XAxis
            type="number"
            dataKey="x"
            tick={false}
            axisLine={{ stroke: 'rgba(255,255,255,0.12)' }}
            label={{
              value: 'PC1',
              position: 'insideBottomRight',
              fill: 'var(--text-faint)',
              fontSize: 11,
              fontFamily: 'var(--mono)',
            }}
          />
          <YAxis
            type="number"
            dataKey="y"
            tick={false}
            axisLine={{ stroke: 'rgba(255,255,255,0.12)' }}
            label={{
              value: 'PC2',
              angle: -90,
              position: 'insideTopLeft',
              fill: 'var(--text-faint)',
              fontSize: 11,
              fontFamily: 'var(--mono)',
            }}
          />
          <Tooltip content={<PointTooltip />} cursor={{ strokeDasharray: '4 4', stroke: 'rgba(255,255,255,0.2)' }} />
          {groups.map((g) => (
            <Scatter
              key={g.week}
              name={`week of ${g.week}`}
              data={g.points}
              fill={g.color}
              fillOpacity={0.85}
              shape={(props: unknown) => {
                const { cx, cy, payload } = props as {
                  cx: number
                  cy: number
                  payload: EmbeddingPoint
                }
                const r = 4 + Math.sqrt(payload.retrieved_count) * 3
                return (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={r}
                    fill={g.color}
                    fillOpacity={payload.retrieved_count > 0 ? 0.9 : 0.45}
                    stroke="var(--bg)"
                    strokeWidth={1.5}
                  />
                )
              }}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}
