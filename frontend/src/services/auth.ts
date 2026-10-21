import { api, setCsrfToken } from '@/lib/api'
import type { Session } from '@/types/api'

export async function fetchSession(): Promise<Session> {
  const { data } = await api.get<Session>('/auth/session/')
  setCsrfToken(data.csrf_token)
  return data
}

/** Any role signs in here (session cookie + CSRF); the full profile is then read back from the session. */
export async function login(username: string, password: string): Promise<Session> {
  const { data } = await api.post<{ csrf_token?: string }>('/auth/signin/', { username, password })
  setCsrfToken(data.csrf_token)
  return fetchSession()
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout/')
}

export interface RegisterInput { username: string; email: string; password: string; first_name: string; last_name?: string; phone_number: string }
export async function register(input: RegisterInput): Promise<void> {
  await api.post('/auth/register/', input)
}
export interface PartnerRegisterInput extends RegisterInput { vehicle_type: string; vehicle_number?: string }
export async function registerPartner(input: PartnerRegisterInput): Promise<void> {
  await api.post('/auth/partner-register/', input)
}
export async function requestPasswordReset(email: string): Promise<void> {
  await api.post('/auth/password/reset/', { email })
}
export async function confirmPasswordReset(uid: string, token: string, newPassword: string): Promise<void> {
  await api.post('/auth/password/reset/confirm/', { uid, token, new_password: newPassword })
}
export async function changePassword(current: string, next: string): Promise<void> {
  await api.post('/auth/password/change/', { current_password: current, new_password: next })
}
export interface ProfileInput { first_name?: string; last_name?: string; phone_number?: string; email?: string }
export async function updateProfile(input: ProfileInput): Promise<void> {
  await api.patch('/auth/me/', input)
}
