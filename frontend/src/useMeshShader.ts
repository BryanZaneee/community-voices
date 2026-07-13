// Mounts a mesh gradient and smoothly eases its palette toward a target:
// the shade key's palette, or (during a run) a progress blend between the
// current stage and the next, so colors drift continuously per the design
// handoff.
import { useCallback, useEffect, useRef } from 'react'
import { mountMeshGradient, type ShaderController } from './shaders'
import { mixShade, SHADES, type Shade } from './shades'

function dampen(s: Shade): Shade {
  return { colors: s.colors, speed: s.speed * 0.3, distortion: 0.6, swirl: 0.4 }
}

export function useMeshShader(
  shadeKey: string,
  sidebar = false,
  blend?: { toKey: string; t: number },
) {
  const ctrl = useRef<ShaderController | null>(null)
  const current = useRef<Shade>({ ...SHADES[shadeKey] })
  const target = useRef<Shade>({ ...SHADES[shadeKey] })
  const raf = useRef(0)
  const adapt = sidebar ? dampen : (s: Shade) => s

  const base = SHADES[shadeKey] ?? SHADES.idle
  target.current = blend
    ? mixShade(base, SHADES[blend.toKey] ?? base, Math.min(1, Math.max(0, blend.t)))
    : base

  const setEl = useCallback(
    (el: HTMLElement | null) => {
      ctrl.current?.dispose()
      ctrl.current = null
      if (el) ctrl.current = mountMeshGradient(el, { ...adapt(current.current) })
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  // ponytail: perpetual RAF exponential ease (tau 300ms ≈ old 900ms fade);
  // one loop covers stage crossfades and continuous progress blends alike.
  useEffect(() => {
    let last = performance.now()
    const step = (now: number) => {
      const k = 1 - Math.exp(-(now - last) / 300)
      last = now
      current.current = mixShade(current.current, target.current, k)
      ctrl.current?.set(adapt(current.current))
      raf.current = requestAnimationFrame(step)
    }
    raf.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(
    () => () => {
      ctrl.current?.dispose()
      ctrl.current = null
    },
    [],
  )

  return setEl
}
