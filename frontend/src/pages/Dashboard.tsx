import { useCallback, useEffect, useState } from 'react'
import AnalysisPanel from '../components/AnalysisPanel'
import HistoryTable from '../components/HistoryTable'
import IncidentForm from '../components/IncidentForm'
import MemoryPanel from '../components/MemoryPanel'
import ResolutionPanel from '../components/ResolutionPanel'
import { Badge, ErrorBox } from '../components/ui'
import { api, session, type AnalyzeResponse, type Health, type IncidentInput, type IncidentSummary, type Me } from '../services/api'

const FLOW = ['Hindsight Recall', 'Groq Analysis', 'Confirm Resolution', 'Hindsight Retain']

export default function Dashboard({ user, onLogout }: { user: string; onLogout: () => void }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [incidents, setIncidents] = useState<IncidentSummary[]>([])
  const [result, setResult] = useState<AnalyzeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retained, setRetained] = useState(false)

  // Both calls are scoped server-side to the authenticated user.
  const refresh = useCallback(() => {
    api.list().then(setIncidents).catch(() => {})
    api.me().then(setMe).catch(() => {})
  }, [])

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    refresh()
  }, [refresh])

  async function analyze(input: IncidentInput) {
    setLoading(true)
    setError(null)
    setResult(null)
    setRetained(false)
    try {
      setResult(await api.analyze(input))
      refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function logout() {
    await api.logout().catch(() => {})
    session.clear()
    onLogout()
  }

  const step = !result ? (loading ? 1 : 0) : retained ? 4 : 3

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900/80">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-rose-500/15 text-rose-400">⚠</div>
            <div>
              <h1 className="text-lg font-semibold text-white">Incident Response Agent</h1>
              <p className="text-xs text-slate-500">Remembers past incidents with Hindsight · reasons with Groq</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {health && (
              <>
                <Badge tone={health.hindsight.ok && me?.hindsight.ok !== false ? 'violet' : 'red'}>
                  Hindsight{' '}
                  {!health.hindsight.ok || me?.hindsight.ok === false
                    ? '· unavailable'
                    : me?.hindsight.memory_units !== undefined
                      ? `· your memory: ${me.hindsight.memory_units} units`
                      : '· connected'}
                </Badge>
                <Badge tone={health.groq.configured ? 'sky' : 'red'}>
                  Groq {health.groq.configured ? `· ${health.groq.model}` : '· not configured'}
                </Badge>
              </>
            )}
            <span className="ml-2 text-sm text-slate-400">{user}</span>
            <button onClick={logout} className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800">
              Log out
            </button>
          </div>
        </div>
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-2 px-6 pb-3 text-xs">
          {FLOW.map((s, i) => (
            <span key={s} className="flex items-center gap-2">
              <span className={`rounded-full px-2.5 py-1 ${i < step ? 'bg-emerald-500/15 text-emerald-300' : i === step && loading ? 'bg-sky-500/15 text-sky-300' : 'bg-slate-800 text-slate-500'}`}>
                {i + 1}. {s}
              </span>
              {i < FLOW.length - 1 && <span className="text-slate-700">→</span>}
            </span>
          ))}
        </div>
      </header>

      {health && !health.hindsight.ok && (
        <div className="mx-auto max-w-7xl px-6 pt-4">
          <ErrorBox>Hindsight is not reachable ({health.hindsight.detail}). Historical memory will not be available.</ErrorBox>
        </div>
      )}

      <main className="mx-auto grid max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[420px_1fr]">
        <div className="space-y-6">
          <IncidentForm loading={loading} onSubmit={analyze} />
        </div>
        <div className="space-y-6">
          {error && <ErrorBox>{error}</ErrorBox>}
          {!result && !error && (
            <div className="flex h-full min-h-64 items-center justify-center rounded-xl border border-dashed border-slate-800 p-10 text-center text-sm text-slate-500">
              {loading
                ? 'Recalling similar incidents from Hindsight, then asking Groq to analyze…'
                : 'Describe an incident and click “Analyze Incident”. The agent first recalls relevant past incidents from Hindsight memory.'}
            </div>
          )}
          {result && (
            <>
              <MemoryPanel recall={result.recall} />
              <AnalysisPanel result={result} />
              <ResolutionPanel
                key={result.incident_id}
                incidentId={result.incident_id}
                onSaved={() => {
                  setRetained(true)
                  refresh()
                }}
              />
            </>
          )}
        </div>
      </main>

      <div className="mx-auto max-w-7xl px-6 pb-10">
        <HistoryTable incidents={incidents} />
      </div>
    </div>
  )
}
