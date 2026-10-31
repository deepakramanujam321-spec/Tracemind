/**
 * TraceMind API types. Mirrors docs/ARCHITECTURE.md §5/§7 and
 * tracemind/backend/tracemind/contracts.py. Datetimes are ISO-8601 strings.
 *
 * Section A mirrors contracts.py exactly.
 * Section B lists the response envelopes the UI needs; the orchestrator should
 * implement matching Pydantic models in tracemind/api/schemas.py.
 */

// ───────────── A. contracts.py ─────────────

/** span:<trace>:<span> | event:<trace>:<span>:<idx> | log:<id> | code:<repo>:<path>:<a>-<b> | sig:<incident>:<name> */
export type EvidenceRef = string
export type Validation = 'supported' | 'rejected' | 'inconclusive'
export type Certainty = 'confirmed' | 'suspected' | 'inconclusive'

export interface SpanEvent {
  idx: number
  name: string
  time: string
  attributes: Record<string, unknown>
}

export interface Span {
  trace_id: string
  span_id: string
  parent_span_id: string | null
  name: string
  kind: string | null
  service_name: string
  service_version: string | null
  environment: string | null
  start_time: string
  end_time: string
  duration_ms: number | null
  status_code: string | null // UNSET | OK | ERROR
  status_message: string | null
  attributes: Record<string, unknown>
  resource: Record<string, unknown>
  events: SpanEvent[]
}

export interface LogRecord {
  id: number | null
  time: string
  trace_id: string | null
  span_id: string | null
  service_name: string
  severity: string | null
  body: string | null
  attributes: Record<string, unknown>
}

export type SignalRole = 'origin' | 'transformation' | 'impact' | 'context'

export interface Signal {
  name: string
  description: string
  evidence: EvidenceRef[]
  role: SignalRole
}

export interface TimelineEntry {
  time: string
  ref: EvidenceRef
  service: string
  what: string
}

export interface IncidentContext {
  incident_id: string
  title: string
  trace_ids: string[]
  services: string[]
  edges: [string, string][]
  timeline: TimelineEntry[]
  signals: Signal[]
  limitations: string[]
}

/** challenge shape is open in contracts.py (dict); the UI reads these optional keys. */
export interface Challenge {
  by?: string // e.g. "skeptic"
  challenge?: string
  response?: string
  outcome?: 'upheld' | 'withdrawn' | 'unresolved'
  [k: string]: unknown
}

export interface Hypothesis {
  id: string
  author_agent: string
  description: string
  confidence: number // model estimate, NOT a probability
  supporting_refs: EvidenceRef[]
  contradicting_refs: EvidenceRef[]
  alternatives: string[]
  missing_evidence: string[]
  challenges: Challenge[]
  validation_status: Validation
}

// ───────────── B. response envelopes (new; orchestrator to implement) ─────────────

export type IncidentStatus = 'open' | 'investigating' | 'resolved'
export type Severity = 'low' | 'medium' | 'high' | 'critical'

export interface ServiceInfo {
  name: string
  version: string | null
  environment: string | null
  span_count: number
  error_count: number
  last_seen: string | null
}

/** GET /api/services */
export interface ServicesResponse {
  services: ServiceInfo[]
  edges: [string, string][]
}

export interface IncidentSummary {
  id: string
  title: string
  status: IncidentStatus
  severity: Severity
  services: string[]
  trace_ids: string[]
  signal_count: number
  first_seen: string
  last_seen: string
}

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface InvestigationSummary {
  id: string
  incident_id: string
  incident_title: string
  status: RunStatus
  certainty: Certainty | null
  started_at: string
  finished_at: string | null
}

/** GET /api/overview */
export interface OverviewResponse {
  services: ServiceInfo[]
  incidents: IncidentSummary[]
  investigations: InvestigationSummary[]
}

/** GET /api/incidents */
export interface IncidentListResponse {
  incidents: IncidentSummary[]
}

/** GET /api/incidents/{id} */
export interface IncidentDetail extends IncidentSummary {
  context: IncidentContext
  investigations: InvestigationSummary[]
}

/** POST /api/incidents/detect  -> sync result */
export interface DetectResponse {
  created: number
  refreshed: number
  incidents: IncidentSummary[]
}

/** GET /api/incidents/{id}/traces/{trace_id} */
export interface TraceDetail {
  trace_id: string
  spans: Span[] // events nested in each span
  logs: LogRecord[]
}

/** POST /api/incidents/{id}/investigations */
export interface StartInvestigationResponse {
  investigation_id: string
}

export type AgentStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export interface AgentStep {
  id: string
  agent: string // e.g. telemetry_agent, code_agent, hypothesizer_a, skeptic, adjudicator
  role: string // short human label, e.g. "Telemetry analysis"
  status: AgentStepStatus
  started_at: string | null
  finished_at: string | null
  summary: string | null
  evidence_refs: EvidenceRef[]
  error: string | null
}

export interface Adjudication {
  certainty: Certainty
  winning_hypothesis_id: string | null
  root_cause: string
  rationale: string
  rejected_hypothesis_ids: string[]
  evidence_refs: EvidenceRef[]
  limitations: string[]
  /** refs the engine rejected as unresolvable (anti-hallucination), if any */
  rejected_refs: EvidenceRef[]
}

export interface RemediationRef {
  id: string
  status: RemediationStatus
}

/** GET /api/investigations/{id} */
export interface Investigation {
  id: string
  incident_id: string
  incident_title: string
  status: RunStatus
  started_at: string
  finished_at: string | null
  error: string | null
  model: string | null // provider/model label actually used
  code_backend: 'graphify' | 'fallback' | null
  steps: AgentStep[]
  hypotheses: Hypothesis[]
  adjudication: Adjudication | null
  remediations: RemediationRef[]
}

export type CodeKind = 'span' | 'event' | 'log' | 'code' | 'sig'

export interface CodeExcerpt {
  repo_id: string
  path: string
  start_line: number
  end_line: number
  lines: string[]
  sha: string | null
}

/** GET /api/evidence/{ref}  (ref URL-encoded) */
export interface EvidenceRecord {
  ref: EvidenceRef
  kind: CodeKind
  resolved: boolean
  title: string
  /** span / event / log / signal record as stored; null for code */
  record: Record<string, unknown> | null
  excerpt: CodeExcerpt | null
  error: string | null
}

/** POST /api/investigations/{id}/remediations  body: { repository_id?: string } */
export interface StartRemediationResponse {
  remediation_id: string
}

export type RemediationStatus =
  | 'queued'
  | 'running'
  | 'patch_generated'
  | 'tested'
  | 'verified'
  | 'failed'

export interface CommandRun {
  id: string
  command: string
  phase: string // e.g. "baseline", "apply", "test", "regression"
  exit_code: number | null
  duration_ms: number | null
  stdout: string
  stderr: string
  started_at: string
}

export interface TestResult {
  name: string
  outcome: 'passed' | 'failed' | 'skipped' | 'error'
  phase: string // "baseline" | "after_patch"
  detail: string | null
}

/** GET /api/remediations/{id} */
export interface Remediation {
  id: string
  investigation_id: string
  incident_id: string
  status: RemediationStatus
  repository_id: string | null
  base_sha: string | null
  source_refs: EvidenceRef[] // code:... refs the patch is based on
  summary: string | null
  diff: string | null // unified diff
  command_runs: CommandRun[]
  test_results: TestResult[]
  error: string | null
  approved: boolean
  approved_by: string | null
  approved_at: string | null
  created_at: string
}

export interface ApiErrorBody {
  detail?: string | { msg?: string }[]
}
