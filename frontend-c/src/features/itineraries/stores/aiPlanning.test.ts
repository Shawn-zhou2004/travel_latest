import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAiPlanningStore } from './aiPlanning'
import type { SmartPlanRequest } from '../aiPlanningApi'

const { applyPreview, createJob, getJob, getPreview, retryJob } = vi.hoisted(() => ({
  applyPreview: vi.fn(),
  createJob: vi.fn(),
  getJob: vi.fn(),
  getPreview: vi.fn(),
  retryJob: vi.fn(),
}))
const { getMyAIEntitlements } = vi.hoisted(() => ({ getMyAIEntitlements: vi.fn() }))

vi.mock('../aiPlanningApi', () => ({
  createGenerationJob: createJob,
  applyGenerationPreview: applyPreview,
  getGenerationJob: getJob,
  getGenerationPreview: getPreview,
  retryGenerationJob: retryJob,
}))
vi.mock('@/features/ai/assistantApi', () => ({ getMyAIEntitlements }))

const request: SmartPlanRequest = {
  destination: { id: '430100', name: '长沙市', display_address: '中国 · 湖南省 · 长沙市', city_code: '430100', kind: 'city' as const },
  start_date: '2026-10-01',
  end_date: '2026-10-03',
  preference_tags: ['citywalk'],
  prompt: '安排适合慢行的路线。',
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: 'job-1',
    status: 'queued',
    progress: 0,
    outcome: null,
    error_code: null,
    message: null,
    preview_id: null,
    target_itinerary_id: null,
    created_at: '2026-08-05T00:00:00Z',
    updated_at: '2026-08-05T00:00:00Z',
    ...overrides,
  }
}

describe('AI planning store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('polls a queued job and exposes the source-backed preview id without confirming it', async () => {
    createJob.mockResolvedValue(job())
    getJob.mockResolvedValue(job({
      status: 'awaiting_confirmation',
      progress: 100,
      outcome: 'preview',
      preview_id: 'preview-1',
      message: 'A source-backed itinerary preview is ready for confirmation.',
    }))

    getPreview.mockResolvedValue({ id: 'preview-1', generation_job_id: 'job-1', draft: { title: 'City break', days: [] }, citations: [], prompt_version: null, model_version: null, created_at: '2026-08-05T00:00:00Z' })
    const store = useAiPlanningStore()
    await store.submit(request)

    expect(getJob).toHaveBeenCalledWith('job-1')
    expect(store.state).toBe('ready')
    expect(store.job?.preview_id).toBe('preview-1')
    expect(store.preview?.id).toBe('preview-1')
    expect(store.message).toContain('source-backed')
  })

  it('confirms a loaded preview only through the protected preview endpoint', async () => {
    createJob.mockResolvedValue(job())
    getJob.mockResolvedValue(job({ status: 'awaiting_confirmation', progress: 100, outcome: 'preview', preview_id: 'preview-1', target_itinerary_id: 'itinerary-1' }))
    getPreview.mockResolvedValue({ id: 'preview-1', generation_job_id: 'job-1', draft: { title: 'City break', days: [] }, citations: [], prompt_version: null, model_version: null, created_at: '2026-08-05T00:00:00Z' })
    applyPreview.mockResolvedValue({ code: 'APPLIED', current_version: 2, snapshot: {}, idempotent: false })

    const store = useAiPlanningStore()
    await store.submit({ ...request, target_itinerary_id: 'itinerary-1', base_version: 1 })
    await store.applyPreview()

    expect(applyPreview).toHaveBeenCalledWith('job-1', 'preview-1', 1, expect.any(String))
    expect(store.appliedItineraryId).toBe('itinerary-1')
  })

  it('restores a pending preview by job id and confirms with its authoritative base_version', async () => {
    getJob.mockResolvedValue(job({ status: 'awaiting_confirmation', progress: 100, outcome: 'preview', preview_id: 'preview-1', target_itinerary_id: 'itinerary-1' }))
    getPreview.mockResolvedValue({ id: 'preview-1', generation_job_id: 'job-1', draft: { title: 'City break', days: [] }, citations: [], prompt_version: null, model_version: null, created_at: '2026-08-05T00:00:00Z', base_version: 3 })
    applyPreview.mockResolvedValue({ code: 'APPLIED', current_version: 4, snapshot: {}, idempotent: false })

    const store = useAiPlanningStore()
    expect(await store.restore('job-1')).toBe(true)
    expect(store.state).toBe('ready')
    expect(store.preview?.id).toBe('preview-1')

    await store.applyPreview()
    expect(applyPreview).toHaveBeenCalledWith('job-1', 'preview-1', 3, expect.any(String))
    expect(store.appliedItineraryId).toBe('itinerary-1')
  })

  it('surfaces an unavailable restore so the caller can fall back to the planning form', async () => {
    getJob.mockRejectedValue(new Error('not allowed'))

    const store = useAiPlanningStore()
    expect(await store.restore('job-1')).toBe(false)
    expect(store.state).toBe('unavailable')
  })

  it('keeps no-result and clarification as explicit terminal states', async () => {
    createJob.mockResolvedValue(job())
    getJob.mockResolvedValueOnce(job({
      status: 'succeeded',
      progress: 100,
      outcome: 'no_result',
      message: '没有足够可靠的来源。',
    }))

    const store = useAiPlanningStore()
    await store.submit(request)
    expect(store.state).toBe('no_result')
    expect(store.message).toBe('未找到足够可验证的地点。请调整偏好后重试，或选择手动规划。')

    store.reset()
    createJob.mockResolvedValue(job())
    getJob.mockResolvedValueOnce(job({
      status: 'succeeded',
      progress: 100,
      outcome: 'clarification',
      message: '请补充预算。',
    }))

    await store.submit(request)
    expect(store.state).toBe('clarification')
    expect(store.message).toBe('请补充预算。')
  })

  it('uses the retry endpoint for a failed generation job', async () => {
    createJob.mockResolvedValue(job())
    getJob.mockResolvedValueOnce(job({
      status: 'failed',
      progress: 100,
      outcome: 'unavailable',
      message: '依赖服务暂不可用。',
    }))
    retryJob.mockResolvedValue(job())
    getJob.mockResolvedValueOnce(job({
      status: 'succeeded',
      progress: 100,
      outcome: 'no_result',
      message: '重试后没有结果。',
    }))

    const store = useAiPlanningStore()
    await store.submit(request)
    await store.retry()

    expect(retryJob).toHaveBeenCalledWith('job-1')
    expect(store.state).toBe('no_result')
  })

  it('preserves omitted and explicit optional preferences in retry requests', async () => {
    createJob.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(job())
    getJob.mockResolvedValueOnce(job({ status: 'succeeded', progress: 100, outcome: 'no_result' }))
    const store = useAiPlanningStore()
    const retryRequest: SmartPlanRequest = {
      ...request,
      preference_tags: undefined,
      pace: null,
      traveler_type: null,
    }

    await store.submit(retryRequest)
    await store.retry()

    expect(createJob).toHaveBeenLastCalledWith(expect.objectContaining({
      preference_tags: undefined,
      pace: null,
      traveler_type: null,
    }), expect.any(String))
  })

  it('explains an invalid model draft without presenting it as missing travel knowledge', async () => {
    createJob.mockResolvedValue(job())
    getJob.mockResolvedValueOnce(job({
      status: 'failed',
      progress: 100,
      outcome: 'unavailable',
      error_code: 'INVALID_DRAFT_SCHEMA',
      message: 'Each activity requires poi_id and title',
    }))

    const store = useAiPlanningStore()
    await store.submit(request)

    expect(store.state).toBe('unavailable')
    expect(store.message).toBe('AI 返回的行程格式不完整，未生成可确认的计划。请重试。')
  })

  it('explains why an empty itinerary cannot be modified', async () => {
    const error = new Error('The target itinerary must contain at least one activity.') as Error & { code: string }
    error.code = 'TARGET_ITINERARY_EMPTY'
    createJob.mockRejectedValue(error)

    const store = useAiPlanningStore()
    await store.submit(request)

    expect(store.state).toBe('unavailable')
    expect(store.message).toBe('请先在目标行程中加入至少一个地点，再生成修改预览。')
  })

  it('marks an exhausted AI quota without scheduling a retry', async () => {
    const error = new Error('quota exhausted') as Error & { code: string }
    error.code = 'AI_QUOTA_EXHAUSTED'
    createJob.mockRejectedValue(error)
    const store = useAiPlanningStore()
    await store.submit(request)
    expect(store.quotaExhausted).toBe(true)
    expect(store.message).toContain('额度已用完')
    await store.retry()
    expect(createJob).toHaveBeenCalledTimes(1)
  })
})
