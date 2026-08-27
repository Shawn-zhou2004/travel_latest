import { describe, expect, it, vi } from 'vitest'

const { get, patch, post } = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api', () => ({ api: { get, patch, post } }))

import { archiveMembershipPlan, createMembershipPlan, listMembershipPlans, publishMembershipPlan, updateMembershipPlan } from './membershipPlans'

describe('membership plan API', () => {
  it('loads plans from the platform-admin collection with the selected lifecycle filter', async () => {
    get.mockResolvedValueOnce({ data: { items: [], next_cursor: null } })

    await expect(listMembershipPlans('draft')).resolves.toEqual([])

    expect(get).toHaveBeenCalledWith('/admin/membership-plans', { params: { status: 'draft' } })
  })

  it('creates and transitions plans through their supported lifecycle endpoints', async () => {
    const body = { code: 'trip-plus', name: 'Trip Plus', duration_days: 30, entitlement_codes: ['itinerary_export'], price_amount: 19.9, currency: 'CNY' as const, generation_quota: 10, assistant_quota: 300, purchasable: false as const }
    post.mockResolvedValue({ data: { id: 'plan-id' } })

    await createMembershipPlan(body)
    await publishMembershipPlan('plan-id')
    await archiveMembershipPlan('plan-id')

    expect(post).toHaveBeenNthCalledWith(1, '/admin/membership-plans', body)
    expect(post).toHaveBeenNthCalledWith(2, '/admin/membership-plans/plan-id:publish')
    expect(post).toHaveBeenNthCalledWith(3, '/admin/membership-plans/plan-id:archive')
  })

  it('updates server-controlled pricing, quotas, and purchasable state', async () => {
    patch.mockResolvedValueOnce({ data: { id: 'plan-id' } })

    await updateMembershipPlan('plan-id', { price_amount: 19.9, currency: 'CNY', generation_quota: 10, assistant_quota: 300, purchasable: true })

    expect(patch).toHaveBeenCalledWith('/admin/membership-plans/plan-id', { price_amount: 19.9, currency: 'CNY', generation_quota: 10, assistant_quota: 300, purchasable: true })
  })
})
