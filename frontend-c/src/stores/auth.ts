import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, refreshAccessToken } from '@/services/api'
import { audienceForUser, clearSession as clearStoredSession, getAccessToken, readSession, saveSession, type SessionAudience, type SessionUser } from '@/services/session'

export type TokenAudience = SessionAudience

export const useAuthStore = defineStore('consumer-auth', () => {
  const stored = readSession()
  const accessToken = ref<string | undefined>(stored?.audience === 'consumer' ? stored.accessToken : undefined)
  const audience = ref<TokenAudience | undefined>(stored?.audience === 'consumer' ? stored.audience : undefined)
  const user = ref<SessionUser | undefined>(stored?.audience === 'consumer' ? stored.user : undefined)
  const initialized = ref(false)
  const busy = ref(false)
  let restorePromise: Promise<void> | undefined
  const isConsumerSession = computed(() => Boolean(accessToken.value) && audience.value === 'consumer')

  function setSession(token: string, tokenAudience: TokenAudience, sessionUser?: SessionUser) {
    accessToken.value = token
    audience.value = tokenAudience
    user.value = sessionUser ?? { id: 'local-session', roles: tokenAudience === 'admin' ? ['platform_admin'] : ['user'] }
    initialized.value = true
    saveSession({ accessToken: token, audience: tokenAudience, user: user.value })
  }

  function clearSession() {
    accessToken.value = undefined
    audience.value = undefined
    user.value = undefined
    initialized.value = true
    clearStoredSession()
  }

  function updateUserProfile(profile: Pick<SessionUser, 'nickname' | 'avatar_asset_id'>) {
    if (!user.value || !accessToken.value || audience.value !== 'consumer') return
    user.value = { ...user.value, ...profile }
    saveSession({ accessToken: accessToken.value, audience: 'consumer', user: user.value })
  }

  async function restoreSession() {
    if (restorePromise) return restorePromise
    restorePromise = (async () => {
      const current = readSession()
      if (current?.audience === 'consumer') {
        accessToken.value = current.accessToken
        audience.value = current.audience
        user.value = current.user
        try {
          const response = await api.get<SessionUser>('/auth/me')
          accessToken.value = getAccessToken() ?? accessToken.value
          user.value = response.data
          if (accessToken.value) saveSession({ accessToken: accessToken.value, audience: 'consumer', user: response.data })
        } catch {
          clearSession()
        }
      } else if (await refreshAccessToken()) {
        const refreshed = readSession()
        if (refreshed?.audience === 'consumer') {
          accessToken.value = refreshed.accessToken
          audience.value = refreshed.audience
          user.value = refreshed.user
        }
      }
      initialized.value = true
    })().finally(() => { restorePromise = undefined })
    return restorePromise
  }

  async function sendCode(phone: string) {
    const { data } = await api.post<{ request_id: string; expires_in: number; debug_code?: string }>('/auth/sms-codes', { phone })
    return data
  }

  async function login(phone: string, code: string) {
    busy.value = true
    try {
      const { data } = await api.post<{ access_token: string; user: SessionUser }>('/auth/sessions', { phone, code, device_name: 'consumer-web' })
      if (audienceForUser(data.user) !== 'consumer') throw new Error('This account belongs to the administration console.')
      setSession(data.access_token, 'consumer', data.user)
    } finally {
      busy.value = false
    }
  }

  async function loginWithPassword(phone: string, password: string) {
    busy.value = true
    try {
      const { data } = await api.post<{ access_token: string; user: SessionUser }>('/auth/sessions/password', { phone, password, device_name: 'consumer-web' })
      if (audienceForUser(data.user) !== 'consumer') throw new Error('This account belongs to the administration console.')
      setSession(data.access_token, 'consumer', data.user)
    } finally {
      busy.value = false
    }
  }

  async function register(phone: string, code: string, nickname: string, password: string) {
    busy.value = true
    try {
      const { data } = await api.post<{ access_token: string; user: SessionUser }>('/auth/register', { phone, code, nickname, password, device_name: 'consumer-web' })
      setSession(data.access_token, 'consumer', data.user)
    } finally {
      busy.value = false
    }
  }

  async function logout() {
    try {
      if (isConsumerSession.value) await api.delete('/auth/sessions/current')
    } finally {
      clearSession()
      initialized.value = true
    }
  }

  return { accessToken, audience, user, initialized, busy, isConsumerSession, setSession, clearSession, updateUserProfile, restoreSession, sendCode, login, loginWithPassword, register, logout }
})
