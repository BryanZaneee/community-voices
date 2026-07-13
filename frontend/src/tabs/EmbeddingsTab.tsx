import { useCallback, useEffect, useRef, useState } from 'react'
import type { Embeddings, Stats } from '../api'
import { ACCENT, fmt, scatterModel, type VmCluster, type VmPoint } from '../viewmodel'
import { card, DISPLAY, kicker, MONO } from '../ui'

const CANVAS_H = 430

interface Tooltip {
  x: number
  y: number
  name: string
  hits: number
  snippet: string
}

export function EmbeddingsTab({
  emb,
  stats,
}: {
  emb: Embeddings | null
  stats: Stats | null
}) {
  const [heat, setHeat] = useState(false)
  const [sel, setSel] = useState<number | null>(null)
  const [tt, setTt] = useState<Tooltip | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const hoverRef = useRef<VmPoint | null>(null)
  const model = emb && emb.points.length ? scatterModel(emb) : null

  const draw = useCallback(() => {
    const el = canvasRef.current
    if (!el || !model) return
    const dpr = window.devicePixelRatio || 1
    const w = el.clientWidth || 700
    el.width = w * dpr
    el.height = CANVAS_H * dpr
    const ctx = el.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, CANVAS_H)
    ctx.strokeStyle = 'rgba(22,24,15,.04)'
    ctx.lineWidth = 1
    for (let i = 1; i < 6; i++) {
      const x = (w / 6) * i
      const y = (CANVAS_H / 6) * i
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, CANVAS_H); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke()
    }
    for (const p of model.points) {
      const x = p.nx * w
      const y = p.ny * CANVAS_H
      const f = p.retrieved_count / model.maxHits
      let col: string, alpha: number, r: number
      if (heat) {
        col = f > 0.5 ? '#3A421F' : ACCENT
        alpha = 0.12 + f * 0.88
        r = 1.4 + f * 5.5
      } else {
        col = p.color
        alpha = 0.72
        r = 1.6 + f * 3.2
      }
      if (sel != null && p.cluster !== sel) alpha *= 0.14
      ctx.globalAlpha = alpha
      ctx.fillStyle = col
      ctx.beginPath()
      ctx.arc(x, y, r, 0, 7)
      ctx.fill()
    }
    const h = hoverRef.current
    if (h) {
      ctx.globalAlpha = 1
      ctx.strokeStyle = '#16180F'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.arc(h.nx * w, h.ny * CANVAS_H, 6.5, 0, 7)
      ctx.stroke()
    }
    ctx.globalAlpha = 1
    // model dep: emb identity is enough — scatterModel is pure
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emb, heat, sel])

  useEffect(() => {
    draw()
    const onResize = () => draw()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [draw])

  const findPoint = (e: React.MouseEvent): { p: VmPoint; mx: number; my: number } | null => {
    const el = canvasRef.current
    if (!el || !model) return null
    const rect = el.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    let best: VmPoint | null = null
    let bd = 121
    for (const p of model.points) {
      const dx = p.nx * rect.width - mx
      const dy = p.ny * CANVAS_H - my
      const d = dx * dx + dy * dy
      if (d < bd) {
        bd = d
        best = p
      }
    }
    return best ? { p: best, mx, my } : null
  }

  const onMove = (e: React.MouseEvent) => {
    const hit = findPoint(e)
    hoverRef.current = hit?.p ?? null
    if (!hit) {
      if (tt) setTt(null)
      draw()
      return
    }
    setTt({
      x: hit.mx,
      y: hit.my,
      name: hit.p.title ?? hit.p.heading,
      hits: hit.p.retrieved_count,
      snippet: hit.p.snippet ?? '',
    })
    draw()
  }

  if (!emb || !model || !stats) {
    return (
      <div style={{ fontFamily: MONO, fontSize: 11, color: '#8A8C7C' }}>
        No embeddings yet. Run an ingest first.
      </div>
    )
  }

  const totalHits = stats.total_retrievals || 1
  const clusterById = new Map(model.clusters.map((c) => [c.id, c]))
  const selCluster: VmCluster | null = sel != null ? (clusterById.get(sel) ?? null) : null
  const selChunks = selCluster
    ? model.points
        .filter((p) => p.cluster === sel)
        .sort((a, b) => b.retrieved_count - a.retrieved_count)
        .slice(0, 4)
    : []
  const pointById = new Map(model.points.map((p) => [p.id, p]))
  const topChunks = stats.top_chunks.slice(0, 6)
  const maxTop = topChunks[0]?.retrieved_count || 1
  const dims = emb.points.length ? `${emb.embedding_model ?? '-'}` : '-'
  const methodLabel = (emb.method ?? 'pca').toUpperCase()

  return (
    <div>
      {/* stat strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 14 }}>
        {[
          [fmt(stats.chunks_total), 'chunks in sqlite-vec'],
          [dims, 'embedding model'],
          [methodLabel, `${methodLabel === 'UMAP' ? 'nonlinear' : 'linear'} 2-D projection`],
          [fmt(stats.total_retrievals), 'retrievals logged'],
        ].map(([v, label]) => (
          <div key={label} style={{ ...card('14px 16px'), borderRadius: 12 }}>
            <div style={{ fontFamily: MONO, fontSize: 17, fontWeight: 600 }}>{v}</div>
            <div style={{ fontSize: 10.5, color: '#8A8C7C', marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>

      <div
        style={{
          display: 'grid', gridTemplateColumns: '1fr 320px', gap: 14,
          alignItems: 'start', marginBottom: 14,
        }}
      >
        {/* scatter card */}
        <div style={{ ...card('16px 18px 14px'), minWidth: 0 }}>
          <div
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              flexWrap: 'wrap', gap: 8, marginBottom: 12,
            }}
          >
            <div style={kicker}>
              {methodLabel} 2D · {model.points.length} CHUNKS
            </div>
            <div style={{ display: 'flex', flex: 'none', border: '1px solid #E1E3D2', borderRadius: 8, overflow: 'hidden' }}>
              <button
                onClick={() => setHeat(false)}
                style={{
                  padding: '6px 12px', border: 'none', whiteSpace: 'nowrap', flex: 'none',
                  background: heat ? '#FFFFFF' : '#16180F',
                  color: heat ? '#6B6D5F' : '#FAFAF7',
                  fontFamily: MONO, fontSize: 10, fontWeight: 600, cursor: 'pointer',
                }}
              >
                TOPICS
              </button>
              <button
                onClick={() => setHeat(true)}
                style={{
                  padding: '6px 12px', border: 'none', borderLeft: '1px solid #E1E3D2',
                  whiteSpace: 'nowrap', flex: 'none',
                  background: heat ? '#16180F' : '#FFFFFF',
                  color: heat ? '#FAFAF7' : '#6B6D5F',
                  fontFamily: MONO, fontSize: 10, fontWeight: 600, cursor: 'pointer',
                }}
              >
                RETRIEVAL HEAT
              </button>
            </div>
          </div>
          <div
            style={{
              position: 'relative', background: '#FBFBF8',
              border: '1px solid #F0F0E7', borderRadius: 10, overflow: 'hidden',
            }}
          >
            <canvas
              ref={canvasRef}
              onMouseMove={onMove}
              onMouseLeave={() => {
                hoverRef.current = null
                setTt(null)
                draw()
              }}
              onClick={() => {
                setSel(hoverRef.current ? (hoverRef.current.cluster ?? null) : null)
              }}
              style={{ width: '100%', height: CANVAS_H, display: 'block', cursor: 'crosshair' }}
            />
            <div
              style={{
                position: 'absolute', right: 10, bottom: 8, fontFamily: MONO,
                fontSize: 8.5, color: '#A2A494', pointerEvents: 'none',
              }}
            >
              {methodLabel}-1 →
            </div>
            <div
              style={{
                position: 'absolute', left: 8, top: 10, fontFamily: MONO,
                fontSize: 8.5, color: '#A2A494', pointerEvents: 'none',
                writingMode: 'vertical-rl', transform: 'rotate(180deg)',
              }}
            >
              {methodLabel}-2 →
            </div>
            {tt && (
              <div
                style={{
                  position: 'absolute', left: tt.x + 14, top: tt.y + 12,
                  pointerEvents: 'none', background: '#16180F', color: '#FAFAF7',
                  borderRadius: 8, padding: '7px 10px', maxWidth: 230,
                  boxShadow: '0 4px 16px rgba(22,24,15,.25)',
                }}
              >
                <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 2 }}>{tt.name}</div>
                <div style={{ fontFamily: MONO, fontSize: 9.5, color: '#B9C65A' }}>
                  retrieved {tt.hits}× by the generator
                </div>
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 12 }}>
            {model.clusters.map((c) => {
              const act = sel === c.id
              return (
                <button
                  key={c.id}
                  onClick={() => setSel(act ? null : c.id)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 7, padding: '5.5px 11px',
                    borderRadius: 99,
                    border: `1px solid ${act ? '#DEE3B9' : '#E7E7DD'}`,
                    background: act ? '#F3F5E3' : '#FFFFFF',
                    fontSize: 11, fontWeight: 600, color: '#33352B', cursor: 'pointer',
                  }}
                >
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: c.color }} />
                  {c.label}
                  <span style={{ fontFamily: MONO, fontSize: 9, color: '#8A8C7C' }}>{c.n}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* cluster inspector */}
        <div style={{ ...card('16px 18px'), minHeight: 300, minWidth: 0 }}>
          {selCluster ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 9, height: 9, borderRadius: '50%', background: selCluster.color }} />
                  <span style={{ fontFamily: DISPLAY, fontSize: 15, fontWeight: 600 }}>
                    {selCluster.label}
                  </span>
                </div>
                <button
                  onClick={() => setSel(null)}
                  style={{
                    border: 'none', background: 'none', fontFamily: MONO, fontSize: 10,
                    color: '#8A8C7C', cursor: 'pointer', textDecoration: 'underline',
                  }}
                >
                  clear
                </button>
              </div>
              <div style={{ fontFamily: MONO, fontSize: 10, color: '#8A8C7C', marginBottom: 13 }}>
                {selCluster.n} chunks · {Math.round((selCluster.hits / totalHits) * 100)}% of
                retrieval volume
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                {selChunks.map((ch) => (
                  <div
                    key={ch.id}
                    style={{
                      border: '1px solid #EFEFE6', borderRadius: 10,
                      padding: '11px 12px', background: '#FCFCF9',
                    }}
                  >
                    <div style={{ fontSize: 11.6, lineHeight: 1.5, color: '#33352B', marginBottom: 6 }}>
                      {ch.snippet ? `${ch.snippet}…` : ch.heading}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                      <span
                        style={{
                          fontFamily: MONO, fontSize: 9, color: '#A2A494',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}
                      >
                        {ch.title ?? ch.path} · {ch.week_start ?? ''}
                      </span>
                      <span
                        style={{
                          fontFamily: MONO, fontSize: 9, fontWeight: 600, color: '#1E5940',
                          background: '#EEF1DA', borderRadius: 99, padding: '2px 7px', flex: 'none',
                        }}
                      >
                        {ch.retrieved_count}× retrieved
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <div style={{ ...kicker, marginBottom: 12 }}>CLUSTER INSPECTOR</div>
              <div style={{ fontSize: 12.5, lineHeight: 1.6, color: '#6B6D5F' }}>
                Click a cluster in the map (or a legend chip) to see its
                most-retrieved chunks and how often the generator pulls from it.
              </div>
              <div
                style={{
                  marginTop: 16, padding: 12, border: '1px dashed #DEE3B9', borderRadius: 10,
                  fontSize: 11.5, lineHeight: 1.55, color: '#5F6153', background: '#FBFCF4',
                }}
              >
                {stats.chunks_never_retrieved} of {stats.chunks_total} chunks have
                never been retrieved; the generator&rsquo;s attention follows a{' '}
                <span style={{ fontWeight: 700, color: '#3A421A' }}>power law</span>.
              </div>
            </>
          )}
        </div>
      </div>

      {/* most-retrieved table */}
      <div style={card()}>
        <div style={{ ...kicker, marginBottom: 13 }}>MOST-RETRIEVED CHUNKS</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {topChunks.map((tc, i) => {
            const color = pointById.get(tc.chunk_id)?.color ?? ACCENT
            return (
              <div
                key={tc.chunk_id}
                style={{
                  display: 'grid', gridTemplateColumns: '26px 1fr 190px 90px',
                  gap: 12, alignItems: 'center',
                }}
              >
                <span style={{ fontFamily: MONO, fontSize: 10.5, color: '#A2A494' }}>
                  #{i + 1}
                </span>
                <span
                  style={{
                    fontSize: 11.8, color: '#33352B', whiteSpace: 'nowrap',
                    overflow: 'hidden', textOverflow: 'ellipsis',
                  }}
                >
                  {tc.title ? `${tc.title}: ` : ''}
                  {tc.snippet}
                </span>
                <div style={{ height: 6, borderRadius: 3, background: '#F0F0E7' }}>
                  <div
                    style={{
                      height: '100%',
                      width: `${(tc.retrieved_count / maxTop) * 100}%`,
                      background: color, borderRadius: 3,
                    }}
                  />
                </div>
                <span
                  style={{
                    fontFamily: MONO, fontSize: 10.5, fontWeight: 600,
                    color: '#3A421A', textAlign: 'right',
                  }}
                >
                  {tc.retrieved_count} hits
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
