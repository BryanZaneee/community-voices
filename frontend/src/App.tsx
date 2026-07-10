import { useEffect, useState } from 'react'
import { MeshGradient } from '@paper-design/shaders-react'
import { api, type Status } from './api'
import DocumentTab from './tabs/DocumentTab'
import CompareTab from './tabs/CompareTab'
import EmbeddingsTab from './tabs/EmbeddingsTab'
import StatsTab from './tabs/StatsTab'

const TABS = ['Document', 'Compare', 'Embeddings', 'Stats'] as const
type Tab = (typeof TABS)[number]

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [week, setWeek] = useState<string>('')
  const [tab, setTab] = useState<Tab>('Document')
  const [pulling, setPulling] = useState(false)
  const [pullError, setPullError] = useState('')

  const refreshStatus = () =>
    api.status().then((s) => {
      setStatus(s)
      setWeek((w) => w || s.weeks[0]?.week_start || '')
      return s
    })

  useEffect(() => {
    refreshStatus().catch(() => setStatus(null))
  }, [])

  const pullLive = async () => {
    setPulling(true)
    setPullError('')
    try {
      const { weeks } = await api.ingestWeek()
      await refreshStatus()
      if (weeks[0]) setWeek(weeks[0].week_start)
    } catch (e) {
      setPullError(e instanceof Error ? e.message : String(e))
    } finally {
      setPulling(false)
    }
  }

  return (
    <>
      <MeshGradient
        className="bg-shader"
        colors={['#0b0d13', '#1b2030', '#3d2320', '#0e2b26']}
        distortion={0.9}
        swirl={0.6}
        speed={0.12}
      />
      <div className="bg-vignette" />
      <div className="shell">
        <header className="masthead">
          <div>
            <div className="kicker">
              <span className="dot" />
              RAG-powered weekly digest · r/{status?.subreddit ?? 'gaming'}
            </div>
            <h1>
              Community <em>Voices</em>
            </h1>
          </div>
          <div className="controls">
            <span className="field-label">Week</span>
            <select value={week} onChange={(e) => setWeek(e.target.value)}>
              {status?.weeks.map((w) => (
                <option key={w.week_start} value={w.week_start}>
                  {w.week_start} → {w.week_end} · {w.n_posts} posts
                </option>
              ))}
            </select>
            <button
              className="btn primary"
              onClick={pullLive}
              disabled={pulling || !status?.can_pull_live}
              title={
                status?.can_pull_live
                  ? 'Scrape the trailing 7 days from Reddit right now'
                  : 'Needs VOYAGE_API_KEY + REDDIT_CLIENT_ID/SECRET in .env'
              }
            >
              {pulling && <span className="spinner" />}
              {pulling ? 'Pulling…' : 'Pull this week live'}
            </button>
          </div>
        </header>

        {pullError && <div className="error-note">{pullError}</div>}

        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t}
              className={t === tab ? 'active' : ''}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </nav>

        {status === null ? (
          <div className="panel">
            <div className="empty">
              Backend not reachable — start it with{' '}
              <code>uvicorn app.main:app</code> in backend/.
            </div>
          </div>
        ) : (
          <>
            {tab === 'Document' && <DocumentTab status={status} week={week} />}
            {tab === 'Compare' && <CompareTab status={status} week={week} />}
            {tab === 'Embeddings' && <EmbeddingsTab />}
            {tab === 'Stats' && <StatsTab status={status} />}
          </>
        )}
      </div>
    </>
  )
}
