// Thin wrapper around @paper-design/shaders (vanilla ESM, zero deps).
// Vendored from the design handoff with the CDN import swapped for the npm
// package; falls back to a CSS gradient if WebGL is unavailable.
import * as m from '@paper-design/shaders'

export interface ShaderParams {
  colors: string[]
  speed?: number
  distortion?: number
  swirl?: number
  grainMixer?: number
  grainOverlay?: number
}

export interface ShaderController {
  ok: boolean
  set(p: Partial<ShaderParams>): void
  setSpeed(s: number): void
  dispose(): void
}

const SIZING = {
  u_fit: 2, // cover
  u_scale: 1,
  u_rotation: 0,
  u_offsetX: 0,
  u_offsetY: 0,
  u_originX: 0.5,
  u_originY: 0.5,
  u_worldWidth: 0,
  u_worldHeight: 0,
}

function toUniforms(p: ShaderParams) {
  return {
    ...SIZING,
    u_colors: (p.colors || []).map((c) => m.getShaderColorFromString(c)),
    u_colorsCount: (p.colors || []).length,
    u_distortion: p.distortion ?? 0.7,
    u_swirl: p.swirl ?? 0.4,
    u_grainMixer: p.grainMixer ?? 0.08,
    u_grainOverlay: p.grainOverlay ?? 0.04,
  }
}

/**
 * Mount a paper-shaders mesh gradient into `el`.
 * Never throws — on failure returns a CSS-gradient fallback controller.
 */
export function mountMeshGradient(
  el: HTMLElement,
  params: ShaderParams,
): ShaderController {
  try {
    const mount = new m.ShaderMount(
      el,
      m.meshGradientFragmentShader,
      toUniforms(params),
      undefined,
      params.speed ?? 1,
    )
    return {
      ok: true,
      set(p) {
        Object.assign(params, p)
        mount.setUniforms(toUniforms(params))
        if (p.speed != null) mount.setSpeed(p.speed)
      },
      setSpeed(s) {
        mount.setSpeed(s)
      },
      dispose() {
        mount.dispose()
      },
    }
  } catch (e) {
    console.warn('paper-shaders unavailable, using CSS fallback', e)
    el.style.background = `radial-gradient(120% 90% at 20% 20%, ${params.colors?.[2] || '#7A8B22'} 0%, transparent 55%), radial-gradient(100% 100% at 80% 30%, ${params.colors?.[1] || '#E9EBD8'} 0%, transparent 60%), radial-gradient(120% 120% at 60% 90%, ${params.colors?.[3] || '#2A2E18'} 0%, transparent 65%), ${params.colors?.[0] || '#F4F4EF'}`
    return {
      ok: false,
      set() {},
      setSpeed() {},
      dispose() {
        el.style.background = ''
      },
    }
  }
}
