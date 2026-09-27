// Thin client for the FastAPI backend. Only a session token is stored in the browser.

export type Severity = 'Low' | 'Medium' | 'High' | 'Critical'

export interface IncidentInput {
  title: string
  service: string
  environment: string
  severity: Severity
  symptoms: string
  error_logs: string
  recent_changes: string
  additional_instructions: string
}

export interface RecalledFact {
  text: string
  type: string | null
  score: number | null
}

export interface RecalledIncident {
  incident_id: string | null
  title: string | null
  service: string | null
  environment: string | null
  severity: string | null
  root_cause: string | null
  solution: string | null
  outcome: string | null
  failed_approaches: string | null
  resolved_at: string | null
  relevance_score: number | null
  why_relevant: string[]
  facts: RecalledFact[]
}

export interface RecallResult {
  status: 'ok' | 'empty' | 'error'
  message: string
  query: string
  memories: RecalledIncident[]
  other_facts: RecalledFact[]
}

export interface IncidentAnalysis {
  summary: string
  possible_causes: { cause: string; likelihood: string; evidence: string }[]
  historical_matches: { incident: string; similarities: string[]; differences: string[]; how_it_applies: string }[]
  recommended_checks: string[]
  recommended_solution: string
  confidence: 'Low' | 'Medium' | 'High'
  confidence_reason: string
}

export interface AnalyzeResponse {
  incident_id: string
  analysis: IncidentAnalysis
  recall: RecallResult
  model: string
}

export interface ResolutionInput {
  root_cause: string
  solution: string
  outcome: string
  failed_approaches: string
  notes: string
}

export interface ResolveResponse {
  incident_id: string
  retained: boolean
  message: string
  bank_id: string
  memory_document: string
}

export interface IncidentSummary {
  id: string
  title: string
  service: string
  environment: string
  severity: Severity
  status: 'analyzed' | 'resolved'
  created_at: string
  root_cause: string | null
  outcome: string | null
  resolved_at: string | null
  retained_in_hindsight: boolean
}

export interface Health {
  groq: { configured: boolean; model: string }
  hindsight: { configured: boolean; ok: boolean; detail: string }
}

export interface AuthResponse {
  token: string
  user_id: string
  username: string
}

export interface Me {
  user_id: string
  username: string
  hindsight: { ok: boolean; detail: string; memory_units?: number }
}

// Only the session identity is kept in the browser. Incident data is never cached here;
// it is always fetched from the server for the authenticated user.
const SESSION_KEY = 'ira_session'
const LEGACY_KEYS = ['ira_token', 'ira_user']

export interface SessionUser {
  token: string
  user_id: string
  username: string
}

export const session = {
  get current(): SessionUser | null {
    try {
      const raw = localStorage.getItem(SESSION_KEY)
      const s = raw ? (JSON.parse(raw) as SessionUser) : null
      return s?.token && s.user_id ? s : null
    } catch {
      return null
    }
  },
  get token() {
    return this.current?.token ?? null
  },
  set(auth: AuthResponse) {
    localStorage.setItem(SESSION_KEY, JSON.stringify({ token: auth.token, user_id: auth.user_id, username: auth.username }))
  },
  clear() {
    localStorage.removeItem(SESSION_KEY)
    LEGACY_KEYS.forEach((k) => localStorage.removeItem(k))
  },
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// Backend location. Override with VITE_API_URL (e.g. http://127.0.0.1:8000 for local FastAPI).
const API_BASE = (import.meta.env.VITE_API_URL ?? 'https://agent-with-memory-1.onrender.com').replace(/\/+$/, '')

let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (session.token) headers.set('Authorization', `Bearer ${session.token}`)

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, `Cannot reach the backend at ${API_BASE}.`)
  }
  if (res.status === 401 && !path.startsWith('/api/auth/login') && !path.startsWith('/api/auth/register')) {
    session.clear()
    onUnauthorized()
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail))
        message = body.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.at(-1)}: ${d.msg}`).join('; ')
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  login: (username: string, password: string) =>
    request<AuthResponse>('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  register: (username: string, password: string) =>
    request<AuthResponse>('/api/auth/register', { method: 'POST', body: JSON.stringify({ username, password }) }),
  me: () => request<Me>('/api/auth/me'),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),
  health: () => request<Health>('/api/health'),
  analyze: (incident: IncidentInput) =>
    request<AnalyzeResponse>('/api/incidents/analyze', { method: 'POST', body: JSON.stringify(incident) }),
  resolve: (id: string, resolution: ResolutionInput) =>
    request<ResolveResponse>(`/api/incidents/${encodeURIComponent(id)}/resolve`, {
      method: 'POST',
      body: JSON.stringify(resolution),
    }),
  list: () => request<IncidentSummary[]>('/api/incidents'),
  memories: (id: string) =>
    request<{ incident_id: string; recall: RecallResult; groq_prompt: string }>(
      `/api/incidents/${encodeURIComponent(id)}/memories`,
    ),
}
