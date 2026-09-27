import type { RecallResult } from '../services/api'
import { Badge, Card, severityTone } from './ui'

function Row({ label, value, tone }: { label: string; value: string | null; tone?: string }) {
  if (!value) return null
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className={`text-sm ${tone ?? 'text-slate-200'}`}>{value}</dd>
    </div>
  )
}

export default function MemoryPanel({ recall }: { recall: RecallResult }) {
  const statusBadge =
    recall.status === 'ok' ? (
      <Badge tone="violet">{recall.memories.length} relevant memor{recall.memories.length === 1 ? 'y' : 'ies'} found</Badge>
    ) : recall.status === 'empty' ? (
      <Badge tone="slate">No relevant memory yet</Badge>
    ) : (
      <Badge tone="red">Memory unavailable</Badge>
    )

  return (
    <Card title="Hindsight Memory" icon={<span className="text-violet-400">◆</span>} right={statusBadge} className="border-violet-500/30">
      <p
        className={`mb-4 text-sm ${
          recall.status === 'error' ? 'text-rose-300' : recall.status === 'ok' ? 'text-violet-200' : 'text-slate-400'
        }`}
      >
        {recall.message}
        {recall.status === 'empty' && ' Once you save this incident’s resolution, the agent will remember it.'}
      </p>

      <div className="space-y-4">
        {recall.memories.map((m, i) => (
          <article key={m.incident_id ?? i} className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-violet-300">Previous Incident</span>
              {m.incident_id && <Badge>{m.incident_id}</Badge>}
              {m.service && <Badge tone="sky">{m.service}</Badge>}
              {m.environment && <Badge>{m.environment}</Badge>}
              {m.severity && <Badge tone={severityTone(m.severity)}>{m.severity}</Badge>}
              {m.resolved_at && <span className="text-xs text-slate-500">resolved {new Date(m.resolved_at).toLocaleString()}</span>}
            </div>
            <h3 className="mb-3 font-semibold text-white">{m.title ?? 'Recalled incident'}</h3>
            <dl className="grid gap-3 sm:grid-cols-2">
              <Row label="Root Cause" value={m.root_cause} tone="text-amber-200" />
              <Row label="Previous Solution" value={m.solution} tone="text-emerald-200" />
              <Row label="Outcome" value={m.outcome} />
              <Row label="Failed Approaches" value={m.failed_approaches} tone="text-rose-200" />
            </dl>
            {m.why_relevant.length > 0 && (
              <div className="mt-3 rounded-md bg-slate-950/60 p-3">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Why this memory is relevant</div>
                <ul className="list-inside list-disc text-sm text-slate-300">
                  {m.why_relevant.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
            {m.facts.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-300">
                  {m.facts.length} fact{m.facts.length === 1 ? '' : 's'} recalled by Hindsight
                </summary>
                <ul className="mt-2 space-y-1 text-xs text-slate-400">
                  {m.facts.map((f, j) => (
                    <li key={j}>
                      <span className="text-slate-600">[{f.type}]</span> {f.text}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </article>
        ))}
        {recall.other_facts.length > 0 && (
          <div className="rounded-lg border border-slate-800 p-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Other related knowledge</div>
            <ul className="space-y-1 text-sm text-slate-300">
              {recall.other_facts.map((f, i) => (
                <li key={i}>• {f.text}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  )
}
