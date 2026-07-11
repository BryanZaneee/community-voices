import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, type Doc, type Status } from '../api'

export function DocMeta({ doc, models }: { doc: Doc; models: Status['models'] }) {
  return (
    <div className="meta-row">
      <span className={`chip ${doc.mode === 'rag' ? 'accent' : ''}`}>
        {doc.mode === 'rag' ? `RAG · ${doc.retrieval_mode}` : 'no RAG'}
      </span>
      <span className="chip">{models[doc.model_key]?.label ?? doc.model_key}</span>
      <span className="chip">{(doc.latency_ms / 1000).toFixed(1)}s</span>
      <span className="chip">
        {doc.input_tokens}→{doc.output_tokens} tok
      </span>
      {doc.cost_usd != null && (
        <span className="chip">${doc.cost_usd.toFixed(4)}</span>
      )}
      {doc.retrieved_chunk_ids && (
        <span className="chip teal">{doc.retrieved_chunk_ids.length} chunks</span>
      )}
    </div>
  )
}

export default function DocumentTab({
  status,
  week,
}: {
  status: Status
  week: string
}) {
  const [doc, setDoc] = useState<Doc | null>(null)
  const [model, setModel] = useState(
    status.models_available[0] ?? 'claude-opus-4-8',
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!week) return
    api
      .documents(week)
      .then((docs) =>
        setDoc(
          docs.find((d) => d.mode === 'rag' && d.retrieval_mode === 'hybrid') ??
            docs.find((d) => d.mode === 'rag') ??
            docs[0] ??
            null,
        ),
      )
      .catch(() => setDoc(null))
  }, [week])

  const regenerate = async () => {
    setBusy(true)
    setError('')
    try {
      setDoc(await api.generate({ week_start: week, mode: 'rag', model_key: model }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const canGenerate = status.models_available.length > 0

  return (
    <div className="panel">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
          marginBottom: 18,
        }}
      >
        <div className="panel-title" style={{ margin: 0 }}>
          The document · week of {week}
        </div>
        <div className="controls">
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {Object.entries(status.models).map(([key, m]) => (
              <option
                key={key}
                value={key}
                disabled={!status.models_available.includes(key)}
              >
                {m.label}
                {!status.models_available.includes(key) ? ' (no key)' : ''}
              </option>
            ))}
          </select>
          <button
            className="btn primary"
            onClick={regenerate}
            disabled={busy || !canGenerate}
            title={canGenerate ? '' : 'No LLM API key configured'}
          >
            {busy && <span className="spinner" />}
            {busy ? 'Writing…' : 'Regenerate'}
          </button>
          {doc && (
            <a
              className="btn"
              href={`/api/documents/${doc.id}/download`}
              style={{ textDecoration: 'none' }}
            >
              ↓ .md
            </a>
          )}
        </div>
      </div>

      {error && <div className="error-note">{error}</div>}

      {doc ? (
        <>
          <DocMeta doc={doc} models={status.models} />
          <div className="doc">
            <ReactMarkdown>{doc.content_md}</ReactMarkdown>
          </div>
        </>
      ) : (
        <div className="empty">
          No document for this week yet — hit Regenerate to write one.
        </div>
      )}
    </div>
  )
}
