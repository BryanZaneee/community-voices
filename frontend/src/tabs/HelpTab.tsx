import type { Status } from '../api'
import { ACCENT, communityIdentity } from '../viewmodel'
import { card, DISPLAY } from '../ui'

// Help copy from the design handoff, with the stack names swapped for the
// real one (sqlite-vec, Voyage embeddings, weekly cron via README).
const HELP_ITEMS = (community: string, model: string) => [
  {
    q: 'What is this report?',
    a: `Every week we read what ${community} posted, then write a short digest of what people talked about — plus a forecast of what they’ll likely talk about next week.`,
  },
  {
    q: 'What is RAG?',
    a: 'Retrieval-Augmented Generation. Instead of letting the AI write from memory, we first hand it the most relevant real posts from the week. It can only summarize what people actually said — which keeps the report honest and specific.',
  },
  {
    q: 'What are embeddings?',
    a: 'A way of turning text into a list of numbers that captures its meaning. Posts about similar things get similar numbers, so the computer can find related discussions instantly.',
  },
  {
    q: 'What is a vector store?',
    a: 'The database where those number-versions of posts live (ours is SQLite with the sqlite-vec extension — a vectorized table inside a relational database). When we build a report, we search it for the posts closest in meaning to each part of the story.',
  },
  {
    q: 'What is a “chunk”?',
    a: 'A bite-sized piece of a discussion — a post plus its best comments. Long threads get split into chunks so the AI receives small, focused pieces of real context.',
  },
  {
    q: 'How do I read the embeddings map?',
    a: 'Each dot is one chunk, placed so similar chunks sit near each other. Colors are topic clusters; a tight blob means lots of people saying related things. Click a blob to read its actual posts.',
  },
  {
    q: 'What is retrieval heat?',
    a: 'A view of which chunks the report actually used. Bigger, darker dots were pulled into the report most often — the community’s “greatest hits.”',
  },
  {
    q: 'What is the A/B comparison?',
    a: 'The same report written twice: once grounded on real posts (RAG), once from the AI’s memory alone. Side by side, you can see which one is specific and true versus vague filler.',
  },
  {
    q: 'What do the run metrics mean?',
    a: 'Cost is what one report costs to generate. Tokens measure how much text goes in and out — more retrieved context in means higher cost, but grounded claims out.',
  },
  {
    q: 'How does data get in?',
    a: `An automated crawler (one cron line, or the Run-now button) reads the week’s top threads from the open Lemmy API, keeps the real discussion, and files it into the vector store as ${model} embeddings — ready before the report is written.`,
  },
  {
    q: 'What does prediction confidence mean?',
    a: 'How sure the model is a topic will take off next week, based on signals like scheduled events and rising activity. 88% means very likely — not guaranteed.',
  },
]

export function HelpTab({ status }: { status: Status | null }) {
  const ident = communityIdentity(status?.subreddit ?? null, status?.source)
  const items = HELP_ITEMS(ident.name, status?.embedding_model ?? 'Voyage')
  return (
    <div>
      <div style={{ maxWidth: 720, fontSize: 13.5, lineHeight: 1.6, color: '#3F4136', marginBottom: 18 }}>
        Everything on this page, explained in plain language — no jargon required.
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {items.map((h) => (
          <details key={h.q} style={{ ...card('16px 18px'), minWidth: 0 }}>
            <summary
              style={{
                display: 'flex', alignItems: 'baseline', gap: 8, cursor: 'pointer',
                listStyle: 'none',
              }}
            >
              <span
                style={{
                  width: 7, height: 7, borderRadius: '50%', background: ACCENT,
                  flex: 'none', position: 'relative', top: -1,
                }}
              />
              <span style={{ fontFamily: DISPLAY, fontSize: 14.5, fontWeight: 600, letterSpacing: '-.01em' }}>
                {h.q}
              </span>
            </summary>
            <div style={{ fontSize: 12.5, lineHeight: 1.62, color: '#4A4C3E', marginTop: 6 }}>{h.a}</div>
          </details>
        ))}
      </div>
    </div>
  )
}
