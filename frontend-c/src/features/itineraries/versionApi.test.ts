import { beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteItinerary, getItineraryVersion, listItineraryVersions, removeItineraryDay } from './api'

const { api } = vi.hoisted(() => ({ api: { delete: vi.fn(), get: vi.fn(), post: vi.fn() } }))

vi.mock('@/services/api', () => ({ api }))

describe('itinerary version API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('uses private itinerary version endpoints', async () => {
    api.get.mockResolvedValueOnce({ data: [{ id: 'version-2', version_no: 2, source: 'add_day', created_at: '2026-10-01T00:00:00Z' }] })
      .mockResolvedValueOnce({ data: { id: 'version-2', version_no: 2, source: 'add_day', created_at: '2026-10-01T00:00:00Z', snapshot: { title: 'Trip', start_date: '2026-10-01', end_date: '2026-10-01', days: [] } } })

    await listItineraryVersions('itinerary-1')
    await getItineraryVersion('itinerary-1', 2)

    expect(api.get).toHaveBeenNthCalledWith(1, '/itineraries/itinerary-1/versions')
    expect(api.get).toHaveBeenNthCalledWith(2, '/itineraries/itinerary-1/versions/2')
  })

  it('deletes a whole itinerary without a request body', async () => {
    api.delete.mockResolvedValueOnce({})

    await deleteItinerary('trip-1')

    expect(api.delete).toHaveBeenCalledWith('/itineraries/trip-1')
  })

  it('removes a day through optimistic operation headers', async () => {
    api.post.mockResolvedValueOnce({ data: { code: 'APPLIED', current_version: 4, snapshot: null, idempotent: false } })

    await removeItineraryDay('trip-1', 3, 'operation-1', 'day-2')

    expect(api.post).toHaveBeenCalledWith('/itineraries/trip-1:operations', {
      operation_type: 'remove_day', payload: { day_id: 'day-2' },
    }, { headers: { 'If-Match-Version': 3, 'X-Operation-ID': 'operation-1' } })
  })
})
