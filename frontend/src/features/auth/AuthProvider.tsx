import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { setSessionExpiredHandler } from '@/lib/api'
import * as authService from '@/services/auth'
import type { Session, SessionUser } from '@/types/api'

type Status = 'loading' | 'authenticated' | 'anonymous' | 'error'

interface AuthValue {
  status: Status
  user: SessionUser | null
  expired: boolean
  signIn: (username: string, password: string) => Promise<SessionUser>
  signOut: () => Promise<void>
  retry: () => void
}

const AuthContext = createContext<AuthValue | null>(null)
export const SESSION_KEY = ['session'] as const

// Drop cached data from the previous user, but keep the session query itself:
// clear() would detach the observer that the provider is subscribed to.
function clearUserData(queryClient: QueryClient) {
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== SESSION_KEY[0] })
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [expired, setExpired] = useState(false)
  // The server session is the source of truth: refreshing the page re-asks it.
  const query = useQuery({ queryKey: SESSION_KEY, queryFn: authService.fetchSession, staleTime: 5 * 60_000, retry: 1 })

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setExpired(true)
      queryClient.setQueryData<Session>(SESSION_KEY, { authenticated: false, user: null })
    })
    return () => setSessionExpiredHandler(undefined)
  }, [queryClient])

  const signIn = useCallback(
    async (username: string, password: string) => {
      const session = await authService.login(username, password)
      setExpired(false)
      clearUserData(queryClient)
      queryClient.setQueryData(SESSION_KEY, session)
      return session.user as SessionUser
    },
    [queryClient],
  )

  const signOut = useCallback(async () => {
    try {
      await authService.logout()
    } finally {
      setExpired(false)
      clearUserData(queryClient)
      queryClient.setQueryData<Session>(SESSION_KEY, { authenticated: false, user: null })
    }
  }, [queryClient])

  const status: Status = query.isPending ? 'loading' : query.isError ? 'error' : query.data?.authenticated ? 'authenticated' : 'anonymous'
  const value = useMemo<AuthValue>(
    () => ({ status, user: query.data?.user ?? null, expired, signIn, signOut, retry: () => void query.refetch() }),
    [status, query, expired, signIn, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
