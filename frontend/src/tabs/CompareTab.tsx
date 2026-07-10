import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, type Comparison, type Status } from '../api'
import { DocMeta } from './DocumentTab'

const KINDS = [
  { key: 'rag_vs_baseline', label: 'RAG vs no-RAG' },
  { key: 'model_vs_model', label: 'Model vs model' },
  { key: 'retrieval_vs_retrieval', label: 'Retrieval vs retrieval' },
] as const

const CRITERIA = [
  ['specificity', 'Specificity'],
  ['evidence', 'Evidence'],
  ['temporal_grounding', 'Temporal grounding'],
  ['usefulness', 'Usefulness'],
] as const

const RETRIEVAL_MODES = ['hybrid', 'vector', 'bm25']

function sideLabel(comp: Comparison, side: 'a' | 'b', models: Status['models']) {
  const doc = side === 'a' ? comp.doc_a : comp.doc_b
  if (comp.kind === 'rag_vs_baseline')
    return doc.mode === 'rag' ? 'With RAG' : 'Without RAG'
  if (comp.kind === 'model_vs_model')
    return models[doc.model_key]?.label ?? doc.model_key
  return `retrieval: ${doc.retrieval_mode}`
}

export default function CompareTab({
  status,
  week,
}: {
  status: Status
  week: string
}) {
  const [kind, setKind] = useState<string>('rag_vs_baseline')
  const [comp, setComp] = useState<Comparison | null>(null)
  const [modelA, setModelA] = useState(status.models_available[0] ?? '')
  const [modelB, setModelB] = useState(
    status.models_available[1] ?? status.models_available[0] ?? '',
  )
  const [retrA, setRetrA] = useState('hybrid')
  const [retrB, setRetrB] = useState('bm25')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .latestComparison(kind)
      .then(setComp)
      .catch(() => setComp(null))
  }, [kind])

  const run = async () => {
    setBusy(true)
    setError('')
    try {
      setComp(
        await api.compare({
          week_start: week,
          kind,
          model_a: modelA,
          model_b: kind === 'model_vs_model' ? modelB : undefined,
          retrieval_a: retrA,
          retrieval_b: retrB,
        }),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const judge = comp?.judge
  const winnerLabel =
    comp && judge
      ? judge.winner === 'tie'
        ? 'Judge calls it a tie'
        : `Winner: ${sideLabel(comp, judge.winner, status.models)}`
      : null

  return (
    <>
      <div className="panel">
        <div className="panel-title">A/B comparison · week of {week}</div>
        <div className="controls" style={{ marginBottom: 6 }}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => (
              <option key={k.key} value={k.key}>
                {k.label}
              </option>
            ))}
          </select>

          <span className="field-label">A</span>
          {kind === 'retrieval_vs_retrieval' ? (
            <select value={retrA} onChange={(e) => setRetrA(e.target.value)}>
              {RETRIEVAL_MODES.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          ) : (
            <select value={modelA} onChange={(e) => setModelA(e.target.value)}>
              {status.models_available.map((key) => (
                <option key={key} value={key}>
                  {status.models[key]?.label ?? key}
                </option>
              ))}
            </select>
          )}

          {kind !== 'rag_vs_baseline' && (
            <>
              <span className="field-label">B</span>
              {kind === 'retrieval_vs_retrieval' ? (
                <select value={retrB} onChange={(e) => setRetrB(e.target.value)}>
                  {RETRIEVAL_MODES.map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              ) : (
                <select value={modelB} onChange={(e) => setModelB(e.target.value)}>
                  {status.models_available.map((key) => (
                    <option key={key} value={key}>
                      {status.models[key]?.label ?? key}
                    </option>
                  ))}
                </select>
              )}
            </>
          )}

          <button
            className="btn primary"
            onClick={run}
            disabled={busy || status.models_available.length === 0}
          >
            {busy && <span className="spinner" />}
            {busy ? 'Generating both sides…' : 'Run comparison'}
          </button>
        </div>
        {error && <div className="error-note">{error}</div>}

        {comp && judge && (
          <>
            <div style={{ margin: '14px 0 6px' }}>
              <span className="winner-badge">{winnerLabel}</span>
              {comp.extra?.chunk_overlap_jaccard != null && (
                <span className="chip teal" style={{ marginLeft: 10 }}>
                  chunk overlap {Math.round(comp.extra.chunk_overlap_jaccard * 100)}%
                </span>
              )}
            </div>
            {judge.scores && (
              <div className="scorebars">
                {CRITERIA.map(([key, label]) => (
                  <div className="scorebar" key={key}>
                    <span>{label}</span>
                    {(['a', 'b'] as const).map((side) => {
                      const v = judge.scores![side][key]
                      return (
                        <div key={side} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div className="bar-track" style={{ flex: 1 }}>
                            <div
                              className={`bar-fill ${side}`}
                              style={{ width: `${(v / 5) * 100}%` }}
                            />
                          </div>
                          <span style={{ width: 24 }}>{v}/5</span>
                        </div>
                      )
                    })}
                  </div>
                ))}
                <div className="scorebar" style={{ color: 'var(--text-faint)' }}>
                  <span />
                  <span>A · {comp && sideLabel(comp, 'a', status.models)}</span>
                  <span>B · {comp && sideLabel(comp, 'b', status.models)}</span>
                </div>
              </div>
            )}
            <p style={{ color: 'var(--text-dim)', fontSize: 14 }}>
              {judge.rationale}
            </p>
          </>
        )}
      </div>

      {comp ? (
        <div className="split" style={{ marginTop: 18 }}>
          {(['a', 'b'] as const).map((side) => {
            const doc = side === 'a' ? comp.doc_a : comp.doc_b
            return (
              <div className="panel" key={side}>
                <div className="panel-title">
                  {side.toUpperCase()} · {sideLabel(comp, side, status.models)}
                </div>
                <DocMeta doc={doc} models={status.models} />
                <div className="doc small">
                  <ReactMarkdown>{doc.content_md}</ReactMarkdown>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="panel" style={{ marginTop: 18 }}>
          <div className="empty">
            No stored comparison of this kind yet — run one above.
          </div>
        </div>
      )}
    </>
  )
}
