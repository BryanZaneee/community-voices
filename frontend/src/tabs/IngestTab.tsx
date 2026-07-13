import type { Status } from '../api'
import { ACCENT, communityIdentity, fmt } from '../viewmodel'
import { card, DISPLAY, kicker, MONO, whiteBtn } from '../ui'

const STEPS = (status: Status | null) => {
  const ident = communityIdentity(status?.community ?? null, status?.source)
  const spec = status?.ingest_spec
  const isHn = status?.source === 'hackernews'
  return [
    {
      name: 'Scheduler',
      desc: 'One cron line runs the weekly crawl unattended (see README); manual runs from this page.',
      spec: 'cron 0 6 * * 1',
    },
    {
      name: 'Crawler',
      desc: `Walks the open ${isHn ? 'Algolia HN search API' : 'Lemmy API'} for ${ident.name}: top listings, then parallel comment fetches on threads with real discussion.`,
      spec: `${isHn ? 'algolia HN API' : 'lemmy API v3'} · ${spec?.workers ?? '-'} workers`,
    },
    {
      name: 'Reduce',
      desc: 'Keeps the top posts per week, skips low-discussion threads, drops bot/deleted comments, truncates walls of text.',
      spec: `top ${spec?.top_posts_per_week ?? '-'} posts/wk · ${spec?.comments_per_post ?? '-'} comments/post`,
    },
    {
      name: 'Chunk + embed',
      desc: 'Thread-aware chunking (post + best comments stay together), embedded in batches.',
      spec: status?.embedding_model ?? 'voyage-3-large',
    },
    {
      name: 'Vector store',
      desc: 'Upsert into sqlite-vec with stable content-derived chunk IDs; re-runs only embed what is new.',
      spec: 'sqlite-vec · BM25 hybrid',
    },
  ]
}

export function IngestTab({
  status,
  canPull,
  busy,
  onRunNow,
  error,
}: {
  status: Status | null
  canPull: boolean
  busy: boolean
  onRunNow: () => void
  error: string | null
}) {
  const report = status?.last_ingest ?? null
  const ingested = status?.ingested_at?.replace('T', ' ').replace('+00:00', ' UTC')
  const rawItems = report ? report.posts + (report.comments ?? 0) : null
  const funnel = report
    ? [
        { label: 'Raw items crawled (posts + comments)', value: rawItems!, display: fmt(rawItems) },
        { label: 'Documents (post + top comments)', value: report.posts, display: fmt(report.posts) },
        { label: 'Chunks after thread-aware chunking', value: report.chunks_total, display: fmt(report.chunks_total) },
        { label: 'New chunks embedded (rest already stored)', value: report.chunks_new, display: fmt(report.chunks_new) },
      ]
    : []
  const funnelMax = Math.max(1, ...funnel.map((f) => f.value))
  const duration =
    report?.fetch_s != null && report?.index_s != null
      ? `${Math.round(report.fetch_s + report.index_s)}s`
      : '-'
  const dropped =
    rawItems && report ? Math.round((1 - report.chunks_new / rawItems) * 100) : null

  return (
    <div>
      {/* run-now row */}
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
          gap: 12, marginBottom: 14,
        }}
      >
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: '#8A8C7C' }}>
          last ingest {ingested ?? 'never'}
        </span>
        <button
          onClick={onRunNow}
          disabled={!canPull || busy}
          className="btn-white"
          title={!canPull ? 'Live pull needs VOYAGE_API_KEY in .env' : undefined}
          style={{ ...whiteBtn, opacity: canPull ? 1 : 0.55, cursor: canPull ? 'pointer' : 'default' }}
        >
          {busy ? 'Crawling…' : canPull ? 'Run now' : 'Run now (needs VOYAGE_API_KEY)'}
        </button>
      </div>
      {error && (
        <div style={{ fontFamily: MONO, fontSize: 11, color: '#A6522E', marginBottom: 12 }}>
          {error}
        </div>
      )}

      {/* pipeline steps */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'stretch', marginBottom: 14 }}>
        {STEPS(status).map((st, i) => (
          <div key={st.name} style={{ display: 'contents' }}>
            {i > 0 && (
              <div style={{ alignSelf: 'center', color: '#C9CABB', fontSize: 15, flex: 'none', padding: '0 1px' }}>
                →
              </div>
            )}
            <div
              style={{
                flex: 1, border: '1px solid #E7E7DD', borderRadius: 12,
                background: '#FFFFFF', padding: '14px 14px 12px', minWidth: 0,
              }}
            >
              <div style={{ fontFamily: MONO, fontSize: 9, color: '#A2A494', marginBottom: 6 }}>
                0{i + 1}
              </div>
              <div style={{ fontFamily: DISPLAY, fontSize: 13.5, fontWeight: 600, marginBottom: 5 }}>
                {st.name}
              </div>
              <div style={{ fontSize: 10.8, lineHeight: 1.5, color: '#6B6D5F', marginBottom: 8 }}>
                {st.desc}
              </div>
              <div
                style={{
                  fontFamily: MONO, fontSize: 9, color: '#1E5940', background: '#EAF2EA',
                  borderRadius: 6, padding: '3.5px 7px', display: 'inline-block',
                }}
              >
                {st.spec}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 14, alignItems: 'start' }}>
        {/* funnel */}
        <div style={card()}>
          <div style={{ ...kicker, marginBottom: 4 }}>VOLUME REDUCTION: LAST RUN</div>
          <div style={{ fontSize: 11, color: '#A2A494', marginBottom: 14 }}>
            Skip low-discussion threads → collapse to post + top comments →
            thread-aware chunking → embed only what&rsquo;s new
          </div>
          {funnel.length ? (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {funnel.map((f, i) => (
                  <div key={f.label}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 11.5, color: '#4A4C3E' }}>{f.label}</span>
                      <span style={{ fontFamily: MONO, fontSize: 11, fontWeight: 600 }}>{f.display}</span>
                    </div>
                    <div style={{ height: 14, borderRadius: 4, background: '#F0F0E7' }}>
                      <div
                        style={{
                          height: '100%',
                          width: `${Math.max(1.5, (f.value / funnelMax) * 100)}%`,
                          background: i === funnel.length - 1 ? ACCENT : ['#5B6770', '#8A94A0', '#B0B6A6'][i] ?? '#B0B6A6',
                          borderRadius: 4,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              {dropped != null && (
                <div style={{ marginTop: 14, fontFamily: MONO, fontSize: 10, color: '#8A8C7C' }}>
                  {dropped}% of raw volume dropped before embedding; cost scales
                  with signal, not noise.
                </div>
              )}
            </>
          ) : (
            <div style={{ fontSize: 12, color: '#8A8C7C' }}>
              No run recorded yet; the funnel fills in after the first ingest on
              this database.
            </div>
          )}
        </div>

        {/* latest run */}
        <div style={card()}>
          <div style={{ ...kicker, marginBottom: 12 }}>LATEST RUN</div>
          <div
            style={{
              display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr .8fr .7fr', gap: 8,
              paddingBottom: 7, fontFamily: MONO, fontSize: 9,
              letterSpacing: '.08em', color: '#A2A494',
            }}
          >
            <span>DATE</span>
            <span>ITEMS</span>
            <span>CHUNKS</span>
            <span>DURATION</span>
            <span>STATUS</span>
          </div>
          <div
            style={{
              display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr .8fr .7fr', gap: 8,
              alignItems: 'center', padding: '8px 0', borderTop: '1px solid #F0F0E7',
            }}
          >
            <span style={{ fontSize: 11.5, fontWeight: 600 }}>
              {ingested?.slice(0, 10) ?? '-'}
            </span>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: '#6B6D5F' }}>
              {fmt(rawItems)}
            </span>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: '#3A421A' }}>
              +{fmt(report?.chunks_new)}
            </span>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: '#6B6D5F' }}>{duration}</span>
            <span
              style={{
                fontFamily: MONO, fontSize: 8.5, fontWeight: 600, textAlign: 'center',
                borderRadius: 99, padding: '2.5px 0',
                background: report ? '#EEF1DA' : '#F4F4EF',
                color: report ? '#3A421A' : '#8A8C7C',
              }}
            >
              {report ? 'ok' : '-'}
            </span>
          </div>
          <div style={{ marginTop: 12, fontSize: 11, lineHeight: 1.55, color: '#8A8C7C' }}>
            Retrieval is time-scoped: the generator only searches the covered
            week&rsquo;s window, so old chunks never leak into a new report.
            Stable chunk IDs make overlapping crawls embed only what&rsquo;s new.
          </div>
        </div>
      </div>
    </div>
  )
}
