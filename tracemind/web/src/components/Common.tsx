import type { ReactNode } from 'react'
import type { Certainty, IncidentStatus, RemediationStatus, RunStatus, Severity, Validation } from '../api/types'

export function Spinner({ size = 14 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-hidden />
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <Spinner size={18} /> <span>{label}…</span>
    </div>
  )
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <div>
        <strong>Request failed.</strong> <span className="mono">{error}</span>
      </div>
      {/not found/i.test(error) && <a className="btn btn-sm" href="/">Back to overview</a>}
      {onRetry && !/not found/i.test(error) && (
        <button className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  )
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="state state-empty">
      <div className="empty-title">{title}</div>
      {hint && <div className="muted">{hint}</div>}
      {action}
    </div>
  )
}

export function Card({ title, aside, children, className = '', id }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section className={`card ${className}`} id={id}>
      {(title || aside) && (
        <header className="card-head">
          <h2>{title}</h2>
          {aside && <div className="card-aside">{aside}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

const CERT: Record<Certainty, string> = { confirmed: 'Confirmed', suspected: 'Suspected', inconclusive: 'Inconclusive' }
export function CertaintyBadge({ value, large }: { value: Certainty; large?: boolean }) {
  return <span className={`badge cert-${value} ${large ? 'badge-lg' : ''}`}><i className="dot" />{CERT[value]}</span>
}
export function ValidationBadge({ value }: { value: Validation }) {
  return <span className={`badge val-${value}`}><i className="dot" />{value[0].toUpperCase() + value.slice(1)}</span>
}
export function StatusBadge({ value }: { value: IncidentStatus | RunStatus | RemediationStatus }) {
  return <span className={`badge st-${value}`}>{value.replace('_', ' ')}</span>
}
export function SeverityBadge({ value }: { value: Severity }) {
  return <span className={`badge sev-${value}`}>{value}</span>
}
export function Pill({ children, tone }: { children: ReactNode; tone?: string }) {
  return <span className={`pill ${tone ? 'pill-' + tone : ''}`}>{children}</span>
}
