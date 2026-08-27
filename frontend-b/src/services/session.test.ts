import { beforeEach, describe, expect, it } from 'vitest'
import { audienceForUser, clearSession, readSession, saveSession } from './session'

describe('admin session storage', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips a platform admin session', () => {
    saveSession({ accessToken: 'token', audience: 'admin', user: { id: 'a1', roles: ['platform_admin'] } })
    expect(readSession()).toMatchObject({ accessToken: 'token', audience: 'admin', user: { id: 'a1' } })
  })

  it('clears a stale session', () => {
    saveSession({ accessToken: 'token', audience: 'admin', user: { id: 'a1', roles: ['platform_admin'] } })
    clearSession()
    expect(readSession()).toBeUndefined()
  })

  it('recognizes a provider role as an admin-audience backoffice session', () => {
    expect(audienceForUser({ id: 'provider-user', roles: ['provider_staff'] })).toBe('admin')
  })
})
