import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createTravelOrder, createTravelOrderRefund } from './api'

const { api } = vi.hoisted(() => ({
  api: { post: vi.fn() },
}))

vi.mock('@/services/api', () => ({ api }))

describe('travel order refund API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('uses the documented refund endpoint, body, and idempotency key', async () => {
    const request = { amount: '100.00', currency: 'CNY', reason: 'Plans changed' }
    api.post.mockResolvedValue({ data: { id: 'refund-1' } })

    await createTravelOrderRefund('order-1', request, 'refund-request-1')

    expect(api.post).toHaveBeenCalledWith('/travel-orders/order-1/refunds', request, {
      headers: { 'Idempotency-Key': 'refund-request-1' },
    })
  })
})

describe('travel order checkout API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('sends transient passenger details with the selected offer only', async () => {
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000003')
    const passengers = [{ name: 'Zhang San', document_type: 'passport' as const, document_number: 'E12345678', seat_preference: 'window' as const }]
    api.post.mockResolvedValue({ data: { id: 'order-1' } })

    await createTravelOrder('offer-1', passengers)

    expect(api.post).toHaveBeenCalledWith('/travel-orders', { offer_id: 'offer-1', passengers }, {
      headers: { 'Idempotency-Key': '00000000-0000-4000-8000-000000000003' },
    })
  })
})
