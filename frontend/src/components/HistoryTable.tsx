import type { IncidentSummary } from '../services/api'
import { Badge, Card, severityTone } from './ui'

export default function HistoryTable({ incidents }: { incidents: IncidentSummary[] }) {
  const retained = incidents.filter((i) => i.retained_in_hindsight).length
  return (
    <Card
      title="Incident History"
      icon={<span className="text-slate-400">≡</span>}
      right={<span className="text-xs text-slate-500">{retained} of {incidents.length} retained in Hindsight</span>}
    >
      {incidents.length === 0 ? (
        <p className="text-sm text-slate-500">No incidents yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-slate-500">
              <tr>
                {['Incident', 'Service', 'Severity', 'Environment', 'Date', 'Root Cause', 'Outcome', 'Memory'].map((h) => (
                  <th key={h} className="px-3 py-2 font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {incidents.map((i) => (
                <tr key={i.id} className="align-top">
                  <td className="px-3 py-2">
                    <div className="font-medium text-white">{i.title}</div>
                    <div className="text-xs text-slate-500">{i.id}</div>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{i.service}</td>
                  <td className="px-3 py-2"><Badge tone={severityTone(i.severity)}>{i.severity}</Badge></td>
                  <td className="px-3 py-2">{i.environment}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-400">{new Date(i.created_at).toLocaleString()}</td>
                  <td className="px-3 py-2 text-slate-300">{i.root_cause ?? <span className="text-slate-600">-</span>}</td>
                  <td className="px-3 py-2 text-slate-300">{i.outcome ?? <span className="text-slate-600">-</span>}</td>
                  <td className="px-3 py-2">
                    {i.retained_in_hindsight ? <Badge tone="violet">Retained</Badge> : <Badge>Open</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
