import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAdminRouter } from './index'
import { useAuthStore } from '@/stores/auth'

describe('admin route guard', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('redirects an unauthorized visitor to the login route', async () => {
    const router = createAdminRouter(createMemoryHistory())
    await router.push('/orders')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query.redirect).toBe('/orders')
  })

  it('allows a platform admin with a B-end audience token', async () => {
    useAuthStore().setSession('token', 'admin', ['platform_admin'])
    const router = createAdminRouter(createMemoryHistory())
    await router.push('/orders')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/orders')
  }, 10_000)

  it('allows a provider backoffice session into the scoped provider workspace', async () => {
    useAuthStore().setSession('token', 'admin', ['provider_staff'], { id: 'provider-user', roles: ['provider_staff'], provider_memberships: ['provider-a'] })
    const router = createAdminRouter(createMemoryHistory())
    await router.push('/provider/experiences')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/provider/experiences')
  })

  it('redirects platform administrators away from the provider workspace', async () => {
    useAuthStore().setSession('token', 'admin', ['platform_admin'])
    const router = createAdminRouter(createMemoryHistory())
    await router.push('/provider/experiences')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/content/posts')
  })

  it('returns a provider session from the root route to its workspace', async () => {
    useAuthStore().setSession('token', 'admin', ['provider_admin'], { id: 'provider-user', roles: ['provider_admin'], provider_memberships: ['provider-a'] })
    const router = createAdminRouter(createMemoryHistory())
    await router.push('/')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/provider/experiences')
  })

  it('registers export task monitoring as an admin route', async () => {
    useAuthStore().setSession('token', 'admin', ['platform_admin'])
    const router = createAdminRouter(createMemoryHistory())
    await router.push('/tasks')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/tasks')
    expect(router.currentRoute.value.matched[0]?.components?.default).toBeTruthy()
  })

  it('registers membership plan administration as an admin route', async () => {
    useAuthStore().setSession('token', 'admin', ['platform_admin'])
    const router = createAdminRouter(createMemoryHistory())
    await router.push('/memberships/plans')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/memberships/plans')
    expect(router.currentRoute.value.matched[0]?.components?.default).toBeTruthy()
  })
})
