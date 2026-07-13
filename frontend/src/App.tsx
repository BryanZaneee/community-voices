import { useCallback, useEffect, useState } from 'react'
import { api, type Comparison, type Doc, type Embeddings, type Stats, type Status } from './api'
import { useGeneration } from './runstate'
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
  ab: 'A/B — RAG vs LLM-only',
  ingest: 'Ingestion',
  help: 'Help — how to read this',
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

  const refreshRetrievalViews = useCallback(() => {
    api.stats().then(setStats).catch(() => {})
    api.embeddings().then(setEmb).catch(() => {})
  }, [])

  const gen = useGeneration(status, (d) => {
    setDoc(d)
    refreshRetrievalViews()
  })
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
  const model = status?.models_available[0] ?? ''
  const canGenerate = !!model && !running

  const onGenerate = () => {
    if (!canGenerate || !week) return
    setTab('report')
    gen.start(week, model)
  }

  const onRunAb = async () => {
    if (!model || abBusy) return
    setAbBusy(true)
    setAbError(null)
    try {
      setComp(
        await api.compare({ week_start: week, model_key: model }),
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

  const selectedWeek = status?.weeks.find((w) => w.week_start === week) ?? null
  const instance = status?.subreddit?.split('@')[1] ?? ''
  const hasReport = gen.run.phase === 'done' && !!doc

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
        open={sideOpen}
        onToggle={() => setSideOpen(!sideOpen)}
        run={gen.run}
        stages={gen.stages}
        onGenerate={onGenerate}
        shadeKey={gen.shadeKey}
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
            {!sideOpen && (
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
                <span>· {instance}</span>
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
                href={doc ? `/api/documents/${doc.id}/download` : '#'}
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
                stages={gen.stages}
                shadeKey={gen.shadeKey}
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
                canRun={!!model}
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
      </main>
    </div>
  )
}
