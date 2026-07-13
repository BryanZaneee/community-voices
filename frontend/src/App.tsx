import { useCallback, useEffect, useState } from 'react'
import { api, type Comparison, type Doc, type Embeddings, type Stats, type Status } from './api'
import { CEILS, STAGE_KEYS, useGeneration, type RunState, type StageUi } from './runstate'
import { useMeshShader } from './useMeshShader'
import { pickDoc, weekRange } from './viewmodel'
import { DISPLAY, MONO, whiteBtn } from './ui'
import { Sidebar, type TabKey } from './components/Sidebar'
import { ReportTab } from './tabs/ReportTab'
import { EmbeddingsTab } from './tabs/EmbeddingsTab'
import { AbTab } from './tabs/AbTab'
import { IngestTab } from './tabs/IngestTab'
import { HelpTab } from './tabs/HelpTab'

const TITLES: Record<TabKey, string> = {
  report: 'Weekly report',
  embed: 'Embeddings',
  ab: 'A/B: RAG vs LLM-only',
  ingest: 'Ingestion',
  help: 'Help: how to read this',
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [week, setWeek] = useState('')
  const [doc, setDoc] = useState<Doc | null>(null)
  const [comp, setComp] = useState<Comparison | null>(null)
  const [emb, setEmb] = useState<Embeddings | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [tab, setTab] = useState<TabKey>('report')
  const [sideOpen, setSideOpen] = useState(true)
  const [abBusy, setAbBusy] = useState(false)
  const [abError, setAbError] = useState<string | null>(null)
  const [ingestBusy, setIngestBusy] = useState(false)
  const [ingestError, setIngestError] = useState<string | null>(null)
  const [selectedModel, setSelectedModel] = useState('')
  const [sourceBusy, setSourceBusy] = useState(false)
  const [sourceError, setSourceError] = useState<string | null>(null)

  const refreshRetrievalViews = useCallback(() => {
    api.stats().then(setStats).catch(() => {})
    api.embeddings().then(setEmb).catch(() => {})
  }, [])

  // true from regenerate-start until the blind judge's verdict arrives
  const [judging, setJudging] = useState(false)
  const gen = useGeneration(
    status,
    (d) => {
      setDoc(d)
      refreshRetrievalViews()
    },
    (c) => {
      setJudging(false)
      if (c) setComp(c)
    },
  )
  const { showDone, showIdle } = gen

  // boot
  useEffect(() => {
    api.status().then((s) => {
      setStatus(s)
      setWeek(s.weeks[0]?.week_start ?? '')
    }).catch(() => {})
    api.latestComparison('rag_vs_baseline').then(setComp).catch(() => {})
    refreshRetrievalViews()
  }, [refreshRetrievalViews])

  // keep the picked model valid as `status` (re)loads — default to the
  // first available model, re-sync if the current pick drops out of it
  useEffect(() => {
    const available = status?.models_available ?? []
    if (available.length && !available.includes(selectedModel)) {
      setSelectedModel(available[0])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  // load the selected week's newest doc; show it in the done state
  useEffect(() => {
    if (!week) return
    let cancelled = false
    api.documents(week).then((docs) => {
      if (cancelled) return
      const d = pickDoc(docs, week)
      setDoc(d)
      if (d) showDone()
      else showIdle()
    }).catch(() => {})
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [week])

  const running = gen.run.phase === 'run'

  // Keep the takeover mounted ~900ms into 'done' so the write→done shader
  // crossfade is visible during the handoff to the report.
  const [overlay, setOverlay] = useState(false)
  useEffect(() => {
    if (gen.run.phase === 'run') setOverlay(true)
    else if (gen.run.phase === 'done' && overlay) {
      const id = setTimeout(() => setOverlay(false), 950)
      return () => clearTimeout(id)
    } else setOverlay(false)
  }, [gen.run.phase, overlay])
  const canGenerate = !!selectedModel && !running

  const onGenerate = () => {
    if (!canGenerate || !week) return
    setTab('report')
    setJudging(true)
    gen.start(week, selectedModel)
  }

  const onRunAb = async () => {
    if (!selectedModel || abBusy) return
    setAbBusy(true)
    setAbError(null)
    try {
      setComp(
        await api.compare({ week_start: week, model_key: selectedModel }),
      )
      refreshRetrievalViews()
    } catch (e) {
      setAbError((e as Error).message)
    } finally {
      setAbBusy(false)
    }
  }

  const onRunIngest = async () => {
    if (ingestBusy) return
    setIngestBusy(true)
    setIngestError(null)
    try {
      await api.ingestWeek()
      setStatus(await api.status())
      refreshRetrievalViews()
    } catch (e) {
      setIngestError((e as Error).message)
    } finally {
      setIngestBusy(false)
    }
  }

  const onSwitchSource = async (sourceKey: string) => {
    if (sourceBusy) return
    setSourceBusy(true)
    setSourceError(null)
    try {
      const { weeks } = await api.ingestSource(sourceKey)
      setStatus(await api.status())
      setWeek(weeks[0]?.week_start ?? '')
      setComp(null)
      refreshRetrievalViews()
    } catch (e) {
      setSourceError((e as Error).message)
    } finally {
      setSourceBusy(false)
    }
  }

  const selectedWeek = status?.weeks.find((w) => w.week_start === week) ?? null
  const hasReport = gen.run.phase === 'done' && !!doc
  const currentSourceKey =
    status?.source === 'hackernews'
      ? 'hackernews'
      : `lemmy:${(status?.subreddit ?? '').split('@')[0]}`

  return (
    <div
      className="print-scroll"
      style={{
        display: 'flex', height: '100vh', background: '#FAFAF7',
        color: '#16180F', overflow: 'hidden',
      }}
    >
      <Sidebar
        status={status}
        tab={tab}
        onTab={setTab}
        open={sideOpen && !running}
        onToggle={() => setSideOpen(!sideOpen)}
        run={gen.run}
        stages={gen.stages}
        onGenerate={onGenerate}
        shadeKey={gen.shadeKey}
        currentSourceKey={currentSourceKey}
        onSwitchSource={onSwitchSource}
        sourceBusy={sourceBusy}
        sourceError={sourceError}
        selectedModel={selectedModel}
        onModel={setSelectedModel}
      />

      <main
        className="print-scroll"
        style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, position: 'relative' }}
      >
        <header
          data-noprint="true"
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            gap: 16, padding: '16px 28px', borderBottom: '1px solid #E7E7DD',
            background: '#FAFAF7', flex: 'none',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {!sideOpen && !running && (
              <button
                onClick={() => setSideOpen(true)}
                title="Show sidebar"
                className="btn-white"
                style={{
                  width: 32, height: 32, borderRadius: 9, border: '1px solid #D8D9CB',
                  background: '#FFFFFF', cursor: 'pointer', display: 'grid',
                  placeItems: 'center', color: '#5F6153', fontSize: 13,
                  lineHeight: 1, padding: 0, flex: 'none',
                }}
              >
                »
              </button>
            )}
            <div>
              <div style={{ fontFamily: DISPLAY, fontSize: 19, fontWeight: 700, letterSpacing: '-.01em' }}>
                {TITLES[tab]}
              </div>
              <div
                style={{
                  fontFamily: MONO, fontSize: 10.5, color: '#8A8C7C', marginTop: 2,
                  display: 'flex', alignItems: 'center', gap: 6,
                }}
              >
                <span>Week of</span>
                <select
                  value={week}
                  disabled={running}
                  onChange={(e) => setWeek(e.target.value)}
                  style={{
                    fontFamily: MONO, fontSize: 10.5, color: '#3A421A',
                    border: 'none', background: 'transparent', cursor: 'pointer',
                    padding: 0, textDecoration: 'underline',
                  }}
                >
                  {status?.weeks.map((w) => (
                    <option key={w.week_start} value={w.week_start}>
                      {weekRange(w.week_start, w.week_end)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
          {tab === 'report' && (
            <div
              style={{
                display: 'flex', gap: 8,
                opacity: hasReport ? 1 : 0.4,
                pointerEvents: hasReport ? 'auto' : 'none',
              }}
            >
              <a
                href={doc ? `api/documents/${doc.id}/download` : '#'}
                className="btn-white"
                style={{ ...whiteBtn, textDecoration: 'none', display: 'inline-block' }}
              >
                ↓ .md
              </a>
              <button onClick={() => window.print()} className="btn-white" style={whiteBtn}>
                ↓ PDF
              </button>
            </div>
          )}
        </header>

        <div className="print-scroll" style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
          <div style={{ padding: '24px 28px 56px', maxWidth: 1120 }}>
            {tab === 'report' && (
              <ReportTab
                status={status}
                week={selectedWeek}
                doc={doc}
                run={gen.run}
                canGenerate={canGenerate}
                onGenerate={onGenerate}
                onAb={() => setTab('ab')}
                error={gen.error}
              />
            )}
            {tab === 'embed' && <EmbeddingsTab emb={emb} stats={stats} />}
            {tab === 'ab' && (
              <AbTab
                comp={comp}
                judging={judging}
                canRun={!!selectedModel}
                busy={abBusy}
                onRun={onRunAb}
                error={abError}
              />
            )}
            {tab === 'ingest' && (
              <IngestTab
                status={status}
                canPull={status?.can_pull_live ?? false}
                busy={ingestBusy}
                onRunNow={onRunIngest}
                error={ingestError}
              />
            )}
            {tab === 'help' && <HelpTab status={status} />}
          </div>
        </div>

        {overlay && <Takeover run={gen.run} stages={gen.stages} shadeKey={gen.shadeKey} />}
      </main>
    </div>
  )
}

/** Fullscreen generating takeover (animationStyle = "fullscreen takeover"):
 * covers the main area with the stage shader while the pipeline runs. */
function Takeover({ run, stages, shadeKey }: { run: RunState; stages: StageUi[]; shadeKey: string }) {
  // Blend continuously from this stage's palette toward the next one's as
  // stage-local progress advances (prog is cumulative, hence the CEILS math).
  const floor = run.stage === 0 ? 0 : CEILS[run.stage - 1]
  const ceil = CEILS[run.stage] ?? 1
  const t = (run.prog - floor) / Math.max(0.001, ceil - floor)
  const next = STAGE_KEYS[run.stage + 1] ?? 'done'
  const setShaderEl = useMeshShader(
    shadeKey,
    false,
    run.phase === 'run' ? { toKey: next, t } : undefined,
  )
  const done = run.phase === 'done'
  const cur = stages[run.stage]
  const pct = Math.round(run.prog * 100)
  return (
    <div
      style={{
        position: 'absolute', inset: 0, zIndex: 40, animation: 'ccFade .35s ease',
        opacity: done ? 0 : 1, transition: 'opacity .9s ease',
        pointerEvents: done ? 'none' : undefined,
      }}
    >
      <div ref={setShaderEl} style={{ position: 'absolute', inset: 0 }} />
      <div
        style={{
          position: 'absolute', inset: 0,
          background: 'linear-gradient(180deg,rgba(250,250,247,.1) 0%,rgba(250,250,247,.6) 100%)',
        }}
      />
      <div
        style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 12,
          textAlign: 'center', padding: '0 40px',
        }}
      >
        <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '.16em', color: '#3A421A' }}>
          STAGE {run.stage + 1} / {STAGE_KEYS.length}
        </div>
        <div style={{ fontFamily: DISPLAY, fontSize: 52, fontWeight: 700, letterSpacing: '-.025em', lineHeight: 1 }}>
          {cur?.label}
        </div>
        <div style={{ fontSize: 15, color: '#33352B' }}>{cur?.desc}</div>
        <div style={{ fontFamily: MONO, fontSize: 11.5, color: '#5F6153' }}>{cur?.detail}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 14 }}>
          <div
            style={{
              width: 320, height: 4, borderRadius: 2,
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
    </div>
  )
}
