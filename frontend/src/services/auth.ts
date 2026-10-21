import { api, setCsrfToken } from '@/lib/api'
import type { Session } from '@/types/api'

export async function fetchSession(): Promise<Session> {
  const { data } = await api.get<Session>('/auth/session/')
  setCsrfToken(data.csrf_token)
  return data
}

export async function login(username: string, password: string): Promise<Session> {
  const { data } = await api.post<Session>('/auth/login/', { username, password })
  setCsrfToken(data.csrf_token)
  return data
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout/')
}
