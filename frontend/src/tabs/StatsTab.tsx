import { useEffect, useState } from 'react'
import { api, type Stats, type Status } from '../api'

export default function StatsTab({ status }: { status: Status }) {
  const [stats, setStats] = useState<Stats | null>(null)

  useEffect(() => {
    api.stats().then(setStats)
  }, [])

  if (!stats) return <div className="panel"><div className="empty">Loading…</div></div>

  const coverage =
    stats.chunks_total > 0
      ? Math.round(
          ((stats.chunks_total - stats.chunks_never_retrieved) /
            stats.chunks_total) *
            100,
        )
      : 0

  return (
    <>
      <div className="tiles">
        <div className="tile">
          <div className="value">{stats.total_retrievals}</div>
          <div className="label">total retrievals</div>
        </div>
        <div className="tile">
          <div className="value">{stats.chunks_total}</div>
          <div className="label">chunks indexed</div>
        </div>
        <div className="tile">
          <div className="value">{coverage}%</div>
          <div className="label">of chunks ever retrieved</div>
        </div>
        <div className="tile">
          <div className="value">{stats.chunks_never_retrieved}</div>
          <div className="label">never retrieved</div>
        </div>
      </div>

      {stats.per_model.length > 0 && (
        <div className="panel">
          <div className="panel-title">Generation stats by model</div>
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th className="num">Docs</th>
                <th className="num">Avg latency</th>
                <th className="num">Avg input tok</th>
                <th className="num">Avg output tok</th>
              </tr>
            </thead>
            <tbody>
              {stats.per_model.map((m) => (
                <tr key={m.model_key}>
                  <td>{status.models[m.model_key]?.label ?? m.model_key}</td>
                  <td className="num">{m.docs}</td>
                  <td className="num">{(m.avg_latency_ms / 1000).toFixed(1)}s</td>
                  <td className="num">{m.avg_input_tokens}</td>
                  <td className="num">{m.avg_output_tokens}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="panel">
        <div className="panel-title">
          Most retrieved chunks — the voices the documents are built from
        </div>
        {stats.top_chunks.length === 0 ? (
          <div className="empty">Nothing retrieved yet — generate a document.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th className="num">Count</th>
                <th>Post · section</th>
                <th>Last retrieved</th>
              </tr>
            </thead>
            <tbody>
              {stats.top_chunks.map((c) => (
                <tr key={c.chunk_id}>
                  <td className="num" style={{ color: 'var(--accent)', fontWeight: 700 }}>
                    {c.retrieved_count}×
                  </td>
                  <td>
                    {c.title ?? c.chunk_id}
                    <span className="snippet">{c.snippet}</span>
                  </td>
                  <td style={{ fontFamily: 'var(--mono)', fontSize: 11.5, whiteSpace: 'nowrap' }}>
                    {c.last_retrieved_at?.replace('T', ' ').slice(0, 16)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
