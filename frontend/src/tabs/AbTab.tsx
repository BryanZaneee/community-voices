import type { Comparison } from '../api'
import {
  citationCount,
  CRITERIA_LABELS,
  metricRows,
  segmentDoc,
  weekRange,
  type AbBlock,
} from '../viewmodel'
import { card, DISPLAY, kicker, MONO, whiteBtn } from '../ui'

function Paragraphs({ blocks, side }: { blocks: AbBlock[]; side: 'rag' | 'base' }) {
  return (
    <>
      {blocks.map((b, i) =>
        b.heading ? (
          <div
            key={i}
            style={{
              fontFamily: MONO, fontSize: 9.5, letterSpacing: '.12em',
              color: '#8A8C7C', textTransform: 'uppercase', margin: '14px 0 8px',
            }}
          >
            {b.heading}
          </div>
        ) : (
          <p
            key={i}
            style={{
              margin: '0 0 13px', fontSize: 13.2, lineHeight: 1.7,
              color: side === 'rag' ? '#26281E' : '#4A4C3E',
            }}
          >
            {b.segs.map((s, j) => (
              <span key={j}>
                <span
                  style={{
                    background: s.cite ? '#EEF1DA' : 'transparent',
                    borderBottom: s.cite
                      ? '2px solid #7A8B22'
                      : s.vague
                        ? '2px dashed #B9B4A5'
                        : '2px solid transparent',
                    padding: '1px 2px',
                    borderRadius: 2,
                  }}
                >
                  {s.text}
                </span>
                {s.cite != null && (
                  <sup style={{ fontFamily: MONO, fontSize: 8.5, color: '#5A661A', marginLeft: 1 }}>
                    {s.cite}
                  </sup>
                )}
              </span>
            ))}
          </p>
        ),
      )}
    </>
  )
}

export function AbTab({
  comp,
  canRun,
  busy,
  onRun,
  error,
}: {
  comp: Comparison | null
  canRun: boolean
  busy: boolean
  onRun: () => void
  error: string | null
}) {
  if (!comp) {
    return (
      <div style={{ ...card(), maxWidth: 560 }}>
        <div style={{ ...kicker, marginBottom: 10 }}>A/B — RAG VS LLM-ONLY</div>
        <div style={{ fontSize: 12.8, lineHeight: 1.6, color: '#4A4C3E', marginBottom: 14 }}>
          No comparison stored yet. Run one to see the same weekly report written
          twice — once grounded on retrieved chunks, once from the model&rsquo;s
          memory alone — judged blind on a 1–5 rubric.
        </div>
        <button onClick={onRun} disabled={!canRun || busy} className="btn-white" style={whiteBtn}>
          {busy ? 'Running…' : canRun ? 'Run A/B comparison' : 'Needs an API key in .env'}
        </button>
        {error && (
          <div style={{ fontFamily: MONO, fontSize: 11, color: '#A6522E', marginTop: 10 }}>
            {error}
          </div>
        )}
      </div>
    )
  }

  const rag = comp.doc_b // rag_vs_baseline: A = baseline, B = RAG
  const base = comp.doc_a
  const ragBlocks = segmentDoc(rag.content_md, 'rag')
  const baseBlocks = segmentDoc(base.content_md, 'base')
  const ragCites = citationCount(rag.content_md)
  const judge = comp.judge
  const rows = metricRows(comp)
  const range = weekRange(
    rag.week_start,
    new Date(new Date(rag.week_start + 'T00:00:00Z').getTime() + 7 * 86400e3)
      .toISOString()
      .slice(0, 10),
  )

  return (
    <div>
      {/* legend */}
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: '#6B6D5F' }}>
          Same prompt, same week ({range}), same model ({rag.model_key}) —
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#33352B' }}>
          <span
            style={{
              width: 12, height: 12, borderRadius: 3, background: '#EEF1DA',
              borderBottom: '2px solid #7A8B22',
            }}
          />
          grounded claim (cites a post title)
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#33352B' }}>
          <span
            style={{
              width: 12, height: 12, borderRadius: 3, background: '#FFFFFF',
              borderBottom: '2px dashed #B9B4A5',
            }}
          />
          hedged / unverifiable claim
        </span>
        <span style={{ flex: 1 }} />
        <button onClick={onRun} disabled={!canRun || busy} className="btn-white" style={whiteBtn}>
          {busy ? 'Running…' : 'Re-run A/B'}
        </button>
      </div>
      {error && (
        <div style={{ fontFamily: MONO, fontSize: 11, color: '#A6522E', marginBottom: 12 }}>
          {error}
        </div>
      )}

      {/* side-by-side docs */}
      <div
        style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14,
          marginBottom: 14, alignItems: 'start',
        }}
      >
        <div
          style={{
            border: '1px solid #DEE3B9', borderTop: '3px solid #7A8B22',
            borderRadius: 14, background: '#FFFFFF', padding: '20px 22px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
            <div style={{ fontFamily: DISPLAY, fontSize: 16, fontWeight: 700 }}>With RAG</div>
            <span
              style={{
                fontFamily: MONO, fontSize: 9.5, fontWeight: 600, color: '#3A421A',
                background: '#EEF1DA', border: '1px solid #DEE3B9',
                borderRadius: 99, padding: '3px 9px',
              }}
            >
              {ragCites} citations
            </span>
          </div>
          <div style={{ fontFamily: MONO, fontSize: 10, color: '#8A8C7C', marginBottom: 14 }}>
            {rag.model_key} + top-{rag.retrieved_chunk_ids?.length ?? 0} chunks from
            sqlite-vec ({rag.retrieval_mode})
          </div>
          <Paragraphs blocks={ragBlocks} side="rag" />
        </div>
        <div
          style={{
            border: '1px solid #E7E7DD', borderTop: '3px solid #C9CABB',
            borderRadius: 14, background: '#FFFFFF', padding: '20px 22px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
            <div style={{ fontFamily: DISPLAY, fontSize: 16, fontWeight: 700, color: '#4A4C3E' }}>
              LLM only
            </div>
            <span
              style={{
                fontFamily: MONO, fontSize: 9.5, fontWeight: 600, color: '#6B6D5F',
                background: '#F4F4EF', border: '1px solid #E7E7DD',
                borderRadius: 99, padding: '3px 9px',
              }}
            >
              0 citations
            </span>
          </div>
          <div style={{ fontFamily: MONO, fontSize: 10, color: '#8A8C7C', marginBottom: 14 }}>
            {base.model_key}, no retrieval context
          </div>
          <Paragraphs blocks={baseBlocks} side="base" />
        </div>
      </div>

      <div
        style={{
          display: 'grid', gridTemplateColumns: '1.15fr 1fr', gap: 14,
          alignItems: 'start', marginBottom: 14,
        }}
      >
        {/* judged criteria */}
        <div style={card()}>
          <div style={{ ...kicker, marginBottom: 14 }}>JUDGED CRITERIA (BLIND RUBRIC, 1–5)</div>
          {judge?.scores ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {Object.entries(CRITERIA_LABELS).map(([key, meta]) => {
                const ragScore = judge.scores!.b[key as keyof typeof judge.scores.b]
                const baseScore = judge.scores!.a[key as keyof typeof judge.scores.a]
                return (
                  <div key={key}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4, gap: 10 }}>
                      <span style={{ fontSize: 12.5, fontWeight: 600 }}>{meta.label}</span>
                      <span style={{ fontSize: 10, color: '#A2A494', textAlign: 'right' }}>{meta.note}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                      <span style={{ fontFamily: MONO, fontSize: 9, width: 28, color: '#5A661A' }}>RAG</span>
                      <div style={{ flex: 1, height: 6, borderRadius: 3, background: '#F0F0E7' }}>
                        <div style={{ height: '100%', width: `${(ragScore / 5) * 100}%`, background: '#7A8B22', borderRadius: 3 }} />
                      </div>
                      <span style={{ fontFamily: MONO, fontSize: 10, width: 14, textAlign: 'right' }}>{ragScore}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontFamily: MONO, fontSize: 9, width: 28, color: '#8A8C7C' }}>LLM</span>
                      <div style={{ flex: 1, height: 6, borderRadius: 3, background: '#F0F0E7' }}>
                        <div style={{ height: '100%', width: `${(baseScore / 5) * 100}%`, background: '#C9CABB', borderRadius: 3 }} />
                      </div>
                      <span style={{ fontFamily: MONO, fontSize: 10, width: 14, textAlign: 'right' }}>{baseScore}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: '#8A8C7C' }}>
              Judge unavailable for this run{judge?.rationale ? ` — ${judge.rationale}` : ''}.
            </div>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* run metrics */}
          <div style={card()}>
            <div style={{ ...kicker, marginBottom: 12 }}>RUN METRICS</div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <div
                style={{
                  display: 'grid', gridTemplateColumns: '1.4fr 1fr 1fr 54px', gap: 8,
                  padding: '0 0 7px', fontFamily: MONO, fontSize: 9,
                  letterSpacing: '.08em', color: '#A2A494',
                }}
              >
                <span />
                <span>RAG</span>
                <span>LLM ONLY</span>
                <span />
              </div>
              {rows.map((m) => (
                <div
                  key={m.name}
                  style={{
                    display: 'grid', gridTemplateColumns: '1.4fr 1fr 1fr 54px', gap: 8,
                    alignItems: 'center', padding: '7px 0', borderTop: '1px solid #F0F0E7',
                  }}
                >
                  <span style={{ fontSize: 11.5, color: '#4A4C3E' }}>{m.name}</span>
                  <span style={{ fontFamily: MONO, fontSize: 11, fontWeight: 600 }}>{m.rag}</span>
                  <span style={{ fontFamily: MONO, fontSize: 11, color: '#6B6D5F' }}>{m.base}</span>
                  <span
                    style={{
                      fontFamily: MONO, fontSize: 8.5, fontWeight: 600, textAlign: 'center',
                      borderRadius: 99, padding: '2.5px 0',
                      background: m.win === 'rag' ? '#EEF1DA' : m.win === 'base' ? '#F0F0E7' : 'transparent',
                      color: m.win === 'rag' ? '#3A421A' : m.win === 'base' ? '#6B6D5F' : '#B9BBA9',
                    }}
                  >
                    {m.win === 'rag' ? 'RAG' : m.win === 'base' ? 'LLM' : '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>
          {/* verdict */}
          <div
            style={{
              border: '1px solid #DEE3B9', borderRadius: 14,
              background: '#F6F8EA', padding: '16px 18px',
            }}
          >
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.14em', color: '#5A661A', marginBottom: 8 }}>
              VERDICT — {judge?.winner === 'b' ? 'RAG' : judge?.winner === 'a' ? 'LLM ONLY' : 'TIE'}
            </div>
            <div style={{ fontSize: 12.6, lineHeight: 1.62, color: '#33352B' }}>
              {judge?.rationale ?? 'No judge rationale stored for this comparison.'}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
