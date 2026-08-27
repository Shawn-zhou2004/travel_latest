export interface SessionUser {
  id: string
  nickname?: string | null
  avatar_asset_id?: string | null
  roles: string[]
  provider_memberships?: string[]
  entitlements?: string[]
}

export type SessionAudience = 'consumer' | 'admin'

export interface StoredSession {
  accessToken: string
  audience: SessionAudience
  user: SessionUser
}

const STORAGE_KEY = 'travel-platform.consumer-session'

function storage() {
  return typeof window === 'undefined' ? undefined : window.localStorage
}

export function readSession(): StoredSession | undefined {
  const value = storage()?.getItem(STORAGE_KEY)
  if (!value) return undefined
  try {
    const parsed = JSON.parse(value) as StoredSession
    if (!parsed.accessToken || !parsed.audience || !parsed.user?.id) return undefined
    return parsed
  } catch {
    return undefined
  }
}

export function saveSession(session: StoredSession) {
  storage()?.setItem(STORAGE_KEY, JSON.stringify(session))
}

export function clearSession() {
  storage()?.removeItem(STORAGE_KEY)
}

export function getAccessToken() {
  return readSession()?.accessToken
}

export function audienceForUser(user: SessionUser): SessionAudience {
  return user.roles.includes('platform_admin') ? 'admin' : 'consumer'
}
