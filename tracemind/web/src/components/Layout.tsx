import type { ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { fixturesActive } from '../api/client'
import { EvidenceProvider } from './Evidence'

export function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="var(--accent-bg)" />
      <path d="M6 22l6-9 5 6 4-10 5 13" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export default function Layout({ children }: { children: ReactNode }) {
  const fx = fixturesActive()
  useLocation() // re-evaluate banner on navigation
  return (
    <EvidenceProvider>
      <a className="skip" href="#main">Skip to content</a>
      {fx && (
        <div className="fx-banner" role="status">
          <b>FIXTURE DATA</b>
          <span>Showing bundled sample data for the duplicate-notification incident, not live telemetry.</span>
          <a href="/?fixtures=0">Exit fixture mode</a>
        </div>
      )}
      <div className="shell">
        <nav className="side" aria-label="Primary">
          <Link to="/" className="brand"><Logo /><span>Trace<b>Mind</b></span></Link>
          <NavLink to="/" end className={({ isActive }) => 'nav' + (isActive ? ' active' : '')}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/></svg>
            <span>Overview</span>
          </NavLink>
          <div className="side-foot">
            <div className="tagline">From distributed failure<br />to verified fix.</div>
          </div>
        </nav>
        <main id="main" className="main" tabIndex={-1}>{children}</main>
      </div>
    </EvidenceProvider>
  )
}

export function PageHead({ crumbs, title, sub, actions }: { crumbs?: { to?: string; label: string }[]; title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        {crumbs && (
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.map((c, i) => (
              <span key={i}>{c.to ? <Link to={c.to}>{c.label}</Link> : c.label}{i < crumbs.length - 1 && <i>/</i>}</span>
            ))}
          </nav>
        )}
        <h1>{title}</h1>
        {sub && <div className="page-sub">{sub}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}
