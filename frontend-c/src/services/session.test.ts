import { beforeEach, describe, expect, it } from 'vitest'
import { clearSession, readSession, saveSession } from './session'

describe('consumer session storage', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips a consumer session', () => {
    saveSession({ accessToken: 'token', audience: 'consumer', user: { id: 'u1', roles: ['user'] } })
    expect(readSession()).toMatchObject({ accessToken: 'token', audience: 'consumer', user: { id: 'u1' } })
  })

  it('clears a stale session', () => {
    saveSession({ accessToken: 'token', audience: 'consumer', user: { id: 'u1', roles: ['user'] } })
    clearSession()
    expect(readSession()).toBeUndefined()
  })
})
