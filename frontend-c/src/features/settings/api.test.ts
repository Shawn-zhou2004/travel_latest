import { describe, expect, it, vi } from 'vitest'
import { getMySettings, updateMySettings } from './api'
import { routes } from '@/router'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), patch: vi.fn() } }))
vi.mock('@/services/api', () => ({ api }))

describe('settings API', () => {
  it('gets the normalized personal settings object', async () => {
    const settings = { departure_city: null, budget_level: 'balanced' }
    api.get.mockResolvedValue({ data: settings })

    await expect(getMySettings()).resolves.toEqual(settings)
    expect(api.get).toHaveBeenCalledWith('/users/me/settings')
  })

  it('sends a partial settings patch', async () => {
    const settings = { departure_city: null, budget_level: 'balanced' }
    api.patch.mockResolvedValue({ data: settings })

    await updateMySettings({ travel_pace: 'relaxed', interest_tags: ['吃吃喝喝'] })

    expect(api.patch).toHaveBeenCalledWith('/users/me/settings', {
      travel_pace: 'relaxed', interest_tags: ['吃吃喝喝'],
    })
  })

  it('registers the consumer-only settings route and profile compatibility redirect', () => {
    expect(routes.find((route) => route.path === '/me/settings')?.meta).toMatchObject({ requiresConsumer: true })
    expect(routes.find((route) => route.path === '/me/profile')?.redirect).toEqual({ path: '/me/settings', hash: '#profile' })
  })
})
