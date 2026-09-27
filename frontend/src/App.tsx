import { useEffect, useState } from 'react'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import { session, setUnauthorizedHandler, type SessionUser } from './services/api'

export default function App() {
  const [user, setUser] = useState<SessionUser | null>(() => session.current)

  useEffect(() => {
    // Drop pre-isolation keys that had no user_id.
    if (!session.current) session.clear()
    setUnauthorizedHandler(() => setUser(null))
  }, [])

  if (!user) return <Login onLogin={setUser} />
  // key={user_id}: switching accounts remounts the dashboard so no previous user's
  // incidents, analysis or form state can survive in React state.
  return <Dashboard key={user.user_id} user={user.username} onLogout={() => setUser(null)} />
}
