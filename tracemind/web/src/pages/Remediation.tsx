import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { CommandRun, Remediation, RemediationStatus } from '../api/types'
import { useAction, useFetch } from '../hooks'
import { Card, Empty, ErrorBox, Loading, Spinner, StatusBadge } from '../components/Common'
import { PageHead } from '../components/Layout'
import { RefList } from '../components/Evidence'
import { DiffView } from '../components/Diff'
import { fmtClock, fmtDateTime, fmtDur } from '../util'

const STAGES: { key: RemediationStatus; label: string; hint: string }[] = [
  { key: 'patch_generated', label: 'Patch generated', hint: 'A diff exists. Nothing has been run yet.' },
  { key: 'tested', label: 'Tested', hint: 'Tests ran in the sandbox; results captured.' },
  { key: 'verified', label: 'Verified', hint: 'Tests including the injected-scenario regression passed.' },
]
const RANK: Record<string, number> = { queued: -1, running: -1, failed: -1, patch_generated: 0, tested: 1, verified: 2 }
const inFlight = (s: string) => s !== 'verified' && s !== 'failed'

export default function RemediationPage() {
  const { id = '' } = useParams()
  const { data, error, loading, reload } = useFetch(() => api.remediation(id), [id], { poll: 1200, done: (d: Remediation) => !inFlight(d.status) })
  const approve = useAction(async () => {
    await api.approve(id)
    reload()
  })

  if (loading && !data) return <Loading label="Loading remediation" />
  if (error && !data) return <ErrorBox error={error} onRetry={reload} />
  if (!data) return null
  const r = data
  const canApprove = r.status === 'verified' && !r.approved

  return (
    <>
      <PageHead
        crumbs={[{ to: '/', label: 'Overview' }, { to: `/incidents/${r.incident_id}`, label: 'Incident' }, { to: `/investigations/${r.investigation_id}`, label: 'Investigation' }, { label: 'Remediation' }]}
        title="Proposed fix"
        sub={
          <div className="meta-row">
            <StatusBadge value={r.status} />
            {r.approved && <span className="badge cert-confirmed"><i className="dot" />Approved</span>}
            <span className="mono small muted">{r.id}</span>
            {r.base_sha && <span className="mono small muted">base {r.base_sha.slice(0, 10)}</span>}
            {inFlight(r.status) && <span className="live"><Spinner /> live · polling</span>}
          </div>
        }
        actions={
          <>
            <button className="btn btn-primary" disabled={!canApprove || approve.pending} onClick={() => approve.run()}
              title={r.approved ? 'Already approved' : r.status !== 'verified' ? 'Approval requires a verified fix' : undefined}>
              {approve.pending ? <><Spinner /> Approving…</> : r.approved ? 'Approved' : 'Approve fix'}
            </button>
            <button className="btn" disabled aria-disabled title="Pull request creation is not implemented yet">Create PR <span className="soon">coming soon</span></button>
          </>
        }
      />
      {approve.error && <ErrorBox error={approve.error} />}
      {r.approved && <div className="state state-ok small">Approved{r.approved_by ? ` by ${r.approved_by}` : ''} {r.approved_at ? `at ${fmtDateTime(r.approved_at)}` : ''}. No code has been pushed or merged; PR creation is not yet available.</div>}
      {r.error && <ErrorBox error={r.error} />}

      <Card title="Verification status">
        <Stepper status={r.status} />
        {r.status === 'failed' && <div className="note note-bad small">Remediation failed before reaching verification. See command output below.</div>}
      </Card>

      {r.summary && <p className="lede">{r.summary}</p>}

      <div className="grid-2">
        <Card title="Source references" aside={<span className="muted small">code the patch is based on</span>}>
          {r.source_refs.length ? <RefList refs={r.source_refs} /> : <Empty title={inFlight(r.status) ? 'Locating source…' : 'No source references'} />}
        </Card>
        <Card title="Test results">
          {r.test_results.length === 0 ? <Empty title="No tests have run yet" /> : (
            <ul className="tests">
              {r.test_results.map((t, i) => (
                <li key={i} className={`t-${t.outcome}`}>
                  <span className="t-out">{t.outcome}</span>
                  <span className="mono small t-name">{t.name}</span>
                  <span className="pill">{t.phase.replace('_', ' ')}</span>
                  {t.detail && <span className="mono small muted">{t.detail}</span>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Unified diff">
        {r.diff ? <DiffView diff={r.diff} /> : <Empty title={inFlight(r.status) ? 'Generating patch…' : 'No diff produced'} />}
      </Card>

      <Card title="Command runs" aside={<span className="muted small">sandboxed · network disabled</span>}>
        {r.command_runs.length === 0 ? <Empty title="No commands have run" /> : <div className="cmds">{r.command_runs.map((c) => <Cmd key={c.id} c={c} />)}</div>}
      </Card>

      <p className="muted small"><Link to={`/investigations/${r.investigation_id}`}>Back to investigation</Link></p>
    </>
  )
}

function Stepper({ status }: { status: RemediationStatus }) {
  const rank = RANK[status]
  return (
    <ol className="stepper" aria-label="Remediation status">
      {STAGES.map((s, i) => {
        const done = rank >= i
        const current = rank === i
        const next = rank + 1 === i && status !== 'failed'
        return (
          <li key={s.key} className={`stg ${done ? 'stg-done' : ''} ${current ? 'stg-cur' : ''}`} aria-current={current ? 'step' : undefined}>
            <i className="stg-dot">{done ? '✓' : next ? <Spinner size={10} /> : i + 1}</i>
            <div><b>{s.label}</b><div className="small muted">{s.hint}</div></div>
          </li>
        )
      })}
    </ol>
  )
}

function Cmd({ c }: { c: CommandRun }) {
  const [open, setOpen] = useState(c.exit_code !== 0)
  const ok = c.exit_code === 0
  return (
    <div className={`cmd ${ok ? 'cmd-ok' : 'cmd-bad'}`}>
      <button className="cmd-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="cmd-exit">exit {c.exit_code ?? '?'}</span>
        <span className="pill">{c.phase}</span>
        <code className="mono cmd-line">$ {c.command}</code>
        <span className="muted small mono">{fmtClock(c.started_at)} · {fmtDur(c.duration_ms)}</span>
        <span className="chev">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="cmd-out">
          {c.stdout || c.stderr ? <pre className="pre">{c.stdout}{c.stderr && '\n' + c.stderr}</pre> : <div className="muted small">no output</div>}
        </div>
      )}
    </div>
  )
}
