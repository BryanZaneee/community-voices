import type { Comparison } from '../api'
import {
  claimStats,
  CRITERIA_LABELS,
  metricRows,
  prosCons,
  segmentDoc,
  weekRange,
  type AbBlock,
  type ClaimStats,
} from '../viewmodel'
import { card, DISPLAY, kicker, MONO, whiteBtn } from '../ui'

const TEAL = '#2E7D5B'
const GRAY = '#C9CABB'
const HEDGE = '#B9B4A5'

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
                      ? `2px solid ${TEAL}`
                      : s.vague
                        ? `2px dashed ${HEDGE}`
                        : '2px solid transparent',
                    padding: '1px 2px',
                    borderRadius: 2,
                  }}
                >
                  {s.text}
                </span>
                {s.cite != null && (
                  <sup style={{ fontFamily: MONO, fontSize: 8.5, color: '#1E5940', marginLeft: 1 }}>
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

/** One stacked bar: grounded / neutral / hedged shares of the document. */
function CompositionBar({ label, stats }: { label: string; stats: ClaimStats }) {
  const total = Math.max(1, stats.totalChars)
  const pct = (n: number) => (n / total) * 100
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 5 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{label}</span>
        <span style={{ fontFamily: MONO, fontSize: 10, color: '#6B6D5F' }}>
          {stats.grounded} grounded · {stats.hedged} hedged
        </span>
      </div>
      <div style={{ display: 'flex', height: 14, borderRadius: 4, overflow: 'hidden', background: '#F0F0E7' }}>
        <div style={{ width: `${pct(stats.groundedChars)}%`, background: TEAL }} />
        <div style={{ width: `${pct(stats.neutralChars)}%`, background: '#E3E4D8' }} />
        <div style={{ width: `${pct(stats.hedgedChars)}%`, background: HEDGE }} />
      </div>
      <div style={{ display: 'flex', gap: 14, marginTop: 5, fontFamily: MONO, fontSize: 9, color: '#8A8C7C' }}>
        <span>{Math.round(pct(stats.groundedChars))}% grounded</span>
        <span>{Math.round(pct(stats.neutralChars))}% neutral prose</span>
        <span>{Math.round(pct(stats.hedgedChars))}% hedged</span>
      </div>
    </div>
  )
}

export function AbTab({
  comp,
  judging = false,
  canRun,
  busy,
  onRun,
  error,
}: {
  comp: Comparison | null
  judging?: boolean
  canRun: boolean
  busy: boolean
  onRun: () => void
  error: string | null
}) {
  if (!comp) {
    return (
      <div style={{ ...card(), maxWidth: 560 }}>
        <div style={{ ...kicker, marginBottom: 10 }}>A/B — RAG VS LLM-ONLY</div>
        {judging && (
          <div style={{ fontFamily: MONO, fontSize: 11, color: '#1E5940', marginBottom: 10 }}>
            Judge still deciding… the verdict will appear here.
          </div>
        )}
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
  const ragStats = claimStats(ragBlocks)
  const baseStats = claimStats(baseBlocks)
  const judge = comp.judge
  const rows = metricRows(comp, ragStats, baseStats)
  const maxRow = (r: (typeof rows)[number]) => Math.max(r.ragN, r.baseN, 1)
  const { pros, cons } = prosCons(comp, ragStats, baseStats)
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
              borderBottom: `2px solid ${TEAL}`,
            }}
          />
          grounded claim (cites a post title)
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#33352B' }}>
          <span
            style={{
              width: 12, height: 12, borderRadius: 3, background: '#FFFFFF',
              borderBottom: `2px dashed ${HEDGE}`,
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
            border: '1px solid #DEE3B9', borderTop: `3px solid ${TEAL}`,
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
              {ragStats.grounded} citations
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
            border: '1px solid #E7E7DD', borderTop: `3px solid ${GRAY}`,
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
            {base.model_key}, no data access — writing from model memory alone,
            so its specifics are unverifiable guesses
          </div>
          <Paragraphs blocks={baseBlocks} side="base" />
        </div>
      </div>

      {/* claim composition */}
      <div style={{ ...card(), marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
          <div style={kicker}>CLAIM COMPOSITION — SHARE OF EACH DOCUMENT</div>
          <div style={{ fontSize: 10, color: '#A2A494' }}>
            grounded = cites a retrieved thread · hedged = &ldquo;likely / probably&rdquo; or an unverifiable title
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <CompositionBar label="With RAG" stats={ragStats} />
          <CompositionBar label="LLM only" stats={baseStats} />
        </div>
      </div>

      <div
        style={{
          display: 'grid', gridTemplateColumns: '1fr 1.15fr', gap: 14,
          alignItems: 'start', marginBottom: 14,
        }}
      >
        {/* judged criteria */}
        <div style={card()}>
          <div style={{ ...kicker, marginBottom: 14 }}>
            JUDGED CRITERIA (BLIND RUBRIC, 1–5, GRADED VS THE WEEK&rsquo;S SOURCES)
          </div>
          {judging ? (
            <div style={{ fontSize: 12, color: '#1E5940' }}>
              Judge still deciding… fresh scores will land here when the
              blind rubric is done.
            </div>
          ) : judge?.scores ? (
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
                      <span style={{ fontFamily: MONO, fontSize: 9, width: 28, color: '#1E5940' }}>RAG</span>
                      <div style={{ flex: 1, height: 6, borderRadius: 3, background: '#F0F0E7' }}>
                        <div style={{ height: '100%', width: `${(ragScore / 5) * 100}%`, background: TEAL, borderRadius: 3 }} />
                      </div>
                      <span style={{ fontFamily: MONO, fontSize: 10, width: 14, textAlign: 'right' }}>{ragScore}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontFamily: MONO, fontSize: 9, width: 28, color: '#8A8C7C' }}>LLM</span>
                      <div style={{ flex: 1, height: 6, borderRadius: 3, background: '#F0F0E7' }}>
                        <div style={{ height: '100%', width: `${(baseScore / 5) * 100}%`, background: GRAY, borderRadius: 3 }} />
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

        {/* run metrics — paired bars */}
        <div style={card()}>
          <div style={{ ...kicker, marginBottom: 14 }}>RUN METRICS</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {rows.map((m) => (
              <div key={m.name}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4, gap: 10 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 600 }}>{m.name}</span>
                  <span
                    style={{
                      fontFamily: MONO, fontSize: 9, fontWeight: 600,
                      color: m.win === 'rag' ? '#3A421A' : m.win === 'base' ? '#8A6A20' : '#A2A494',
                    }}
                  >
                    {m.delta}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                  <span style={{ fontFamily: MONO, fontSize: 9, width: 28, color: '#1E5940' }}>RAG</span>
                  <div style={{ flex: 1, height: 6, borderRadius: 3, background: '#F0F0E7' }}>
                    <div style={{ height: '100%', width: `${(m.ragN / maxRow(m)) * 100}%`, background: TEAL, borderRadius: 3 }} />
                  </div>
                  <span style={{ fontFamily: MONO, fontSize: 10, width: 52, textAlign: 'right' }}>{m.rag}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontFamily: MONO, fontSize: 9, width: 28, color: '#8A8C7C' }}>LLM</span>
                  <div style={{ flex: 1, height: 6, borderRadius: 3, background: '#F0F0E7' }}>
                    <div style={{ height: '100%', width: `${(m.baseN / maxRow(m)) * 100}%`, background: GRAY, borderRadius: 3 }} />
                  </div>
                  <span style={{ fontFamily: MONO, fontSize: 10, width: 52, textAlign: 'right', color: '#6B6D5F' }}>{m.base}</span>
                </div>
                <div style={{ fontSize: 9.5, color: '#A2A494', marginTop: 3 }}>{m.note}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* verdict: pros / cons + judge rationale */}
      <div
        style={{
          border: '1px solid #DEE3B9', borderRadius: 14,
          background: '#F6F8EA', padding: '18px 20px',
        }}
      >
        <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.14em', color: '#1E5940', marginBottom: 12 }}>
          VERDICT — {judging ? 'JUDGE STILL DECIDING…'
            : judge?.winner === 'b' ? 'RAG' : judge?.winner === 'a' ? 'LLM ONLY' : 'TIE'}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginBottom: 14 }}>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: '.1em', color: '#3A421A', marginBottom: 7 }}>
              WHAT RAG BUYS
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {pros.map((p) => (
                <div key={p} style={{ display: 'flex', gap: 7, fontSize: 11.8, lineHeight: 1.5, color: '#33352B' }}>
                  <span style={{ color: TEAL, flex: 'none' }}>▸</span>
                  <span>{p}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: '.1em', color: '#8A6A20', marginBottom: 7 }}>
              WHAT IT COSTS
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {cons.map((c) => (
                <div key={c} style={{ display: 'flex', gap: 7, fontSize: 11.8, lineHeight: 1.5, color: '#4A4C3E' }}>
                  <span style={{ color: '#B08C1E', flex: 'none' }}>▸</span>
                  <span>{c}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div style={{ fontSize: 12.6, lineHeight: 1.62, color: '#33352B', borderTop: '1px solid #DEE3B9', paddingTop: 12 }}>
          <span style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.1em', color: '#8A8C7C', marginRight: 8 }}>
            JUDGE
          </span>
          {judging
            ? 'Judge still deciding… the rationale will appear here.'
            : judge?.rationale ?? 'No judge rationale stored for this comparison.'}
        </div>
      </div>
    </div>
  )
}
