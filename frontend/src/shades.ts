// Per-stage mesh-gradient palettes + crossfade math, from the design handoff.

export interface Shade {
  speed: number
  distortion: number
  swirl: number
  colors: string[]
}

export const SHADES: Record<string, Shade> = {
  idle:     { speed: 0.35, distortion: 0.55, swirl: 0.3,  colors: ['#F4F4EF', '#E7EBD2', '#B9C65A', '#7A8B22'] },
  crawl:    { speed: 1.2,  distortion: 0.95, swirl: 0.15, colors: ['#EFF1E4', '#C9D18C', '#7A8B22', '#3A421F', '#16180F'] },
  reduce:   { speed: 0.95, distortion: 0.45, swirl: 0.9,  colors: ['#F7F3E4', '#E4D194', '#B08C1E', '#6B5312', '#F4F4EF'] },
  embed:    { speed: 1.6,  distortion: 0.85, swirl: 1.0,  colors: ['#EAF2EA', '#9CC9A8', '#2E7D5B', '#153B2A', '#F4F4EF'] },
  retrieve: { speed: 0.85, distortion: 0.3,  swirl: 0.55, colors: ['#EEF0F2', '#B9C2CC', '#5B6770', '#2A3138', '#DDE3BC'] },
  write:    { speed: 0.5,  distortion: 0.6,  swirl: 0.25, colors: ['#FAFAF7', '#E7EBD2', '#A9BA4A', '#6A791D'] },
  done:     { speed: 0.22, distortion: 0.5,  swirl: 0.3,  colors: ['#FAFAF7', '#EDEFDF', '#C9D18C', '#8E9F33'] },
}

function hexToRgb(h: string): [number, number, number] {
  h = h.replace('#', '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  const n = parseInt(h, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function mixHex(a: string, b: string, t: number): string {
  const A = hexToRgb(a)
  const B = hexToRgb(b)
  return (
    '#' +
    [0, 1, 2]
      .map((i) =>
        Math.round(A[i] + (B[i] - A[i]) * t)
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')
  )
}

export function mixShade(a: Shade, b: Shade, t: number): Shade {
  const n = Math.max(a.colors.length, b.colors.length)
  const ca = [...a.colors]
  while (ca.length < n) ca.push(ca[ca.length - 1])
  const cb = [...b.colors]
  while (cb.length < n) cb.push(cb[cb.length - 1])
  return {
    colors: ca.map((c, i) => mixHex(c, cb[i], t)),
    distortion: a.distortion + (b.distortion - a.distortion) * t,
    swirl: a.swirl + (b.swirl - a.swirl) * t,
    speed: a.speed + (b.speed - a.speed) * t,
  }
}
