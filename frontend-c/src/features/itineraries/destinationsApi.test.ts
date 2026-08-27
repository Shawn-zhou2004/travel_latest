import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createManualPlan, searchDestinations } from './destinationsApi'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), post: vi.fn() } }))

vi.mock('@/services/api', () => ({ api }))

const destination = {
  id: '430100',
  name: '长沙市',
  display_address: '中国 · 湖南省 · 长沙市',
  city_code: '430100',
  kind: 'city' as const,
}

describe('destination planning API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('searches backend-provided destination options', async () => {
    api.get.mockResolvedValue({ data: { items: [destination] } })

    await expect(searchDestinations('长沙')).resolves.toEqual([destination])

    expect(api.get).toHaveBeenCalledWith('/destinations', { params: { query: '长沙' } })
  })

  it('creates a manual itinerary without using the generation endpoint', async () => {
    const request = { destination, start_date: '2026-10-01', end_date: '2026-10-03', title: '长沙三日游' }
    const itinerary = { id: 'itinerary-1', owner_id: 'user-1', title: '长沙三日游', start_date: '2026-10-01', end_date: '2026-10-03', version: 1, status: 'draft', created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' }
    api.post.mockResolvedValue({ data: itinerary })

    await expect(createManualPlan(request)).resolves.toEqual(itinerary)

    expect(api.post).toHaveBeenCalledWith('/itineraries:manual-plan', request)
  })
})
