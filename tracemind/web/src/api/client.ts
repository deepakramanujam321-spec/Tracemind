import type {
  DetectResponse,
  EvidenceRecord,
  IncidentDetail,
  IncidentListResponse,
  Investigation,
  OverviewResponse,
  Remediation,
  ServicesResponse,
  StartInvestigationResponse,
  StartRemediationResponse,
  TraceDetail,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Fixture mode is explicit: ?fixtures=1 (remembered for the tab session), ?fixtures=0 clears. */
export function fixturesActive(): boolean {
  try {
    const q = new URLSearchParams(window.location.search).get('fixtures')
    if (q === '1') sessionStorage.setItem('tm.fixtures', '1')
    if (q === '0') sessionStorage.removeItem('tm.fixtures')
    return sessionStorage.getItem('tm.fixtures') === '1'
  } catch {
    return new URLSearchParams(window.location.search).get('fixtures') === '1'
  }
}

const KEY = 'tm.apiKey'

export function getApiKey(): string {
  try {
    return sessionStorage.getItem(KEY) ?? ''
  } catch {
    return ''
  }
}

export function setApiKey(key: string): void {
  try {
    if (key) sessionStorage.setItem(KEY, key)
    else sessionStorage.removeItem(KEY)
  } catch {
    /* storage unavailable: key lives only until reload */
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (fixturesActive()) {
    const { handleFixture } = await import('../fixtures')
    return (await handleFixture(method, path, body)) as T
  }
  let res: Response
  try {
    res = await fetch(BASE + path, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(getApiKey() ? { Authorization: `Bearer ${getApiKey()}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the TraceMind backend (is tracemind-backend running on :8100?)')
  }
  if (res.status === 401) window.dispatchEvent(new Event('tm-unauthorized'))
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      if (typeof j.detail === 'string') msg = j.detail
      else if (Array.isArray(j.detail)) msg = j.detail.map((d: { msg?: string }) => d.msg).join('; ')
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg)
  }
  return (await res.json()) as T
}

const enc = encodeURIComponent

export const api = {
  overview: () => request<OverviewResponse>('GET', '/overview'),
  services: () => request<ServicesResponse>('GET', '/services'),
  incidents: () => request<IncidentListResponse>('GET', '/incidents'),
  incident: (id: string) => request<IncidentDetail>('GET', `/incidents/${enc(id)}`),
  detect: () => request<DetectResponse>('POST', '/incidents/detect', {}),
  trace: (incidentId: string, traceId: string) =>
    request<TraceDetail>('GET', `/incidents/${enc(incidentId)}/traces/${enc(traceId)}`),
  startInvestigation: (incidentId: string) =>
    request<StartInvestigationResponse>('POST', `/incidents/${enc(incidentId)}/investigations`, {}),
  investigation: (id: string) => request<Investigation>('GET', `/investigations/${enc(id)}`),
  evidence: (ref: string) => request<EvidenceRecord>('GET', `/evidence/${enc(ref)}`),
  startRemediation: (investigationId: string) =>
    request<StartRemediationResponse>('POST', `/investigations/${enc(investigationId)}/remediations`, {}),
  remediation: (id: string) => request<Remediation>('GET', `/remediations/${enc(id)}`),
  approve: (id: string) => request<Remediation>('POST', `/remediations/${enc(id)}/approve`, {}),
}
