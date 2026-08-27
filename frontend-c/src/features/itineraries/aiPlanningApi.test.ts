import { beforeEach, describe, expect, it, vi } from 'vitest'
import { applyGenerationPreview, createGenerationJob, getGenerationJob, getGenerationPreview, retryGenerationJob, type SmartPlanRequest } from './aiPlanningApi'

const { api } = vi.hoisted(() => ({
  api: { post: vi.fn(), get: vi.fn() },
}))

vi.mock('@/services/api', () => ({ api }))

const request: SmartPlanRequest = {
  destination: { id: '430100', name: '长沙市', display_address: '中国 · 湖南省 · 长沙市', city_code: '430100', kind: 'city' as const },
  start_date: '2026-10-01',
  end_date: '2026-10-03',
  preference_tags: ['吃吃喝喝', 'citywalk'],
  prompt: '安排一段适合步行的湖岸和老城路线。',
}

describe('AI planning API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('posts the selected destination and preference tags with the idempotency key', async () => {
    api.post.mockResolvedValue({ data: { id: 'job-1' } })

    await createGenerationJob(request, 'request-key-1')

    expect(api.post).toHaveBeenCalledWith('/generation-jobs', request, {
      headers: { 'Idempotency-Key': 'request-key-1' },
    })
  })

  it('uses the generation job preview, retry, and confirmation endpoints', async () => {
    api.get.mockResolvedValue({ data: { id: 'job-1' } })
    api.post.mockResolvedValue({ data: { id: 'job-1' } })

    await getGenerationJob('job-1')
    await retryGenerationJob('job-1')
    await getGenerationPreview('job-1')
    await applyGenerationPreview('job-1', 'preview-1', 1, 'operation-1')

    expect(api.get).toHaveBeenCalledWith('/generation-jobs/job-1')
    expect(api.post).toHaveBeenCalledWith('/generation-jobs/job-1/retry')
    expect(api.get).toHaveBeenCalledWith('/generation-jobs/job-1/preview')
    expect(api.post).toHaveBeenCalledWith('/generation-jobs/job-1/preview/preview-1:apply', {}, {
      headers: { 'If-Match-Version': 1, 'X-Operation-ID': 'operation-1' },
    })
  })
})
