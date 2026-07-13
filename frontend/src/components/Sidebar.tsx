import type { Status } from '../api'
import { ACCENT, communityIdentity, fmt } from '../viewmodel'
import { DISPLAY, MONO } from '../ui'
import { useMeshShader } from '../useMeshShader'
import type { RunState, StageUi } from '../runstate'

export const NAVDEF = [
  { key: 'report', label: 'Weekly report', shapeR: '2px', shapeTf: 'none', fill: true, split: false },
  { key: 'ab', label: 'A/B: RAG vs LLM', shapeR: '2px', shapeTf: 'none', fill: false, split: true },
  { key: 'embed', label: 'Embeddings', shapeR: '50%', shapeTf: 'none', fill: true, split: false },
  { key: 'ingest', label: 'Ingestion', shapeR: '2px', shapeTf: 'rotate(45deg)', fill: true, split: false },
  { key: 'help', label: 'Help', shapeR: '50%', shapeTf: 'none', fill: false, split: false },
] as const

export type TabKey = (typeof NAVDEF)[number]['key']

const VEIL =
  'linear-gradient(180deg,rgba(255,255,255,.55) 0%,rgba(255,255,255,.28) 55%,rgba(255,255,255,.16) 100%)'

export function Sidebar({
  status,
  tab,
  onTab,
  open,
  onToggle,
  run,
  stages,
  onGenerate,
  shadeKey,
  currentSourceKey,
  onSwitchSource,
  sourceBusy,
  sourceError,
  selectedModel,
  onModel,
}: {
  status: Status | null
  tab: TabKey
  onTab: (t: TabKey) => void
  open: boolean
  onToggle: () => void
  run: RunState
  stages: StageUi[]
  onGenerate: () => void
  shadeKey: string
  currentSourceKey: string
  onSwitchSource: (key: string) => void
  sourceBusy: boolean
  sourceError: string | null
  selectedModel: string
  onModel: (key: string) => void
}) {
  const setShaderEl = useMeshShader(shadeKey, true)
  const ident = communityIdentity(status?.community ?? null, status?.source)
  const running = run.phase === 'run'
  const modelKeys = status?.model_keys ?? Object.keys(status?.models ?? {})
  const available = new Set(status?.models_available ?? [])
  const sources = status?.sources ?? []
  const canGenerate = available.size > 0 && !running
  const curStage = stages[run.stage]

  return (
    <aside
      style={{
        width: open ? 274 : 0,
        flex: 'none',
        minHeight: 0,
        overflow: 'hidden',
        transition: 'width .65s cubic-bezier(.4,0,.2,1)',
      }}
    >
      <div
        style={{
          width: 274,
          height: '100%',
          position: 'relative',
          borderRight: '1px solid #E7E7DD',
          background: '#FFFFFF',
          overflow: 'hidden',
        }}
      >
        <div ref={setShaderEl} style={{ position: 'absolute', inset: 0 }} />
        <div style={{ position: 'absolute', inset: 0, background: VEIL }} />
        <div
          style={{
            position: 'relative',
            zIndex: 1,
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            minHeight: 0,
            overflowY: 'auto',
          }}
        >
          {/* logo row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '20px 16px 16px 20px' }}>
            <div
              style={{
                width: 28, height: 28, borderRadius: 9, background: '#16180F',
                display: 'grid', placeItems: 'center', flex: 'none',
              }}
            >
              <div style={{ width: 11, height: 11, borderRadius: '50%', background: '#9CC9A8' }} />
            </div>
            <div>
              <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 15, letterSpacing: '-.01em', lineHeight: 1.1 }}>
                Community Voices
              </div>
            </div>
            <button
              onClick={onToggle}
              title="Hide sidebar"
              aria-label="Hide sidebar"
              className="btn-white"
              style={{
                marginLeft: 'auto', width: 28, height: 28, borderRadius: 8,
                border: '1px solid #E1E3D2', background: 'rgba(255,255,255,.7)',
                cursor: 'pointer', display: 'grid', placeItems: 'center',
                color: '#5F6153', fontSize: 13, lineHeight: 1, padding: 0, flex: 'none',
              }}
            >
              «
            </button>
          </div>

          {/* identity card — click to switch which community/site the
              report is generated from; full stats live in the report's
              community-pulse card */}
          <div
            style={{
              margin: '0 16px 16px', padding: '12px 14px', border: '1px solid #E7E7DD',
              borderRadius: 12, background: 'rgba(252,252,249,.72)', backdropFilter: 'blur(8px)',
              display: 'flex', alignItems: 'center', gap: 10, opacity: sourceBusy ? 0.6 : 1,
            }}
          >
            <div
              style={{
                width: 34, height: 34, borderRadius: '50%', background: '#EEF1DA',
                border: '1px solid #DEE3B9', display: 'grid', placeItems: 'center',
                fontFamily: DISPLAY, fontWeight: 700, fontSize: 16, color: '#1E5940', flex: 'none',
              }}
            >
              {ident.initial}
            </div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <select
                aria-label="Source"
                className="source-select"
                value={currentSourceKey}
                disabled={sourceBusy || running || sources.length === 0}
                onChange={(e) => onSwitchSource(e.target.value)}
                title="Switch source (re-ingests from scratch)"
                style={{
                  fontFamily: DISPLAY, fontWeight: 600, fontSize: 14, lineHeight: 1.15,
                  width: '100%',
                }}
              >
                {!sources.some((s) => s.key === currentSourceKey) && (
                  <option value={currentSourceKey}>{ident.name}</option>
                )}
                {sources.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
              <div style={{ fontFamily: MONO, fontSize: 10, color: sourceError ? '#A6522E' : '#8A8C7C' }}>
                {sourceBusy ? 'switching source…' : sourceError ?? 'source of this report · click to switch'}
              </div>
            </div>
          </div>

          {/* nav */}
          <nav style={{ padding: '0 12px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            {NAVDEF.map((n) => {
              const act = tab === n.key
              const shapeCol = act ? '#1E5940' : '#A2A494'
              return (
                <button
                  key={n.key}
                  onClick={() => onTab(n.key)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 11, padding: '9px 11px',
                    borderRadius: 9,
                    border: `1px solid ${act ? '#DEE3B9' : 'transparent'}`,
                    background: act ? '#F3F5E3' : 'transparent',
                    color: act ? '#3A421A' : '#5F6153',
                    fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    textAlign: 'left', width: '100%',
                  }}
                >
                  <span
                    style={{
                      width: 9, height: 9, flex: 'none',
                      borderRadius: n.shapeR,
                      background: n.split
                        ? `linear-gradient(90deg, ${shapeCol} 50%, transparent 50%)`
                        : n.fill
                          ? shapeCol
                          : 'transparent',
                      border: `1.5px solid ${shapeCol}`,
                      transform: n.shapeTf,
                    }}
                  />
                  <span style={{ flex: 1 }}>{n.label}</span>
                </button>
              )
            })}
          </nav>

          <div style={{ flex: 1 }} />

          {/* model + generate */}
          <div style={{ padding: '0 16px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <select
              aria-label="Model"
              className="model-select"
              value={selectedModel}
              disabled={available.size === 0 || running}
              onChange={(e) => onModel(e.target.value)}
              title={available.size === 0 ? 'Add an API key in .env to generate' : 'Model'}
            >
              {modelKeys.length === 0 ? (
                <option>no models configured</option>
              ) : (
                modelKeys.map((k) => (
                  <option key={k} value={k} disabled={!available.has(k)}>
                    {status?.models[k]?.label ?? k}
                    {!available.has(k) ? ' (needs API key)' : ''}
                  </option>
                ))
              )}
            </select>
            <button
              onClick={onGenerate}
              disabled={!canGenerate}
              className={canGenerate ? 'btn-brighten' : undefined}
              title={available.size === 0 ? 'Add an API key in .env to generate' : undefined}
              style={{
                width: '100%', padding: '12px 14px', borderRadius: 10,
                border: `1px solid ${running || !canGenerate ? '#E1E3D2' : '#1E5940'}`,
                background: running || !canGenerate ? '#EDEFDF' : ACCENT,
                color: running || !canGenerate ? '#6B6D5F' : '#FFFFFF',
                fontFamily: DISPLAY, fontWeight: 600, fontSize: 13.5,
                cursor: canGenerate ? 'pointer' : 'default',
                letterSpacing: '.01em',
              }}
            >
              {running
                ? `Generating: ${curStage?.label ?? ''}…`
                : run.phase === 'done'
                  ? 'Regenerate report'
                  : 'Generate weekly report'}
            </button>
          </div>
          <div
            style={{
              padding: '11px 20px 16px', borderTop: '1px solid #EFEFE6',
              fontFamily: MONO, fontSize: 9.5, color: '#8A8C7C', lineHeight: 1.6,
            }}
          >
            sqlite-vec · {fmt(status?.chunks_total)} chunks
            <br />
            last ingest {status?.ingested_at?.replace('T', ' ').replace('+00:00', ' UTC') ?? '-'}
          </div>
        </div>
      </div>
    </aside>
  )
}
