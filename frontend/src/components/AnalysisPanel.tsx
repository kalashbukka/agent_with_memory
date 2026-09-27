import { useState } from 'react'
import { api, type AnalyzeResponse } from '../services/api'
import { Badge, Card, type Tone } from './ui'

const likelihoodTone = (l: string): Tone => (l === 'High' ? 'red' : l === 'Medium' ? 'amber' : 'slate')
const confidenceTone = (c: string): Tone => (c === 'High' ? 'green' : c === 'Medium' ? 'amber' : 'red')

function H({ children }: { children: string }) {
  return <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{children}</h3>
}

export default function AnalysisPanel({ result }: { result: AnalyzeResponse }) {
  const a = result.analysis
  const [prompt, setPrompt] = useState<string | null>(null)

  async function togglePrompt() {
    if (prompt !== null) return setPrompt(null)
    const res = await api.memories(result.incident_id)
    setPrompt(res.groq_prompt)
  }

  return (
    <Card
      title="AI Analysis"
      icon={<span className="text-sky-400">▲</span>}
      right={
        <div className="flex items-center gap-2">
          <Badge>{result.incident_id}</Badge>
          <Badge tone="sky">Groq · {result.model}</Badge>
        </div>
      }
    >
      <div className="space-y-6">
        <div>
          <H>Summary</H>
          <p className="text-sm leading-relaxed text-slate-200">{a.summary}</p>
        </div>

        <div>
          <H>Possible Causes</H>
          <ul className="space-y-2">
            {a.possible_causes.map((c, i) => (
              <li key={i} className="rounded-md border border-slate-800 bg-slate-950/50 p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-white">{c.cause}</span>
                  <Badge tone={likelihoodTone(c.likelihood)}>{c.likelihood}</Badge>
                </div>
                {c.evidence && <p className="mt-1 text-xs text-slate-400">{c.evidence}</p>}
              </li>
            ))}
          </ul>
        </div>

        <div>
          <H>Historical Matches</H>
          {a.historical_matches.length === 0 ? (
            <p className="text-sm text-slate-500">No historical incidents were used for this analysis.</p>
          ) : (
            <ul className="space-y-3">
              {a.historical_matches.map((m, i) => (
                <li key={i} className="rounded-md border border-violet-500/20 bg-violet-500/5 p-3 text-sm">
                  <div className="mb-2 font-medium text-violet-200">{m.incident}</div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <div className="text-[11px] font-semibold uppercase text-emerald-400">Similarities</div>
                      <ul className="list-inside list-disc text-slate-300">{m.similarities.map((s, j) => <li key={j}>{s}</li>)}</ul>
                    </div>
                    <div>
                      <div className="text-[11px] font-semibold uppercase text-amber-400">Differences</div>
                      <ul className="list-inside list-disc text-slate-300">{m.differences.map((s, j) => <li key={j}>{s}</li>)}</ul>
                    </div>
                  </div>
                  {m.how_it_applies && <p className="mt-2 text-slate-300"><span className="text-slate-500">How it applies now: </span>{m.how_it_applies}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <H>Recommended Checks</H>
          <ol className="list-inside list-decimal space-y-1 text-sm text-slate-200">
            {a.recommended_checks.map((c, i) => <li key={i}>{c}</li>)}
          </ol>
        </div>

        <div>
          <H>Recommended Solution</H>
          <p className="rounded-md border border-emerald-500/20 bg-emerald-500/5 p-3 text-sm leading-relaxed text-emerald-100">{a.recommended_solution}</p>
        </div>

        <div>
          <H>Confidence</H>
          <div className="flex items-center gap-3">
            <Badge tone={confidenceTone(a.confidence)}>{a.confidence}</Badge>
            <span className="text-sm text-slate-400">{a.confidence_reason}</span>
          </div>
        </div>

        <div>
          <button onClick={togglePrompt} className="text-xs text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline">
            {prompt === null ? 'Show exact prompt sent to Groq (current incident + Hindsight memory)' : 'Hide prompt'}
          </button>
          {prompt !== null && (
            <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-3 font-mono text-xs text-slate-400">{prompt}</pre>
          )}
        </div>
      </div>
    </Card>
  )
}
