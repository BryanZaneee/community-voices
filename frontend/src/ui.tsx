// Tiny shared style vocabulary for the inline-styled design port.
import type { CSSProperties } from 'react'

export const MONO = 'var(--mono)'
export const DISPLAY = 'var(--font-display)'

export const card = (padding = '18px 20px'): CSSProperties => ({
  border: '1px solid #E7E7DD',
  borderRadius: 14,
  background: '#FFFFFF',
  padding,
})

export const kicker: CSSProperties = {
  fontFamily: MONO,
  fontSize: 10,
  letterSpacing: '.14em',
  color: '#8A8C7C',
  textTransform: 'uppercase',
}

export const pill = (bg: string, fg: string): CSSProperties => ({
  fontFamily: MONO,
  fontSize: 9.5,
  fontWeight: 600,
  padding: '2.5px 7px',
  borderRadius: 99,
  background: bg,
  color: fg,
})

/** Inline markdown italics (*cited post title*) -> highlighted spans. */
export function RichText({ text }: { text: string }) {
  const parts = text.split(/\*([^*\n]+)\*/g)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <span
            key={i}
            style={{
              background: '#EEF1DA',
              borderBottom: '2px solid #7A8B22',
              padding: '0 2px',
              borderRadius: 2,
            }}
          >
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  )
}

export const whiteBtn: CSSProperties = {
  padding: '8px 14px',
  borderRadius: 9,
  border: '1px solid #D8D9CB',
  background: '#FFFFFF',
  fontFamily: MONO,
  fontSize: 11,
  fontWeight: 600,
  color: '#3A421A',
  cursor: 'pointer',
}
