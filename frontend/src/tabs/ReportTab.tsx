import ReactMarkdown from 'react-markdown'
import type { Doc, Status, Week } from '../api'
import type { RunState, StageUi } from '../runstate'
import { useMeshShader } from '../useMeshShader'
import { ACCENT, citationCount, CLUSTER_COLORS, fmt, fmtSecs, weekRange } from '../viewmodel'
import { card, DISPLAY, kicker, MONO, pill, RichText } from '../ui'

const GRADE_STYLE: Record<string, { bg: string; fg: string }> = {
  hit: { bg: '#EEF1DA', fg: '#3A421A' },
  partial: { bg: '#F5EEDD', fg: '#8A6A20' },
  miss: { bg: '#F4F4EF', fg: '#6B6D5F' },
}

export function ReportTab({
  status,
  week,
  doc,
  run,
  stages,
  shadeKey,
  canGenerate,
  onGenerate,
  onAb,
  error,
}: {
  status: Status | null
  week: Week | null
  doc: Doc | null
  run: RunState
  stages: StageUi[]
  shadeKey: string
  canGenerate: boolean
  onGenerate: () => void
  onAb: () => void
  error: string | null
}) {
  const setShaderEl = useMeshShader(shadeKey)
  const range = week ? weekRange(week.week_start, week.week_end) : '—'
  const cur = stages[run.stage]
  const report = doc?.report_json ?? null
  const heroH = run.phase === 'idle' ? 330 : run.phase === 'run' ? 400 : 54
  const chunksUsed = doc?.retrieved_chunk_ids?.length ?? 0
  const pct = Math.round(run.prog * 100)

  return (
    <div>
      {/* hero: idle / running / done */}
      <div
        data-noprint="true"
        style={{
          position: 'relative', height: heroH, borderRadius: 16, overflow: 'hidden',
          border: '1px solid #E1E3D2',
          transition: 'height .55s cubic-bezier(.4,0,.2,1)', marginBottom: 24,
        }}
      >
        <div ref={setShaderEl} style={{ position: 'absolute', inset: 0 }} />
        <div
          style={{
            position: 'absolute', inset: 0,
            background:
              'linear-gradient(180deg,rgba(250,250,247,.12) 0%,rgba(250,250,247,.55) 100%)',
          }}
        />
        {run.phase === 'idle' && (
          <div
            style={{
              position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
              justifyContent: 'center', padding: '0 44px', gap: 12,
            }}
          >
            <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: '.16em', color: '#3A421A' }}>
              WEEK OF {range.toUpperCase()}
            </div>
            <div
              style={{
                fontFamily: DISPLAY, fontSize: 33, fontWeight: 700,
                letterSpacing: '-.02em', lineHeight: 1.08, maxWidth: 560,
              }}
            >
              Generate this week&rsquo;s
              <br />
              Community Voices report
            </div>
            <div style={{ fontSize: 13.5, color: '#3F4136', maxWidth: 480, lineHeight: 1.55 }}>
              Crawl → reduce → embed → retrieve → write. Grounded on{' '}
              {fmt(status?.chunks_total)} chunks of what the community actually
              said, scoped to this week.
            </div>
            <div style={{ marginTop: 6 }}>
              <button
                onClick={onGenerate}
                disabled={!canGenerate}
                className="btn-olive"
                title={!canGenerate ? 'Add an API key in .env to generate' : undefined}
                style={{
                  padding: '13px 24px', borderRadius: 11,
                  border: `1px solid ${canGenerate ? '#5A661A' : '#E1E3D2'}`,
                  background: canGenerate ? ACCENT : '#EDEFDF',
                  color: canGenerate ? '#FFFFFF' : '#6B6D5F',
                  fontFamily: DISPLAY, fontWeight: 600, fontSize: 14.5,
                  cursor: canGenerate ? 'pointer' : 'default',
                  boxShadow: canGenerate ? '0 2px 10px rgba(90,102,26,.25)' : 'none',
                }}
              >
                {canGenerate ? 'Generate report' : 'Generate report (needs an API key)'}
              </button>
            </div>
            {error && (
              <div style={{ fontFamily: MONO, fontSize: 11, color: '#A6522E' }}>
                last run failed: {error}
              </div>
            )}
          </div>
        )}
        {run.phase === 'run' && (
          <div
            style={{
              position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
              justifyContent: 'center', padding: '0 44px', gap: 10,
            }}
          >
            <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: '.16em', color: '#3A421A' }}>
              STAGE {run.stage + 1} / 5
            </div>
            <div style={{ fontFamily: DISPLAY, fontSize: 38, fontWeight: 700, letterSpacing: '-.02em', lineHeight: 1 }}>
              {cur?.label}
            </div>
            <div style={{ fontSize: 14, color: '#33352B' }}>{cur?.desc}</div>
            <div style={{ fontFamily: MONO, fontSize: 11, color: '#5F6153' }}>{cur?.detail}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 10 }}>
              <div
                style={{
                  width: 280, height: 4, borderRadius: 2,
                  background: 'rgba(22,24,15,.14)', overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    height: '100%', background: '#16180F', borderRadius: 2,
                    width: `${pct}%`, transition: 'width .1s linear',
                  }}
                />
              </div>
              <div style={{ fontFamily: MONO, fontSize: 11, color: '#3A421A' }}>{pct}%</div>
            </div>
          </div>
        )}
        {run.phase === 'done' && (
          <div
            style={{
              position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
              justifyContent: 'space-between', padding: '0 20px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: error ? '#A6522E' : ACCENT, flex: 'none' }} />
              <span
                style={{
                  fontFamily: MONO, fontSize: 11, color: error ? '#A6522E' : '#3A421A',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}
              >
                {error
                  ? `regenerate failed: ${error} — showing the stored report`
                  : `Report generated · ${fmtSecs(doc?.latency_ms)} · ${
                      chunksUsed > 0
                        ? `${chunksUsed} chunks retrieved`
                        : 'no retrieval (baseline)'
                    } · ${doc?.model_key}`}
              </span>
            </div>
            <button
              onClick={onGenerate}
              disabled={!canGenerate}
              className="link-btn"
              title={!canGenerate ? 'Add an API key in .env to regenerate' : undefined}
              style={{
                border: 'none', background: 'none', fontFamily: MONO, fontSize: 11,
                fontWeight: 600, color: canGenerate ? '#5A661A' : '#A2A494',
                cursor: canGenerate ? 'pointer' : 'default',
                textDecoration: 'underline', padding: 4,
              }}
            >
              Regenerate
            </button>
          </div>
        )}
      </div>

      {/* report body */}
      {run.phase === 'done' && doc && (
        <div
          style={{
            opacity: run.reveal ? 1 : 0,
            transform: run.reveal ? 'none' : 'translateY(14px)',
            transition: 'opacity .7s ease, transform .7s ease',
          }}
        >
          {report ? (
            <>
              <div style={{ maxWidth: 760 }}>
                <div style={{ fontSize: 12, color: '#8A8C7C', marginBottom: 14 }}>
                  Covering the past week, {range} · forecast for the week after
                </div>
                <h1
                  style={{
                    fontFamily: DISPLAY, fontSize: 30, fontWeight: 700,
                    letterSpacing: '-.02em', lineHeight: 1.15, margin: '0 0 10px',
                  }}
                >
                  {report.headline}
                </h1>
                <p style={{ fontSize: 14.5, lineHeight: 1.65, color: '#3F4136', margin: '0 0 26px' }}>
                  <RichText text={report.lede} />
                </p>
              </div>

              <PostsPerDay status={status} week={week} />

              <div style={{ ...kicker, fontSize: 10.5, letterSpacing: '.16em', marginBottom: 14 }}>
                WHAT THEY TALKED ABOUT
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 34 }}>
                {report.topics.map((t, i) => (
                  <div key={t.name} style={card()}>
                    <div
                      style={{
                        display: 'flex', alignItems: 'center', gap: 9,
                        marginBottom: 7, flexWrap: 'wrap',
                      }}
                    >
                      <span
                        style={{
                          width: 8, height: 8, borderRadius: '50%', flex: 'none',
                          background: CLUSTER_COLORS[i % CLUSTER_COLORS.length],
                        }}
                      />
                      <span style={{ fontFamily: DISPLAY, fontSize: 15.5, fontWeight: 600, letterSpacing: '-.01em' }}>
                        {t.name}
                      </span>
                      {t.threads != null && (
                        <span style={pill('#F4F4EF', '#6B6D5F')}>{t.threads} threads</span>
                      )}
                      {t.share_pct != null && (
                        <span style={pill('#EEF1DA', '#3A421A')}>{t.share_pct}% of discussion</span>
                      )}
                    </div>
                    <div style={{ fontSize: 12.8, lineHeight: 1.62, color: '#3F4136' }}>
                      <RichText text={t.summary} />
                    </div>
                  </div>
                ))}
              </div>

              {report.standouts.length > 0 && (
                <div style={{ ...card(), marginBottom: 26 }}>
                  <div style={{ ...kicker, marginBottom: 12 }}>STANDOUT THREADS</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                    {report.standouts.map((s) => (
                      <div key={s} style={{ display: 'flex', gap: 8, fontSize: 12.6, lineHeight: 1.55, color: '#3F4136' }}>
                        <span style={{ color: ACCENT, flex: 'none' }}>▸</span>
                        <span><RichText text={s} /></span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {report.prediction_review && report.prediction_review.length > 0 && (
                <div style={{ ...card(), marginBottom: 26 }}>
                  <div style={{ ...kicker, marginBottom: 12 }}>
                    LAST WEEK&rsquo;S PREDICTIONS — HOW DID THEY HOLD UP?
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {report.prediction_review.map((r) => {
                      const g = GRADE_STYLE[r.grade] ?? GRADE_STYLE.miss
                      return (
                        <div key={r.prediction} style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
                          <span style={{ ...pill(g.bg, g.fg), flex: 'none', textTransform: 'uppercase' }}>
                            {r.grade}
                          </span>
                          <div style={{ fontSize: 12.6, lineHeight: 1.55, color: '#3F4136' }}>
                            <span style={{ fontWeight: 600 }}>{r.prediction}</span> — <RichText text={r.evidence} />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              <div
                style={{
                  border: '1px solid #DEE3B9', borderRadius: 16, background: '#F6F8EA',
                  padding: '22px 22px 20px', marginBottom: 26,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 16 }}>
                  <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: '.16em', color: '#5A661A' }}>
                    NEXT WEEK PREDICTION
                  </div>
                  <div style={{ fontFamily: MONO, fontSize: 10, color: '#8A8C7C' }}>
                    forecast · the week after {range.split('–')[1]?.trim() ?? ''}
                  </div>
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: `repeat(${Math.min(3, report.predictions.length)}, 1fr)`,
                    gap: 12,
                  }}
                >
                  {report.predictions.map((p) => (
                    <div
                      key={p.title}
                      style={{
                        background: '#FFFFFF', border: '1px solid #E1E3D2', borderRadius: 12,
                        padding: '16px 16px 14px', display: 'flex', flexDirection: 'column', gap: 9,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span style={{ fontFamily: MONO, fontSize: 19, fontWeight: 600, color: '#3A421A' }}>
                          {p.confidence}%
                        </span>
                        <span style={{ fontFamily: MONO, fontSize: 8.5, letterSpacing: '.1em', color: '#A2A494' }}>
                          CONFIDENCE
                        </span>
                      </div>
                      <div style={{ height: 4, borderRadius: 2, background: '#EDEDE3' }}>
                        <div
                          style={{
                            height: '100%', width: `${p.confidence}%`,
                            background: ACCENT, borderRadius: 2,
                          }}
                        />
                      </div>
                      <div style={{ fontFamily: DISPLAY, fontSize: 14, fontWeight: 600, lineHeight: 1.3 }}>
                        {p.title}
                      </div>
                      <div style={{ fontSize: 11.8, lineHeight: 1.55, color: '#4A4C3E' }}>
                        <RichText text={p.rationale} />
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 2 }}>
                        {p.signals.map((sg) => (
                          <div
                            key={sg}
                            style={{
                              display: 'flex', gap: 6, fontFamily: MONO,
                              fontSize: 9.5, color: '#6B6D5F', lineHeight: 1.4,
                            }}
                          >
                            <span style={{ color: ACCENT }}>▸</span>
                            <span>{sg}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ fontFamily: MONO, fontSize: 10, color: '#A2A494', lineHeight: 1.6 }}>
                Grounded on {chunksUsed} retrieved chunks ·{' '}
                {citationCount(doc.content_md)} cited titles · {doc.model_key} ·{' '}
                {fmtSecs(doc.latency_ms)}. Methodology: crawl of the week&rsquo;s top
                threads → {fmt(week?.n_chunks)} chunks embedded (
                {status?.embedding_model ?? 'BM25 only'}) → retrieval scoped to the{' '}
                {range} window ({doc.retrieval_mode ?? '—'}) → digest &amp; forecast
                written by {doc.model_key}, claims citing post titles. See the{' '}
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault()
                    onAb()
                  }}
                >
                  A/B comparison
                </a>{' '}
                for the ungrounded baseline.
              </div>
            </>
          ) : (
            // docs generated before structured reports: render the markdown
            <div className="md-fallback">
              <ReactMarkdown>{doc.content_md}</ReactMarkdown>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function PostsPerDay({ status, week }: { status: Status | null; week: Week | null }) {
  if (!status || !week) return null
  const days = status.activity.filter(
    (a) => a.date >= week.week_start && a.date < week.week_end,
  )
  if (days.length === 0) return null
  const rawMax = Math.max(...days.map((d) => d.n_posts), 1)
  const yMax = Math.max(10, Math.ceil(rawMax / 10) * 10)
  return (
    <div style={{ ...card(), minWidth: 0, marginBottom: 30 }}>
      <div
        style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
          flexWrap: 'wrap', gap: 8, marginBottom: 14,
        }}
      >
        <div style={kicker}>
          POSTS / DAY — WEEK COVERED · {weekRange(week.week_start, week.week_end).toUpperCase()}
        </div>
        <div style={{ fontSize: 10, color: '#A2A494' }}>
          daily posting volume in the covered window
        </div>
      </div>
      <div style={{ display: 'flex', gap: 10 }}>
        <div
          style={{
            display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
            height: 94, fontFamily: MONO, fontSize: 8, color: '#A2A494',
            textAlign: 'right', flex: 'none',
          }}
        >
          <span>{yMax}</span>
          <span>{yMax / 2}</span>
          <span>0 posts</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 112, flex: 1, minWidth: 0 }}>
          {days.map((d) => (
            <div
              key={d.date}
              style={{
                flex: 1, minWidth: 0, overflow: 'hidden', display: 'flex',
                flexDirection: 'column', alignItems: 'center', gap: 5,
                height: '100%', justifyContent: 'flex-end',
              }}
            >
              <div
                style={{
                  width: '100%',
                  height: `${(d.n_posts / yMax) * 100}%`,
                  background: ACCENT,
                  borderRadius: '4px 4px 0 0',
                }}
              />
              <div style={{ fontFamily: MONO, fontSize: 8, color: '#A2A494', whiteSpace: 'nowrap' }}>
                {new Date(d.date + 'T00:00:00Z').toLocaleDateString('en-US', {
                  month: 'short', day: 'numeric', timeZone: 'UTC',
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
