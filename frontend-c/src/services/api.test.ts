import { describe, expect, it } from 'vitest'
import type { AxiosAdapter } from 'axios'
import { createApiClient, normalizeApiError } from './api'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

describe('createApiClient', () => {
  it('adds the active consumer access token to protected requests', async () => {
    setActivePinia(createPinia())
    useAuthStore().setSession('consumer-token', 'consumer')
    const client = createApiClient('http://api.test')
    let authorization: string | undefined
    const adapter: AxiosAdapter = async (config) => {
      authorization = config.headers.get('Authorization') as string | undefined
      return { config, data: {}, headers: {}, status: 200, statusText: 'OK' }
    }

    await client.get('/protected', { adapter })
    expect(authorization).toBe('Bearer consumer-token')
  })

  it('adds a request ID and surfaces the API error code', async () => {
    const client = createApiClient('http://api.test')
    let sentRequestId: string | undefined
    const adapter: AxiosAdapter = async (config) => {
      sentRequestId = config.headers.get('X-Request-ID') as string | undefined
      return Promise.reject({
        config,
        isAxiosError: true,
        response: { data: { code: 'AUTH_REQUIRED', message: 'Sign in.', request_id: 'r1' } },
      })
    }

    await expect(client.get('/protected', { adapter })).rejects.toMatchObject({
      code: 'AUTH_REQUIRED', requestId: 'r1',
    })
    expect(sentRequestId).toMatch(/^[0-9a-f-]{36}$/)
    expect(client.defaults.baseURL).toBe('http://api.test/api/v1')
    expect(client.defaults.withCredentials).toBe(true)
  })

  it('preserves an API error that was already normalized by an interceptor', () => {
    const error = new Error('The itinerary is unavailable.') as Error & { code: string }
    error.code = 'ITINERARY_NOT_FOUND'

    expect(normalizeApiError(error)).toBe(error)
  })

  it('normalizes an Axios error rather than preserving its transport code', () => {
    const error = Object.assign(new Error('Request failed with status code 422'), {
      code: 'ERR_BAD_REQUEST',
      isAxiosError: true,
      response: { data: { code: 'TARGET_ITINERARY_EMPTY', message: 'Add an activity first.' } },
    })

    expect(normalizeApiError(error)).toMatchObject({ code: 'TARGET_ITINERARY_EMPTY', message: 'Add an activity first.' })
  })
})
