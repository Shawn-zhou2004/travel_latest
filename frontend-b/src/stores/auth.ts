import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, refreshAccessToken } from '@/services/api'
import { audienceForUser, clearSession as clearStoredSession, getAccessToken, readSession, saveSession, type SessionAudience, type SessionUser } from '@/services/session'

export type TokenAudience = SessionAudience

export const useAuthStore = defineStore('admin-auth', () => {
  const stored = readSession()
  const accessToken = ref<string | undefined>(stored?.audience === 'admin' ? stored.accessToken : undefined)
  const audience = ref<TokenAudience | undefined>(stored?.audience === 'admin' ? stored.audience : undefined)
  const user = ref<SessionUser | undefined>(stored?.audience === 'admin' ? stored.user : undefined)
  const roles = computed(() => user.value?.roles ?? [])
  const initialized = ref(false)
  const busy = ref(false)
  let restorePromise: Promise<void> | undefined
  const isAdminSession = computed(() => Boolean(accessToken.value) && audience.value === 'admin' && roles.value.includes('platform_admin'))
  const isProviderSession = computed(() => Boolean(accessToken.value) && audience.value === 'admin' && roles.value.some((role) => role === 'provider_admin' || role === 'provider_staff'))

  function setSession(token: string, tokenAudience: TokenAudience, sessionRoles: string[], sessionUser?: SessionUser) {
    accessToken.value = token
    audience.value = tokenAudience
    user.value = sessionUser ?? { id: 'local-session', roles: sessionRoles }
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

  async function restoreSession() {
    if (restorePromise) return restorePromise
    restorePromise = (async () => {
      const current = readSession()
      if (current?.audience === 'admin') {
        accessToken.value = current.accessToken
        audience.value = current.audience
        user.value = current.user
        try {
          const response = await api.get<SessionUser>('/auth/me')
          accessToken.value = getAccessToken() ?? accessToken.value
          user.value = response.data
          if (accessToken.value) saveSession({ accessToken: accessToken.value, audience: 'admin', user: response.data })
        } catch {
          clearSession()
        }
      } else if (await refreshAccessToken()) {
        const refreshed = readSession()
        if (refreshed?.audience === 'admin') {
          accessToken.value = refreshed.accessToken
          audience.value = refreshed.audience
          user.value = refreshed.user
        }
      }
      initialized.value = true
    })().finally(() => { restorePromise = undefined })
    return restorePromise
  }

  async function login(username: string, password: string) {
    busy.value = true
    try {
      const { data } = await api.post<{ access_token: string; user: SessionUser }>('/auth/sessions/password', { username, password, device_name: 'admin-web', audience: 'admin' })
      if (audienceForUser(data.user) !== 'admin') throw new Error('This account does not have backoffice access.')
      setSession(data.access_token, 'admin', data.user.roles, data.user)
    } finally {
      busy.value = false
    }
  }

  async function logout() {
    try {
      if (isAdminSession.value || isProviderSession.value) await api.delete('/auth/sessions/current')
    } finally {
      clearSession()
      initialized.value = true
    }
  }

  return { accessToken, audience, user, roles, initialized, busy, isAdminSession, isProviderSession, setSession, clearSession, restoreSession, login, logout }
})
