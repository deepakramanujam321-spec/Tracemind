import type { EvidenceRef } from './api/types'

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return '–'
  const d = new Date(iso)
  return d.toLocaleTimeString('en-GB', { hour12: false, timeZone: 'UTC' }) + '.' + String(d.getUTCMilliseconds()).padStart(3, '0')
}
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '–'
  const d = new Date(iso)
  return d.toISOString().replace('T', ' ').replace('Z', ' UTC')
}
export function fmtDur(ms: number | null | undefined): string {
  if (ms == null) return '–'
  if (ms <= 0) return '0'
  if (ms < 1) return `${Math.round(ms * 1000)} µs`
  if (ms < 10) return `${ms.toFixed(1)} ms`
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}
export function spanDur(s: { duration_ms: number | null; start_time: string; end_time: string }): number {
  return s.duration_ms ?? Date.parse(s.end_time) - Date.parse(s.start_time)
}
/** Epoch ms with sub-millisecond precision (Date.parse truncates the microsecond digits OTLP timestamps carry). */
export function tms(iso: string): number {
  const m = /\.(\d+)/.exec(iso)
  const micro = m ? Number('0.' + m[1].slice(3, 6).padEnd(3, '0')) : 0 // digits beyond ms, in ms
  return Date.parse(iso) + micro
}
export const shortId = (id: string, n = 8) => (id.length > n ? id.slice(0, n) : id)

export type RefKind = 'span' | 'event' | 'log' | 'code' | 'sig' | 'unknown'
export function refKind(ref: EvidenceRef): RefKind {
  const k = ref.split(':')[0]
  return (['span', 'event', 'log', 'code', 'sig'] as string[]).includes(k) ? (k as RefKind) : 'unknown'
}
/** Short human label for a ref chip. */
export function refLabel(ref: EvidenceRef): string {
  const p = ref.split(':')
  switch (refKind(ref)) {
    case 'span': return `span …${(p[2] ?? '').slice(-6)}`
    case 'event': return `event …${(p[2] ?? '').slice(-6)}#${p[3]}`
    case 'log': return `log #${p[1]}`
    case 'sig': return `sig ${p.slice(2).join(':')}`
    case 'code': {
      const m = /^code:[^:]+:(.+):(\d+(?:-\d+)?)$/.exec(ref)
      return m ? `${m[1].split('/').pop()}:${m[2]}` : ref
    }
    default: return ref
  }
}
export const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e))
