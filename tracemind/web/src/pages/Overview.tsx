import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useFetch } from '../hooks'
import { Card, CertaintyBadge, Empty, ErrorBox, Loading, SeverityBadge, Spinner, StatusBadge } from '../components/Common'
import { PageHead } from '../components/Layout'
import { fmtDateTime, fmtDur } from '../util'

export default function Overview() {
  const { data, error, loading, reload } = useFetch(() => api.overview(), [])
  const detect = useAction(async () => {
    const r = await api.detect()
    reload()
    return r
  })

  const actions = (
    <>
      <button className="btn btn-primary" onClick={() => detect.run()} disabled={detect.pending}>
        {detect.pending ? <><Spinner /> Detecting…</> : 'Run detection'}
      </button>
    </>
  )

  return (
    <>
      <PageHead title="Overview" sub="Telemetry-grounded incident detection, investigation and remediation." actions={actions} />
      {detect.error && <ErrorBox error={detect.error} />}
      {detect.pending === false && detect.error === null && null}
      {loading && !data && <Loading label="Loading overview" />}
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {data && (
        <>
          <div className="stats">
            <Stat label="Services" value={data.services.length} />
            <Stat label="Open incidents" value={data.incidents.filter((i) => i.status !== 'resolved').length} tone={data.incidents.some((i) => i.status !== 'resolved') ? 'warn' : undefined} />
            <Stat label="Investigations" value={data.investigations.length} />
            <Stat label="Spans with errors" value={data.services.reduce((a, s) => a + s.error_count, 0)} tone={data.services.some((s) => s.error_count) ? 'bad' : undefined} />
          </div>

          <div className="grid-main">
            <Card title="Recent incidents" aside={<span className="muted small">{data.incidents.length} total</span>}>
              {data.incidents.length === 0 ? (
                <Empty title="No incidents yet" hint="Send traffic through the demo app, then run detection to correlate recent traces." />
              ) : (
                <ul className="rows">
                  {data.incidents.map((i) => (
                    <li key={i.id}>
                      <Link className="row-link" to={`/incidents/${i.id}`}>
                        <div className="row-main">
                          <div className="row-title">{i.title}</div>
                          <div className="muted small">
                            {i.services.join(' → ')} · {i.signal_count} signals · {fmtDateTime(i.last_seen)}
                          </div>
                        </div>
                        <SeverityBadge value={i.severity} />
                        <StatusBadge value={i.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Recent investigations">
              {data.investigations.length === 0 ? (
                <Empty title="No investigations yet" hint="Open an incident and start one." />
              ) : (
                <ul className="rows">
                  {data.investigations.map((v) => (
                    <li key={v.id}>
                      <Link className="row-link" to={`/investigations/${v.id}`}>
                        <div className="row-main">
                          <div className="row-title">{v.incident_title}</div>
                          <div className="muted small">
                            {v.id} · {fmtDateTime(v.started_at)}
                            {v.finished_at && ` · ${fmtDur(Date.parse(v.finished_at) - Date.parse(v.started_at))}`}
                          </div>
                        </div>
                        {v.certainty && v.status === 'completed' ? <CertaintyBadge value={v.certainty} /> : <StatusBadge value={v.status} />}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card title="Services">
            {data.services.length === 0 ? (
              <Empty title="No telemetry received" hint="Services appear once the OTLP collector forwards spans to the backend." />
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Service</th><th>Version</th><th>Environment</th><th className="num">Spans</th><th className="num">Errors</th><th>Last seen</th></tr></thead>
                  <tbody>
                    {data.services.map((s) => (
                      <tr key={s.name}>
                        <td className="mono strong">{s.name}</td>
                        <td className="mono">{s.version ?? '–'}</td>
                        <td>{s.environment ?? '–'}</td>
                        <td className="num">{s.span_count}</td>
                        <td className={`num ${s.error_count ? 'bad' : ''}`}>{s.error_count}</td>
                        <td className="mono small">{fmtDateTime(s.last_seen)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'warn' | 'bad' }) {
  return (
    <div className={`stat ${tone ? 'stat-' + tone : ''}`}>
      <div className="stat-v">{value}</div>
      <div className="stat-l">{label}</div>
    </div>
  )
}
