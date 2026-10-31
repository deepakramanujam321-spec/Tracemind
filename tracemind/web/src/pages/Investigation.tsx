import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AgentStep, Challenge, Hypothesis, Investigation } from '../api/types'
import { useAction, useFetch } from '../hooks'
import { Card, CertaintyBadge, Empty, ErrorBox, Loading, Spinner, StatusBadge, ValidationBadge } from '../components/Common'
import { PageHead } from '../components/Layout'
import { RefList } from '../components/Evidence'
import { fmtClock, fmtDur } from '../util'

const active = (s: string) => s === 'queued' || s === 'running'

export default function InvestigationPage() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const { data, error, loading, reload } = useFetch(() => api.investigation(id), [id], {
    poll: 1200,
    done: (d: Investigation) => !active(d.status),
  })
  const fix = useAction(async () => {
    const r = await api.startRemediation(id)
    nav(`/remediations/${r.remediation_id}`)
  })

  if (loading && !data) return <Loading label="Loading investigation" />
  if (error && !data) return <ErrorBox error={error} onRetry={reload} />
  if (!data) return null
  const inv = data
  const running = active(inv.status)
  const adj = inv.adjudication
  const duration = inv.finished_at ? Date.parse(inv.finished_at) - Date.parse(inv.started_at) : null

  return (
    <>
      <PageHead
        crumbs={[{ to: '/', label: 'Overview' }, { to: `/incidents/${inv.incident_id}`, label: 'Incident' }, { label: 'Investigation' }]}
        title={inv.incident_title}
        sub={
          <div className="meta-row">
            <StatusBadge value={inv.status} />
            {adj && <CertaintyBadge value={adj.certainty} />}
            <span className="mono small muted">{inv.id}</span>
            {duration != null && <span className="muted small">{fmtDur(duration)}</span>}
            {inv.code_backend && <span className="muted small">code intel: {inv.code_backend}</span>}
            {inv.model && <span className="muted small mono">{inv.model}</span>}
            {running && <span className="live"><Spinner /> live · polling</span>}
          </div>
        }
        actions={
          <>
            {inv.remediations[0] && <Link className="btn" to={`/remediations/${inv.remediations[0].id}`}>Open remediation</Link>}
            <button className="btn btn-primary" onClick={() => fix.run()} disabled={fix.pending || running || !adj || inv.status === 'failed'} title={!adj ? 'Available once adjudication completes' : undefined}>
              {fix.pending ? <><Spinner /> Starting…</> : 'Generate fix'}
            </button>
          </>
        }
      />
      {fix.error && <ErrorBox error={fix.error} />}
      {inv.error && <ErrorBox error={inv.error} />}
      {error && data && <div className="state state-warn small">Polling error (will retry): <span className="mono">{error}</span></div>}

      {adj ? (
        <section className={`verdict verdict-${adj.certainty}`} aria-label="Final adjudication">
          <div className="verdict-top">
            <div>
              <div className="eyebrow">Final adjudication</div>
              <div className="verdict-cause">{adj.root_cause}</div>
            </div>
            <CertaintyBadge value={adj.certainty} large />
          </div>
          <p className="verdict-why">{adj.rationale}</p>
          <div className="verdict-grid">
            <div>
              <div className="eyebrow">Decisive evidence</div>
              <RefList refs={adj.evidence_refs} tone="for" />
            </div>
            <div>
              <div className="eyebrow">Winning / rejected</div>
              <div className="meta-row">
                {adj.winning_hypothesis_id && <span className="pill pill-win">{adj.winning_hypothesis_id} wins</span>}
                {adj.rejected_hypothesis_ids.map((h) => <span key={h} className="pill pill-rej">{h} rejected</span>)}
              </div>
            </div>
          </div>
          {adj.rejected_refs.length > 0 && (
            <div className="note note-bad small"><b>Unresolvable references discarded:</b> <RefList refs={adj.rejected_refs} tone="against" /></div>
          )}
          {adj.limitations.length > 0 && (
            <div className="limits">
              <div className="eyebrow">Limitations</div>
              <ul className="plain">{adj.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
            </div>
          )}
        </section>
      ) : (
        !running && inv.status !== 'failed' && <Empty title="No adjudication recorded" />
      )}

      <div className={running ? 'run-first' : ''}>
        <div>
          <div className="section-title">
            <h2>Independent hypotheses</h2>
            <span className="muted small">Each authored separately; confidence is a model estimate, not a probability.</span>
          </div>
          {inv.hypotheses.length === 0 ? (
            <Card>{running ? <Loading label="Agents are forming hypotheses" /> : <Empty title="No hypotheses produced" />}</Card>
          ) : (
            <div className="hyps">
              {inv.hypotheses.map((h) => <Hyp key={h.id} h={h} winner={adj?.winning_hypothesis_id === h.id} />)}
            </div>
          )}
        </div>

        <Card className="mt" title="Agent execution" aside={<span className="muted small">{inv.steps.filter((s) => s.status === 'completed').length}/{inv.steps.length} steps</span>}>
          {inv.steps.length === 0 ? <Empty title="Waiting for the first agent step" /> : <ol className="steps">{inv.steps.map((s) => <Step key={s.id} s={s} />)}</ol>}
        </Card>

      </div>
    </>
  )
}

function Step({ s }: { s: AgentStep }) {
  const dur = s.started_at && s.finished_at ? Date.parse(s.finished_at) - Date.parse(s.started_at) : null
  return (
    <li className={`step step-${s.status}`}>
      <i className="step-dot">{s.status === 'running' && <Spinner size={10} />}</i>
      <div className="step-body">
        <div className="step-head">
          <b>{s.role}</b> <span className="mono small muted">{s.agent}</span>
          <span className="step-time mono small muted">{s.started_at ? fmtClock(s.started_at) : ''}{dur != null ? ` · ${fmtDur(dur)}` : ''}</span>
        </div>
        {s.summary && <div className="small">{s.summary}</div>}
        {s.error && <div className="small bad">{s.error}</div>}
        {s.evidence_refs.length > 0 && <RefList refs={s.evidence_refs} />}
      </div>
    </li>
  )
}

function Hyp({ h, winner }: { h: Hypothesis; winner: boolean }) {
  return (
    <article className={`hyp val-card-${h.validation_status} ${winner ? 'hyp-win' : ''}`} aria-label={`Hypothesis ${h.id}`}>
      <header className="hyp-head">
        <div><b className="hyp-id">{h.id}</b> <span className="mono small muted">{h.author_agent}</span></div>
        <ValidationBadge value={h.validation_status} />
      </header>
      <p className="hyp-desc">{h.description}</p>
      <div className="conf" title="Model estimate, not a probability">
        <div className="conf-bar"><i style={{ width: `${Math.round(h.confidence * 100)}%` }} /></div>
        <span className="small">{h.confidence.toFixed(2)} <span className="muted">model confidence</span></span>
      </div>

      <div className="ev ev-for">
        <div className="ev-title">Supporting evidence <span>{h.supporting_refs.length}</span></div>
        <RefList refs={h.supporting_refs} tone="for" />
      </div>
      <div className="ev ev-against">
        <div className="ev-title">Contradicting evidence <span>{h.contradicting_refs.length}</span></div>
        <RefList refs={h.contradicting_refs} tone="against" />
      </div>

      {h.challenges.length > 0 && (
        <div className="challenges">
          <div className="ev-title">Skeptic challenges</div>
          {h.challenges.map((c, i) => <ChallengeItem key={i} c={c} />)}
        </div>
      )}
      {h.alternatives.length > 0 && <Bullets title="Alternatives considered" items={h.alternatives} />}
      {h.missing_evidence.length > 0 && <Bullets title="Missing evidence" items={h.missing_evidence} />}
    </article>
  )
}

function ChallengeItem({ c }: { c: Challenge }) {
  const outcome = c.outcome
  return (
    <div className={`chal chal-${outcome ?? 'none'}`}>
      <div className="small"><b>{c.by ?? 'skeptic'}:</b> {c.challenge ?? JSON.stringify(c)}</div>
      {c.response && <div className="small muted">Response: {c.response}</div>}
      {outcome && <span className="chal-out">{outcome === 'upheld' ? 'challenge upheld' : outcome === 'withdrawn' ? 'challenge answered' : 'unresolved'}</span>}
    </div>
  )
}

function Bullets({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="bul">
      <div className="ev-title">{title}</div>
      <ul className="plain small">{items.map((a, i) => <li key={i}>{a}</li>)}</ul>
    </div>
  )
}
