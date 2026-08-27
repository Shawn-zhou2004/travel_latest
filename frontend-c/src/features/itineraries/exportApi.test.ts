import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createDocxExport, getExportDownloadUrl, getExportTask, retryExportTask } from './exportApi'

const { api } = vi.hoisted(() => ({
  api: { post: vi.fn(), get: vi.fn() },
}))

vi.mock('@/services/api', () => ({ api }))

describe('DOCX export API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('submits the pinned itinerary version with the provided idempotency key', async () => {
    api.post.mockResolvedValue({ data: { id: 'export-1' } })

    await createDocxExport('itinerary-1', 4, 'export-request-1')

    expect(api.post).toHaveBeenCalledWith('/export-tasks', {
      itinerary_id: 'itinerary-1',
      version_no: 4,
      format: 'docx',
    }, { headers: { 'Idempotency-Key': 'export-request-1' } })
  })

  it('uses the task status, retry, and ephemeral download endpoints', async () => {
    api.get.mockResolvedValue({ data: { id: 'export-1', url: 'https://download.test/export.docx' } })
    api.post.mockResolvedValue({ data: { id: 'export-1' } })

    await getExportTask('export-1')
    await retryExportTask('export-1')
    await getExportDownloadUrl('export-1')

    expect(api.get).toHaveBeenCalledWith('/export-tasks/export-1')
    expect(api.post).toHaveBeenCalledWith('/export-tasks/export-1/retry')
    expect(api.get).toHaveBeenCalledWith('/export-tasks/export-1/download-url')
  })
})
