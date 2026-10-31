import { useMemo, useState } from 'react'
import type { Span } from '../api/types'
import { fmtClock, fmtDur, spanDur } from '../util'
import { RefChip } from './Evidence'

interface Row { span: Span; depth: number }

function order(spans: Span[]): Row[] {
  const byParent = new Map<string | null, Span[]>()
  const ids = new Set(spans.map((s) => s.span_id))
  for (const s of spans) {
    const k = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null
    byParent.set(k, [...(byParent.get(k) ?? []), s])
  }
  const rows: Row[] = []
  const walk = (pid: string | null, depth: number) => {
    const kids = (byParent.get(pid) ?? []).sort((a, b) => Date.parse(a.start_time) - Date.parse(b.start_time))
    for (const k of kids) { rows.push({ span: k, depth }); walk(k.span_id, depth + 1) }
  }
  walk(null, 0)
  return rows
}

const COLORS = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)']

export default function Waterfall({ spans }: { spans: Span[] }) {
  const rows = useMemo(() => order(spans), [spans])
  const svc = useMemo(() => Array.from(new Set(spans.map((s) => s.service_name))), [spans])
  const [sel, setSel] = useState<string | null>(() => spans.find((s) => s.status_code === 'ERROR')?.span_id ?? null)
  if (!spans.length) return null
  const t0 = Math.min(...spans.map((s) => Date.parse(s.start_time)))
  const t1 = Math.max(...spans.map((s) => Date.parse(s.end_time)))
  const total = Math.max(t1 - t0, 1)
  const selected = spans.find((s) => s.span_id === sel) ?? null
  const ticks = [0, 0.25, 0.5, 0.75, 1]

  return (
    <div className="wf">
      <div className="wf-legend">
        {svc.map((s, i) => <span key={s}><i style={{ background: COLORS[i % 4] }} />{s}</span>)}
        <span><i style={{ background: 'var(--bad)' }} />error</span>
        <span className="muted">trace length {fmtDur(total)}</span>
      </div>
      <div className="wf-scale">
        <div className="wf-name" />
        <div className="wf-track">{ticks.map((t) => <span key={t} style={{ left: `${t * 100}%` }}>{fmtDur(total * t)}</span>)}</div>
      </div>
      <div role="listbox" aria-label="Spans in trace">
        {rows.map(({ span: s, depth }) => {
          const left = ((Date.parse(s.start_time) - t0) / total) * 100
          const width = Math.max((spanDur(s) / total) * 100, 0.6)
          const err = s.status_code === 'ERROR'
          const color = err ? 'var(--bad)' : COLORS[svc.indexOf(s.service_name) % 4]
          return (
            <button
              key={s.span_id}
              role="option"
              aria-selected={sel === s.span_id}
              className={`wf-row ${sel === s.span_id ? 'sel' : ''}`}
              onClick={() => setSel(s.span_id)}
            >
              <div className="wf-name" style={{ paddingLeft: depth * 14 }}>
                <span className="wf-svc">{s.service_name}</span> <span>{s.name}</span>
                {s.events.some((e) => e.name === 'exception') && <span className="wf-x" title="exception event">!</span>}
              </div>
              <div className="wf-track">
                {ticks.map((t) => <i key={t} className="wf-grid" style={{ left: `${t * 100}%` }} />)}
                <span className="wf-bar" style={{ left: `${left}%`, width: `${width}%`, background: color }} />
                <span className="wf-dur" style={{ left: `${Math.min(left + width + 0.8, 88)}%` }}>{fmtDur(spanDur(s))}</span>
              </div>
            </button>
          )
        })}
      </div>
      {selected && (
        <div className="wf-detail">
          <div className="wf-detail-head">
            <strong>{selected.name}</strong>
            <span className="muted">{selected.service_name} · {selected.kind} · {fmtClock(selected.start_time)}</span>
            <RefChip ref_={`span:${selected.trace_id}:${selected.span_id}`} />
          </div>
          {selected.status_code === 'ERROR' && <div className="wf-err">ERROR {selected.status_message}</div>}
          <dl className="kv kv-2">
            {Object.entries(selected.attributes).map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd className="mono">{String(v)}</dd></div>
            ))}
          </dl>
          {selected.events.map((e) => (
            <div className="wf-event" key={e.idx}>
              <div className="wf-event-head"><b>{e.name}</b> <span className="muted mono small">{fmtClock(e.time)}</span> <RefChip ref_={`event:${selected.trace_id}:${selected.span_id}:${e.idx}`} /></div>
              <div className="mono small">{String(e.attributes['exception.type'] ?? '')}{e.attributes['exception.message'] ? `: ${e.attributes['exception.message']}` : ''}</div>
              {typeof e.attributes['exception.stacktrace'] === 'string' && <pre className="pre">{e.attributes['exception.stacktrace'] as string}</pre>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
