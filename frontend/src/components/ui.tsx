import type { ReactNode } from 'react'

export function Card({ title, icon, right, children, className = '' }: {
  title: string
  icon?: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-xl border border-slate-800 bg-slate-900/70 ${className}`}>
      <header className="flex items-center justify-between gap-3 border-b border-slate-800 px-5 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold tracking-wide text-white">
          {icon}
          {title}
        </h2>
        {right}
      </header>
      <div className="p-5">{children}</div>
    </section>
  )
}

const tones = {
  slate: 'bg-slate-700/40 text-slate-300 ring-slate-600/40',
  green: 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/30',
  amber: 'bg-amber-500/10 text-amber-300 ring-amber-500/30',
  red: 'bg-rose-500/10 text-rose-300 ring-rose-500/30',
  sky: 'bg-sky-500/10 text-sky-300 ring-sky-500/30',
  violet: 'bg-violet-500/10 text-violet-300 ring-violet-500/30',
}
export type Tone = keyof typeof tones

export function Badge({ tone = 'slate', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${tones[tone]}`}>
      {children}
    </span>
  )
}

export const severityTone = (s: string | null | undefined): Tone =>
  s === 'Critical' ? 'red' : s === 'High' ? 'amber' : s === 'Medium' ? 'sky' : 'slate'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-400">{label}</span>
      {children}
    </label>
  )
}

export const inputCls =
  'w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-sky-500'

export function Spinner() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{children}</div>
}
