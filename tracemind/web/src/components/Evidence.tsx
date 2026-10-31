import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { EvidenceRef, EvidenceRecord } from '../api/types'
import { useFetch } from '../hooks'
import { ErrorBox, Loading } from './Common'
import { Code } from './Diff'
import { fmtDateTime, refKind, refLabel, spanDur, fmtDur } from '../util'

const Ctx = createContext<(ref: EvidenceRef) => void>(() => {})
export const useEvidence = () => useContext(Ctx)

export function EvidenceProvider({ children }: { children: ReactNode }) {
  const [ref, setRef] = useState<EvidenceRef | null>(null)
  return (
    <Ctx.Provider value={setRef}>
      {children}
      {ref && <EvidenceDrawer ref_={ref} onClose={() => setRef(null)} />}
    </Ctx.Provider>
  )
}

/** Clickable evidence reference. Opens the drawer which calls GET /api/evidence/{ref}. */
export function RefChip({ ref_, tone }: { ref_: EvidenceRef; tone?: 'for' | 'against' }) {
  const open = useEvidence()
  const k = refKind(ref_)
  return (
    <button type="button" className={`ref ref-${k} ${tone ? 'ref-' + tone : ''}`} onClick={() => open(ref_)} title={ref_}>
      <span className="ref-kind">{k}</span>
      <span className="ref-label">{refLabel(ref_).replace(/^(span|event|log|sig) /, '')}</span>
    </button>
  )
}

const REF_RE = /((?:span:[0-9a-f]+:[0-9a-f]+)|(?:event:[0-9a-f]+:[0-9a-f]+:\d+)|(?:log:\d+)|(?:code:[\w.-]+:[^\s:,)]+:\d+(?:-\d+)?)|(?:sig:[\w.-]+:\w+))/

/** Renders free text with embedded evidence refs turned into clickable chips. */
export function RichText({ text }: { text: string }) {
  const parts = text.split(REF_RE)
  return (
    <>
      {parts.map((p, i) =>
        i % 2 ? <RefChip key={i} ref_={p} /> : p.split(/(`[^`]+`)/).map((q, j) => (q.startsWith('`') && q.endsWith('`') && q.length > 2 ? <code key={`${i}-${j}`} className="ic">{q.slice(1, -1)}</code> : <span key={`${i}-${j}`}>{q}</span>)),
      )}
    </>
  )
}

export function RefList({ refs, tone }: { refs: EvidenceRef[]; tone?: 'for' | 'against' }) {
  if (!refs.length) return <span className="muted small">none</span>
  return <div className="refs">{refs.map((r) => <RefChip key={r} ref_={r} tone={tone} />)}</div>
}

function EvidenceDrawer({ ref_, onClose }: { ref_: EvidenceRef; onClose: () => void }) {
  const { data, error, loading, reload } = useFetch(() => api.evidence(ref_), [ref_])
  const closeRef = useRef<HTMLButtonElement>(null)
  const prev = useRef<Element | null>(null)

  useEffect(() => {
    prev.current = document.activeElement
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      ;(prev.current as HTMLElement | null)?.focus?.()
    }
  }, [onClose])

  return (
    <div className="drawer-wrap">
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Evidence">
        <header className="drawer-head">
          <div>
            <div className="eyebrow">Evidence · {refKind(ref_)}</div>
            <h3>{data?.title ?? refLabel(ref_)}</h3>
            <div className="mono small muted wrap">{ref_}</div>
          </div>
          <button ref={closeRef} className="btn btn-sm" onClick={onClose} aria-label="Close evidence drawer">Close <kbd>Esc</kbd></button>
        </header>
        <div className="drawer-body">
          {loading && <Loading label="Resolving reference" />}
          {error && <ErrorBox error={error} onRetry={reload} />}
          {data && <EvidenceBody ev={data} />}
        </div>
      </aside>
    </div>
  )
}

function Kv({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj)
  if (!entries.length) return <div className="muted small">no attributes</div>
  return (
    <dl className="kv">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd className="mono">{typeof v === 'string' ? v : JSON.stringify(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

function EvidenceBody({ ev }: { ev: EvidenceRecord }) {
  if (!ev.resolved) {
    return (
      <div className="state state-error" role="alert">
        <div><strong>Unresolved reference.</strong> This reference could not be validated against stored data, so it must not be trusted as evidence.</div>
        {ev.error && <div className="mono small">{ev.error}</div>}
      </div>
    )
  }
  if (ev.excerpt) {
    const x = ev.excerpt
    return (
      <>
        <div className="small muted">
          Repository <span className="mono">{x.repo_id}</span>{x.sha && <> at <span className="mono">{x.sha.slice(0, 10)}</span></>} · lines {x.start_line}–{x.end_line}
        </div>
        <div className="mono small path">{x.path}</div>
        <Code lines={x.lines} start={x.start_line} lang={x.path} />
        <div className="note small">Verified against actual file contents.</div>
      </>
    )
  }
  const r = (ev.record ?? {}) as Record<string, unknown>
  const attrs = (r.attributes ?? {}) as Record<string, unknown>
  switch (ev.kind) {
    case 'span':
      return (
        <>
          <dl className="kv">
            <div><dt>service</dt><dd>{String(r.service_name)}</dd></div>
            <div><dt>kind</dt><dd>{String(r.kind ?? '–')}</dd></div>
            <div><dt>status</dt><dd>{String(r.status_code ?? 'UNSET')}{r.status_message ? ` – ${r.status_message}` : ''}</dd></div>
            <div><dt>start</dt><dd className="mono">{fmtDateTime(r.start_time as string)}</dd></div>
            <div><dt>duration</dt><dd>{fmtDur(spanDur(r as never))}</dd></div>
          </dl>
          <h4>Attributes</h4>
          <Kv obj={attrs} />
        </>
      )
    case 'event':
      return (
        <>
          <dl className="kv">
            {r.span != null && <div><dt>span</dt><dd>{String(r.span)}{r.service_name ? ` (${String(r.service_name)})` : ''}</dd></div>}
            <div><dt>time</dt><dd className="mono">{fmtDateTime(r.time as string)}</dd></div>
            <div><dt>name</dt><dd>{String(r.name)}</dd></div>
          </dl>
          {typeof attrs['exception.stacktrace'] === 'string' && <><h4>Stack trace</h4><pre className="pre">{attrs['exception.stacktrace'] as string}</pre></>}
          <h4>Attributes</h4>
          <Kv obj={Object.fromEntries(Object.entries(attrs).filter(([k]) => k !== 'exception.stacktrace'))} />
        </>
      )
    case 'log':
      return (
        <>
          <dl className="kv">
            <div><dt>service</dt><dd>{String(r.service_name)}</dd></div>
            <div><dt>severity</dt><dd>{String(r.severity ?? '–')}</dd></div>
            <div><dt>time</dt><dd className="mono">{fmtDateTime(r.time as string)}</dd></div>
          </dl>
          <div className="note small">Log text is untrusted telemetry shown as data.</div>
          <pre className="pre">{String(r.body ?? '')}</pre>
        </>
      )
    default:
      return <pre className="pre">{JSON.stringify(r, null, 2)}</pre>
  }
}
