import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useFetch } from '../hooks'
import { Card, CertaintyBadge, Empty, ErrorBox, Loading, Pill, SeverityBadge, Spinner, StatusBadge } from '../components/Common'
import { PageHead } from '../components/Layout'
import { RefChip, RefList } from '../components/Evidence'
import Topology from '../components/Topology'
import Waterfall from '../components/Waterfall'
import { fmtClock, fmtDateTime } from '../util'

export default function IncidentPage() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const inc = useFetch(() => api.incident(id), [id])
  const traceId = inc.data?.context.trace_ids[0]
  const trace = useFetch(async () => (traceId ? api.trace(id, traceId) : null), [id, traceId])
  const start = useAction(async () => {
    const r = await api.startInvestigation(id)
    nav(`/investigations/${r.investigation_id}`)
  })

  if (inc.loading && !inc.data) return <Loading label="Loading incident" />
  if (inc.error && !inc.data) return <ErrorBox error={inc.error} onRetry={inc.reload} />
  if (!inc.data) return null
  const d = inc.data
  const ctx = d.context
  const spans = trace.data?.spans ?? []
  const errSpans = spans.filter((s) => s.status_code === 'ERROR')
  const latest = d.investigations[0]

  return (
    <>
      <PageHead
        crumbs={[{ to: '/', label: 'Overview' }, { label: 'Incident' }]}
        title={d.title}
        sub={
          <div className="meta-row">
            <SeverityBadge value={d.severity} /> <StatusBadge value={d.status} />
            <span className="mono small muted">{d.id}</span>
            <span className="muted small">{fmtDateTime(d.first_seen)} → {fmtClock(d.last_seen)}</span>
          </div>
        }
        actions={
          <>
            {latest && <Link className="btn" to={`/investigations/${latest.id}`}>Open latest investigation</Link>}
            <button className="btn btn-primary" onClick={() => start.run()} disabled={start.pending}>
              {start.pending ? <><Spinner /> Starting…</> : 'Start investigation'}
            </button>
          </>
        }
      />
      {start.error && <ErrorBox error={start.error} />}

      <div className="grid-2">
        <Card title="Service topology" aside={<span className="muted small">caller → callee</span>}>
          {ctx.edges.length === 0 && ctx.services.length === 0 ? <Empty title="No topology" /> : <Topology services={ctx.services} edges={ctx.edges} spans={trace.data ? spans : undefined} />}
        </Card>
        <Card title="Correlation signals" aside={<span className="muted small">deterministic</span>}>
          {ctx.signals.length === 0 ? <Empty title="No signals" /> : (
            <ul className="signals">
              {ctx.signals.map((s) => (
                <li key={s.name}>
                  <div className="sig-head"><Pill tone={s.role}>{s.role}</Pill> <b className="mono">{s.name}</b> <RefChip ref_={`sig:${ctx.incident_id}:${s.name}`} /></div>
                  <div className="small">{s.description}</div>
                  <RefList refs={s.evidence} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Trace waterfall" aside={traceId && <span className="mono small muted">trace {traceId.slice(0, 12)}…</span>}>
        {trace.loading && <Loading label="Loading trace" />}
        {trace.error && <ErrorBox error={trace.error} onRetry={trace.reload} />}
        {trace.data && (spans.length ? <Waterfall spans={spans} /> : <Empty title="Trace has no spans" />)}
        {!traceId && <Empty title="Incident has no linked traces" />}
      </Card>

      <div className="grid-2">
        <Card title="Error timeline">
          {ctx.timeline.length === 0 ? <Empty title="No timeline entries" /> : (
            <ol className="timeline">
              {[...ctx.timeline].sort((a, b) => Date.parse(a.time) - Date.parse(b.time)).map((t, i) => (
                <li key={i} className={/error|exception|fail/i.test(t.what) ? 'tl-bad' : ''}>
                  <span className="tl-time mono">{fmtClock(t.time)}</span>
                  <i className="tl-dot" />
                  <div>
                    <div className="small"><b>{t.service}</b> · {t.what}</div>
                    <RefChip ref_={t.ref} />
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card title="Error details">
          {trace.loading ? <Loading /> : errSpans.length === 0 ? <Empty title="No error spans in the loaded trace" /> : (
            errSpans.map((s) => (
              <div className="err-block" key={s.span_id}>
                <div className="err-title"><b>{s.service_name}</b> · {s.name}</div>
                <div className="mono small bad">{s.status_message}</div>
                {s.events.filter((e) => e.name === 'exception').map((e) => (
                  <pre className="pre" key={e.idx}>{String(e.attributes['exception.stacktrace'] ?? `${e.attributes['exception.type']}: ${e.attributes['exception.message']}`)}</pre>
                ))}
                <RefChip ref_={`span:${s.trace_id}:${s.span_id}`} />
              </div>
            ))
          )}
        </Card>
      </div>

      <Card title="Correlated logs" aside={trace.data && <span className="muted small">{trace.data.logs.length} records</span>}>
        {trace.loading ? <Loading /> : !trace.data || trace.data.logs.length === 0 ? <Empty title="No correlated logs" hint="Logs are joined to the trace by trace_id." /> : (
          <div className="logs" role="table" aria-label="Correlated logs">
            {trace.data.logs.map((l) => (
              <div className={`log sev-${(l.severity ?? '').toLowerCase()}`} key={l.id ?? l.time} role="row">
                <span className="mono small muted">{fmtClock(l.time)}</span>
                <span className="log-sev">{l.severity}</span>
                <span className="log-svc">{l.service_name}</span>
                <span className="log-body mono">{l.body}</span>
                {l.id != null && <RefChip ref_={`log:${l.id}`} />}
              </div>
            ))}
          </div>
        )}
      </Card>

      {ctx.limitations.length > 0 && (
        <Card title="Telemetry limitations">
          <ul className="plain">{ctx.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </Card>
      )}

      {d.investigations.length > 0 && (
        <Card title="Investigations">
          <ul className="rows">
            {d.investigations.map((v) => (
              <li key={v.id}>
                <Link className="row-link" to={`/investigations/${v.id}`}>
                  <div className="row-main"><div className="row-title mono">{v.id}</div><div className="muted small">{fmtDateTime(v.started_at)}</div></div>
                  {v.certainty && v.status === 'completed' ? <CertaintyBadge value={v.certainty} /> : <StatusBadge value={v.status} />}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  )
}
