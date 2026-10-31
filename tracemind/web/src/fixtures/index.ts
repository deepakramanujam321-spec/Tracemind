import type { AgentStep, EvidenceRecord, Investigation, Remediation } from '../api/types'
import { ApiError } from '../api/client'
import * as D from './data'

// In-memory progress so polling/async states are exercisable in fixture mode.
let invStart: number | null = null
let remStart: number | null = null
let approved: { by: string; at: string } | null = null

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function investigation(): Investigation {
  const base: Investigation = {
    id: D.INVESTIGATION_ID,
    incident_id: D.INCIDENT_ID,
    incident_title: D.CONTEXT.title,
    status: 'completed',
    started_at: D.INVESTIGATION_SUMMARY.started_at,
    finished_at: D.INVESTIGATION_SUMMARY.finished_at,
    error: null,
    model: null,
    code_backend: 'graphify',
    steps: D.STEPS,
    hypotheses: D.HYPOTHESES,
    adjudication: D.ADJUDICATION,
    remediations: [{ id: D.REMEDIATION_ID, status: remediation().status }],
  }
  if (invStart === null) return base
  const n = Math.floor((Date.now() - invStart) / 1400)
  if (n >= D.STEPS.length) return base
  const steps: AgentStep[] = D.STEPS.map((s, i) =>
    i < n ? s : i === n ? { ...s, status: 'running', finished_at: null, summary: null, evidence_refs: [] }
      : { ...s, status: 'pending', started_at: null, finished_at: null, summary: null, evidence_refs: [] })
  return { ...base, status: 'running', finished_at: null, steps, hypotheses: n > 5 ? D.HYPOTHESES : [], adjudication: null, remediations: [] }
}

function remediation(): Remediation {
  const base: Remediation = { ...D.REMEDIATION, approved: !!approved, approved_by: approved?.by ?? null, approved_at: approved?.at ?? null }
  if (remStart === null) return base
  const e = Date.now() - remStart
  if (e < 1500) return { ...base, status: 'running', diff: null, command_runs: [], test_results: [], summary: null, source_refs: [] }
  if (e < 3000) return { ...base, status: 'patch_generated', command_runs: D.COMMANDS.slice(0, 1), test_results: [] }
  if (e < 4500) return { ...base, status: 'tested', command_runs: D.COMMANDS.slice(0, 3), test_results: D.TESTS.slice(0, 3) }
  return base
}

function evidence(ref: string): EvidenceRecord {
  const mk = (kind: EvidenceRecord['kind'], title: string, record: Record<string, unknown> | null, excerpt: EvidenceRecord['excerpt'] = null): EvidenceRecord =>
    ({ ref, kind, resolved: true, title, record, excerpt, error: null })
  const bad = (kind: EvidenceRecord['kind'], error: string): EvidenceRecord =>
    ({ ref, kind, resolved: false, title: 'Unresolvable reference', record: null, excerpt: null, error })
  const [kind, ...rest] = ref.split(':')
  if (kind === 'span') {
    const s = D.SPANS.find((x) => x.trace_id === rest[0] && x.span_id === rest[1])
    return s ? mk('span', `${s.service_name} · ${s.name}`, s as never) : bad('span', 'No such span in stored telemetry')
  }
  if (kind === 'event') {
    const s = D.SPANS.find((x) => x.trace_id === rest[0] && x.span_id === rest[1])
    const ev = s?.events.find((x) => x.idx === Number(rest[2]))
    return s && ev ? mk('event', `${s.service_name} · ${ev.name} on ${s.name}`, { ...ev, span: s.name, service_name: s.service_name }) : bad('event', 'No such span event')
  }
  if (kind === 'log') {
    const l = D.LOGS.find((x) => String(x.id) === rest[0])
    return l ? mk('log', `${l.service_name} · ${l.severity}`, l as never) : bad('log', 'No such log record')
  }
  if (kind === 'sig') {
    const s = D.CONTEXT.signals.find((x) => x.name === rest[1])
    return s ? mk('sig', `Signal · ${s.name}`, s as never) : bad('sig', 'No such correlation signal')
  }
  if (kind === 'code') {
    const m = /^code:([^:]+):(.+):(\d+)-(\d+)$/.exec(ref)
    if (!m) return bad('code', 'Malformed code reference')
    const file = D.FILES[m[2]]
    if (!file) return bad('code', `File not found in repository: ${m[2]}`)
    const all = file.split('\n')
    const a = Number(m[3]), b = Number(m[4])
    if (b > all.length) return bad('code', `Line range exceeds file length (${all.length})`)
    return mk('code', `${m[2]}:${a}-${b}`, null, { repo_id: m[1], path: m[2], start_line: a, end_line: b, lines: all.slice(a - 1, b), sha: D.SHA_FULL })
  }
  return bad('span', 'Unknown reference kind')
}

export async function handleFixture(method: string, path: string, _body?: unknown): Promise<unknown> {
  await sleep(220)
  const p = decodeURIComponent(path)
  const notFound = () => new ApiError(404, `fixture: no route for ${method} ${p}`)
  if (method === 'GET') {
    if (p === '/overview') return { services: D.SERVICES, incidents: [D.INCIDENT_SUMMARY], investigations: [{ ...D.INVESTIGATION_SUMMARY, status: investigation().status }] }
    if (p === '/services') return { services: D.SERVICES, edges: D.CONTEXT.edges }
    if (p === '/incidents') return { incidents: [D.INCIDENT_SUMMARY] }
    if (p === `/incidents/${D.INCIDENT_ID}`) return D.INCIDENT_DETAIL
    if (p === `/incidents/${D.INCIDENT_ID}/traces/${D.TRACE_ID}`) return { trace_id: D.TRACE_ID, spans: D.SPANS, logs: D.LOGS }
    if (p === `/investigations/${D.INVESTIGATION_ID}`) return investigation()
    if (p === `/remediations/${D.REMEDIATION_ID}`) return remediation()
    if (p.startsWith('/evidence/')) return evidence(p.slice('/evidence/'.length))
  }
  if (method === 'POST') {
    if (p === '/incidents/detect') return { created: 0, refreshed: 1, incidents: [D.INCIDENT_SUMMARY] }
    if (p === `/incidents/${D.INCIDENT_ID}/investigations`) { invStart = Date.now(); return { investigation_id: D.INVESTIGATION_ID } }
    if (p === `/investigations/${D.INVESTIGATION_ID}/remediations`) { remStart = Date.now(); return { remediation_id: D.REMEDIATION_ID } }
    if (p === `/remediations/${D.REMEDIATION_ID}/approve`) {
      approved = { by: 'local-operator', at: new Date().toISOString() }
      return remediation()
    }
  }
  throw notFound()
}
