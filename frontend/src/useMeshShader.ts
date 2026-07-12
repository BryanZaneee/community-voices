// Mounts a mesh gradient and crossfades its palette when the shade key
// changes (900 ms ease, per the design handoff).
import { useCallback, useEffect, useRef } from 'react'
import { mountMeshGradient, type ShaderController } from './shaders'
import { mixShade, SHADES, type Shade } from './shades'

function dampen(s: Shade): Shade {
  return { colors: s.colors, speed: s.speed * 0.3, distortion: 0.6, swirl: 0.4 }
}

export function useMeshShader(shadeKey: string, sidebar = false) {
  const ctrl = useRef<ShaderController | null>(null)
  const current = useRef<Shade>({ ...SHADES[shadeKey] })
  const raf = useRef(0)
  const adapt = sidebar ? dampen : (s: Shade) => s

  const setEl = useCallback(
    (el: HTMLElement | null) => {
      ctrl.current?.dispose()
      ctrl.current = null
      if (el) ctrl.current = mountMeshGradient(el, { ...adapt(current.current) })
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  useEffect(() => {
    const from = { ...current.current }
    const to = SHADES[shadeKey] ?? SHADES.idle
    const t0 = performance.now()
    const ms = 900
    cancelAnimationFrame(raf.current)
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / ms)
      const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2
      const cur = mixShade(from, to, e)
      current.current = cur
      ctrl.current?.set(adapt(cur))
      if (t < 1) raf.current = requestAnimationFrame(step)
    }
    raf.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shadeKey])

  useEffect(
    () => () => {
      ctrl.current?.dispose()
      ctrl.current = null
    },
    [],
  )

  return setEl
}
