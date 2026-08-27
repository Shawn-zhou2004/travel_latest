import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMembershipPurchase, createMembershipQrPayment, getCurrentMembershipQrPayment, listMyEffectiveEntitlements, listPublishedMembershipPlans, queryMembershipPurchasePayment, refreshMembershipQrPayment } from './api'

  const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), post: vi.fn() } }))

vi.mock('@/services/api', () => ({ api }))

describe('membership API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads only published plans from the public endpoint', async () => {
    api.get.mockResolvedValue({ data: [] })

    await listPublishedMembershipPlans()

    expect(api.get).toHaveBeenCalledWith('/membership-plans')
  })

  it('loads the signed-in user effective entitlements', async () => {
    api.get.mockResolvedValue({ data: [] })

    await listMyEffectiveEntitlements()

    expect(api.get).toHaveBeenCalledWith('/users/me/entitlements')
  })

  it('uses server pricing and idempotency headers for a membership purchase', async () => {
    api.post.mockResolvedValue({ data: { id: 'purchase-1' } })
    await createMembershipPurchase('plan-1', 'purchase-key')
    expect(api.post).toHaveBeenNthCalledWith(1, '/membership-purchases', { membership_plan_id: 'plan-1' }, { headers: { 'Idempotency-Key': 'purchase-key' } })
    expect(api.post.mock.calls[0][1]).not.toHaveProperty('amount')
  })

  it('uses only the purchase ID for QR payment lifecycle calls', async () => {
    api.get.mockResolvedValue({ data: {} })
    api.post.mockResolvedValue({ data: {} })
    await createMembershipQrPayment('purchase-1')
    await getCurrentMembershipQrPayment('purchase-1')
    await refreshMembershipQrPayment('purchase-1')
    await queryMembershipPurchasePayment('purchase-1')
    expect(api.post).toHaveBeenNthCalledWith(1, '/membership-purchases/purchase-1/qr-payments')
    expect(api.get).toHaveBeenCalledWith('/membership-purchases/purchase-1/qr-payments/current')
    expect(api.post).toHaveBeenNthCalledWith(2, '/membership-purchases/purchase-1/qr-payments:refresh')
    expect(api.post).toHaveBeenNthCalledWith(3, '/membership-purchases/purchase-1:query-payment')
  })
})
