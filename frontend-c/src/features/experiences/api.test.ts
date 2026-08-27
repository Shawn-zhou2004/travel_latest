import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getExperience, listExperiences } from './api'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn() } }))

vi.mock('@/services/api', () => ({ api }))

describe('experience API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads the public catalog with optional public filters', async () => {
    api.get.mockResolvedValue({ data: { items: [] } })

    await listExperiences({ city_code: 'HZ', provider_id: 'provider-1' })

    expect(api.get).toHaveBeenCalledWith('/experiences', { params: { city_code: 'HZ', provider_id: 'provider-1' } })
  })

  it('loads one public experience without creating a reservation', async () => {
    api.get.mockResolvedValue({ data: {} })

    await getExperience('experience-1')

    expect(api.get).toHaveBeenCalledWith('/experiences/experience-1')
  })
})
