// Generation run state: SSE events in, smoothly-paced stage/progress out.
import { useEffect, useRef, useState } from 'react'
import { generateStream, type Doc, type StageKey, type Status } from './api'
import { communityIdentity, fmt } from './viewmodel'

export interface RunState {
  phase: 'idle' | 'run' | 'done'
  stage: number
  prog: number
  reveal: boolean
}

export interface StageUi {
  key: StageKey
  label: string
  desc: string
  detail: string
}

export const STAGE_KEYS: StageKey[] = [
  'crawl', 'reduce', 'embed', 'retrieve', 'write',
]

export function baseStages(status: Status | null, week: string): StageUi[] {
  const ident = communityIdentity(status?.subreddit ?? null)
  const w = status?.weeks.find((x) => x.week_start === week)
  return [
    {
      key: 'crawl',
      label: 'Crawl',
      desc: `Loading the week's threads from ${ident.name}`,
      detail: `${fmt(w?.n_posts)} posts · cached from last ingest`,
    },
    {
      key: 'reduce',
      label: 'Reduce',
      desc: 'Dedupe, filter noise, keep top discussion',
      detail: `${fmt(w?.n_posts)} posts → ${fmt(w?.n_chunks)} chunks`,
    },
    {
      key: 'embed',
      label: 'Embed',
      desc: 'Chunking & embedding into sqlite-vec',
      detail: `${fmt(w?.n_chunks)} chunks · ${status?.embedding_model ?? '—'}`,
    },
    {
      key: 'retrieve',
      label: 'Retrieve',
      desc: "Ranking the week's context for the digest",
      detail: 'facet queries · scoped to the week window',
    },
    {
      key: 'write',
      label: 'Write',
      desc: 'Drafting digest & predictions',
      detail: 'grounded on retrieved chunks',
    },
  ]
}

// cumulative progress ceiling per stage (write dominates real wall-clock)
const CEILS = [0.08, 0.16, 0.26, 0.55, 0.98]
const MIN_STAGE_MS = 650

export function useGeneration(
  status: Status | null,
  onDoc: (doc: Doc) => void,
) {
  const [run, setRun] = useState<RunState>({
    phase: 'idle', stage: 0, prog: 0, reveal: false,
  })
  const [stages, setStages] = useState<StageUi[]>(baseStages(null, ''))
  const [error, setError] = useState<string | null>(null)
  const target = useRef<{
    stage: number
    doc: Doc | null
    failed: string | null
    fallbackPhase: 'idle' | 'done'
  }>({ stage: 0, doc: null, failed: null, fallbackPhase: 'idle' })

  /** Show an existing report without animating (page load, week switch). */
  const showDone = (reveal = true) =>
    setRun({ phase: 'done', stage: 4, prog: 1, reveal })

  const showIdle = () => setRun({ phase: 'idle', stage: 0, prog: 0, reveal: false })

  const start = (week: string, model: string) => {
    if (run.phase === 'run') return
    target.current = {
      stage: 0,
      doc: null,
      failed: null,
      fallbackPhase: run.phase === 'done' ? 'done' : 'idle',
    }
    setError(null)
    setStages(baseStages(status, week))
    setRun({ phase: 'run', stage: 0, prog: 0, reveal: false })
    generateStream({ week_start: week, model_key: model }, (ev) => {
      const idx = STAGE_KEYS.indexOf(ev.stage)
      if (idx < 0) return
      target.current.stage = Math.max(target.current.stage, idx)
      setStages((prev) =>
        prev.map((s, i) => {
          if (i !== idx) return s
          if (ev.detail) return { ...s, detail: ev.detail }
          if (ev.stage === 'retrieve' && ev.status === 'end')
            return {
              ...s,
              detail: `top-${ev.chunks} chunks · ${ev.mode} · ${ev.retrieval_ms} ms`,
            }
          if (ev.stage === 'write' && ev.status === 'start')
            return { ...s, detail: `${ev.model_key} · grounded on retrieved chunks` }
          return s
        }),
      )
    })
      .then((doc) => {
        target.current.doc = doc
      })
      .catch((e: Error) => {
        target.current.failed = e.message
      })
  }

  useEffect(() => {
    if (run.phase !== 'run') return
    let lastAdvance = performance.now()
    let finished = false
    const iv = window.setInterval(() => {
      const t = target.current
      if (t.failed) {
        window.clearInterval(iv)
        setError(t.failed)
        if (t.fallbackPhase === 'done') showDone()
        else showIdle()
        return
      }
      setRun((r) => {
        if (finished || r.phase !== 'run') return r
        let stage = r.stage
        const now = performance.now()
        const wantStage = t.doc ? STAGE_KEYS.length - 1 : t.stage
        if (stage < wantStage && now - lastAdvance > MIN_STAGE_MS) {
          stage += 1
          lastAdvance = now
        }
        const last = stage === STAGE_KEYS.length - 1
        const ceil = t.doc && last ? 1 : CEILS[stage]
        const prog = r.prog + (ceil - r.prog) * (t.doc ? 0.28 : 0.06)
        if (t.doc && last && prog > 0.99) {
          finished = true
          window.clearInterval(iv)
          const doc = t.doc
          setTimeout(() => {
            onDoc(doc)
            setRun({ phase: 'done', stage, prog: 1, reveal: false })
            setTimeout(
              () => setRun((r2) => ({ ...r2, reveal: true })),
              80,
            )
          }, 250)
          return { ...r, stage, prog: 1 }
        }
        return { ...r, stage, prog }
      })
    }, 100)
    return () => window.clearInterval(iv)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.phase])

  const shadeKey =
    run.phase === 'run'
      ? STAGE_KEYS[run.stage]
      : run.phase === 'done'
        ? 'done'
        : 'idle'

  return { run, stages, error, shadeKey, start, showDone, showIdle }
}
