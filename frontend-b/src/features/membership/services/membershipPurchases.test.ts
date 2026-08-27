import { describe, expect, it, vi } from 'vitest'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api', () => ({ api: { get, post } }))

import { listMembershipPurchases, retryMembershipPurchaseAuthorization } from './membershipPurchases'

describe('membership purchase audit API', () => {
  it('uses only the status filter when loading the redacted audit list', async () => {
    get.mockResolvedValueOnce({ data: { items: [] } })

    await expect(listMembershipPurchases('paid')).resolves.toEqual([])

    expect(get).toHaveBeenCalledWith('/admin/membership-purchases', { params: { status: 'paid' } })
  })

  it('calls the explicit authorization retry endpoint without payment data', async () => {
    post.mockResolvedValueOnce({ data: { id: 'purchase-id' } })

    await retryMembershipPurchaseAuthorization('purchase-id')

    expect(post).toHaveBeenCalledWith('/admin/membership-purchases/purchase-id:retry-authorization')
  })
})
