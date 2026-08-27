import { describe, expect, it, vi } from 'vitest'
import { api } from '@/services/api'
import { listProviderBookings, listProviderExperiences, verifyProviderBooking } from './experiences'

describe('provider experiences API', () => {
  it('passes only the explicitly selected provider scope to the workspace list request', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [] } })
    await expect(listProviderExperiences('provider-a')).resolves.toEqual([])
    expect(get).toHaveBeenCalledWith('/provider/experiences', { params: { provider_id: 'provider-a' } })
    get.mockRestore()
  })

  it('loads scoped bookings and submits a manually entered verification code', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [] } })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'booking-1', status: 'verified', verified_at: '2026-08-09T00:00:00Z' } })

    await expect(listProviderBookings('provider-a')).resolves.toEqual([])
    await verifyProviderBooking('provider-a', 'booking-1', 'traveler-code')

    expect(get).toHaveBeenCalledWith('/provider/experience-bookings', { params: { provider_id: 'provider-a', status: 'reserved' } })
    expect(post).toHaveBeenCalledWith('/provider/experience-bookings/booking-1:verify', { verification_code: 'traveler-code' }, { params: { provider_id: 'provider-a' } })
    get.mockRestore()
    post.mockRestore()
  })
})
