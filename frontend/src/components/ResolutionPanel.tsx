import { useState, type FormEvent } from 'react'
import { api, type ResolutionInput, type ResolveResponse } from '../services/api'
import { Card, ErrorBox, Field, Spinner, inputCls } from './ui'

type Step = 'ask' | 'form' | 'later' | 'saved'

export default function ResolutionPanel({ incidentId, onSaved }: { incidentId: string; onSaved: () => void }) {
  const [step, setStep] = useState<Step>('ask')
  const [form, setForm] = useState<ResolutionInput>({ root_cause: '', solution: '', outcome: '', failed_approaches: '', notes: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<ResolveResponse | null>(null)
  const set = (k: keyof ResolutionInput, v: string) => setForm((f) => ({ ...f, [k]: v }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const res = await api.resolve(incidentId, form)
      setSaved(res)
      setStep('saved')
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Resolution" icon={<span className="text-emerald-400">✓</span>}>
      {step === 'ask' && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-200">Was the incident resolved?</p>
          <div className="flex gap-2">
            <button onClick={() => setStep('form')} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500">
              Yes, Save Resolution
            </button>
            <button onClick={() => setStep('later')} className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
              Not Yet
            </button>
          </div>
        </div>
      )}

      {step === 'later' && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-400">
            OK. Nothing is stored in memory until the actual resolution is confirmed. Come back when it’s fixed.
          </p>
          <button onClick={() => setStep('form')} className="rounded-md border border-emerald-600/50 px-4 py-2 text-sm text-emerald-300 hover:bg-emerald-600/10">
            It’s resolved now
          </button>
        </div>
      )}

      {step === 'form' && (
        <form onSubmit={submit} className="space-y-3">
          <Field label="Actual Root Cause">
            <input className={inputCls} value={form.root_cause} onChange={(e) => set('root_cause', e.target.value)} placeholder="Redis connection pool exhaustion" required minLength={3} />
          </Field>
          <Field label="Actual Solution">
            <textarea className={inputCls} rows={2} value={form.solution} onChange={(e) => set('solution', e.target.value)} placeholder="Increased Redis connection pool from 50 to 150." required minLength={3} />
          </Field>
          <Field label="Outcome">
            <input className={inputCls} value={form.outcome} onChange={(e) => set('outcome', e.target.value)} placeholder="API latency returned to normal." required minLength={3} />
          </Field>
          <Field label="What didn’t work (optional)">
            <input className={inputCls} value={form.failed_approaches} onChange={(e) => set('failed_approaches', e.target.value)} placeholder="Restarting payment-api pods only helped for ~10 minutes." />
          </Field>
          <Field label="Additional Notes / Lessons learned (optional)">
            <textarea className={inputCls} rows={2} value={form.notes} onChange={(e) => set('notes', e.target.value)} placeholder="Add an alert on Redis pool utilisation > 80%." />
          </Field>
          {error && <ErrorBox>{error}</ErrorBox>}
          <div className="flex gap-2">
            <button disabled={saving} className="flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-60">
              {saving ? <><Spinner /> Saving to Hindsight…</> : 'Save to Hindsight'}
            </button>
            <button type="button" onClick={() => setStep('ask')} className="rounded-md px-3 py-2 text-sm text-slate-400 hover:text-slate-200">
              Cancel
            </button>
          </div>
        </form>
      )}

      {step === 'saved' && saved && (
        <div className="space-y-3">
          <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">✓ {saved.message}</div>
          <details>
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-300">Knowledge retained in Hindsight</summary>
            <pre className="mt-2 whitespace-pre-wrap rounded-md bg-slate-950 p-3 font-mono text-xs text-slate-400">{saved.memory_document}</pre>
          </details>
        </div>
      )}
    </Card>
  )
}
