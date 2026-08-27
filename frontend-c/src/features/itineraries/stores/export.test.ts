import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useItineraryExportStore } from './export'

const { createExport, getTask, getDownloadUrl, retryTask } = vi.hoisted(() => ({
  createExport: vi.fn(),
  getTask: vi.fn(),
  getDownloadUrl: vi.fn(),
  retryTask: vi.fn(),
}))

vi.mock('../exportApi', () => ({
  createDocxExport: createExport,
  getExportTask: getTask,
  getExportDownloadUrl: getDownloadUrl,
  retryExportTask: retryTask,
}))

function task(overrides: Record<string, unknown> = {}) {
  return {
    id: 'export-1', itinerary_id: 'itinerary-1', version_no: 4, format: 'docx', status: 'queued', progress: 0,
    output_available: false, attempt_count: 1, last_error_code: null, last_error_message: null, finished_at: null,
    ...overrides,
  }
}

describe('itinerary DOCX export store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('creates one idempotent export request, polls it, and exposes its success state', async () => {
    createExport.mockResolvedValue(task())
    getTask.mockResolvedValue(task({ status: 'succeeded', progress: 100, output_available: true }))
    const store = useItineraryExportStore()

    await store.create('itinerary-1', 4)

    expect(createExport).toHaveBeenCalledWith('itinerary-1', 4, expect.any(String))
    expect(getTask).toHaveBeenCalledWith('export-1')
    expect(store.state).toBe('succeeded')
  })

  it('only retries failed tasks and only requests a download URL after success', async () => {
    createExport.mockResolvedValue(task({ status: 'failed', progress: 100, last_error_message: 'Storage unavailable.' }))
    retryTask.mockResolvedValue(task({ status: 'succeeded', progress: 100, output_available: true }))
    getDownloadUrl.mockResolvedValue('https://download.test/export.docx')
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const store = useItineraryExportStore()

    await store.create('itinerary-1', 4)
    expect(store.canRetry).toBe(true)
    await store.retry()
    await store.download()

    expect(retryTask).toHaveBeenCalledWith('export-1')
    expect(getDownloadUrl).toHaveBeenCalledWith('export-1')
    expect(click).toHaveBeenCalledOnce()
  })

  it('reuses the idempotency key after a create response is unavailable', async () => {
    createExport.mockRejectedValueOnce(new Error('Network unavailable.')).mockResolvedValueOnce(task({ status: 'failed', progress: 100 }))
    const store = useItineraryExportStore()

    await store.create('itinerary-1', 4)
    await store.create('itinerary-1', 4)

    const firstKey = createExport.mock.calls[0][2]
    expect(createExport.mock.calls[1][2]).toBe(firstKey)
  })
})
