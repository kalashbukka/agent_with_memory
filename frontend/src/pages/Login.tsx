import { useState, type FormEvent } from 'react'
import { api, session, type SessionUser } from '../services/api'

type Mode = 'login' | 'register'

export default function Login({ onLogin }: { onLogin: (user: SessionUser) => void }) {
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = mode === 'login' ? await api.login(username, password) : await api.register(username, password)
      session.clear() // never carry anything over from a previous account
      session.set(res)
      onLogin({ token: res.token, user_id: res.user_id, username: res.username })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
  }

  const inputCls = 'mb-4 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-sky-500'

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-xl border border-slate-800 bg-slate-900 p-8 shadow-2xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-rose-500/15 text-xl text-rose-400">⚠</div>
          <div>
            <h1 className="text-lg font-semibold text-white">Incident Response Agent</h1>
            <p className="text-xs text-slate-400">Powered by Hindsight memory + Groq</p>
          </div>
        </div>

        <div className="mb-5 grid grid-cols-2 rounded-md bg-slate-950 p-1 text-sm">
          {(['login', 'register'] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => switchMode(m)}
              className={`rounded py-1.5 ${mode === m ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-slate-200'}`}
            >
              {m === 'login' ? 'Sign in' : 'Create account'}
            </button>
          ))}
        </div>

        <label className="mb-1 block text-xs font-medium text-slate-400">Username</label>
        <input
          className={inputCls}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
          {...(mode === 'register' && { minLength: 3, maxLength: 32, pattern: '[A-Za-z0-9_.\\-]+', title: '3-32 letters, digits, . _ -' })}
        />
        <label className="mb-1 block text-xs font-medium text-slate-400">Password</label>
        <input
          type="password"
          className={inputCls}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          required
          minLength={mode === 'register' ? 6 : undefined}
        />
        {mode === 'register' && (
          <p className="-mt-2 mb-4 text-xs text-slate-500">You get your own private incident history and Hindsight memory.</p>
        )}
        {error && <p className="mb-4 rounded-md bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{error}</p>}
        <button
          disabled={loading}
          className="w-full rounded-md bg-sky-600 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {loading ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>
      </form>
    </div>
  )
}
