import axios, { type AxiosError, type AxiosInstance } from 'axios'
import { clearSession, getAccessToken, saveSession, type SessionUser } from './session'

export interface ApiError extends Error {
  code: string
  message: string
  requestId?: string
  details?: unknown
}

interface ApiErrorEnvelope { code?: unknown; message?: unknown; request_id?: unknown; details?: unknown }

export function normalizeApiError(error: unknown): ApiError {
  const envelope = (axios.isAxiosError(error) ? error.response?.data : undefined) as ApiErrorEnvelope | undefined
  const message = typeof envelope?.message === 'string' ? envelope.message : 'The request could not be completed.'
  const normalized = new Error(message) as ApiError
  normalized.code = typeof envelope?.code === 'string' ? envelope.code : 'REQUEST_FAILED'
  normalized.requestId = typeof envelope?.request_id === 'string' ? envelope.request_id : undefined
  normalized.details = envelope?.details
  return normalized
}

export function createApiClient(baseURL = ''): AxiosInstance {
  const api = axios.create({ baseURL: baseURL ? `${baseURL.replace(/\/$/, '')}/api/v1` : '/api/v1', withCredentials: true })
  api.interceptors.request.use((config) => {
    config.headers.set('X-Request-ID', crypto.randomUUID())
    const token = getAccessToken()
    if (token) config.headers.set('Authorization', `Bearer ${token}`)
    return config
  })
  let refreshPromise: Promise<boolean> | undefined
  api.interceptors.response.use(undefined, async (error: AxiosError) => {
    const request = error.config as (AxiosError['config'] & { _authRetry?: boolean }) | undefined
    const isAuthRequest = request?.url?.includes('/auth/sessions') || request?.url?.includes('/auth/sms-codes')
    if (error.response?.status === 401 && request && !request._authRetry && !isAuthRequest && getAccessToken()) {
      request._authRetry = true
      refreshPromise ??= refreshAccessToken(api.defaults.baseURL).finally(() => { refreshPromise = undefined })
      if (await refreshPromise) return api.request(request)
      clearSession()
    }
    return Promise.reject(normalizeApiError(error))
  })
  return api
}

export async function refreshAccessToken(baseURL = '/api/v1') {
  try {
    const { data } = await axios.post<{ access_token: string; user: SessionUser }>(`${baseURL}/auth/sessions/refresh`, { audience: 'admin' }, { withCredentials: true })
    saveSession({ accessToken: data.access_token, audience: data.user.roles.some((role) => ['platform_admin', 'provider_admin', 'provider_staff'].includes(role)) ? 'admin' : 'consumer', user: data.user })
    return true
  } catch {
    return false
  }
}

export const api = createApiClient()

// Browser payment redirects are not proof of settlement; callers must query the order API.
export function queryPaymentConfirmation(orderId: string) {
  return api.post(`/travel-orders/${orderId}:query-payment`)
}
