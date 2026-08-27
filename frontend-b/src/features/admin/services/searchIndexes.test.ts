import { describe, expect, it, vi } from 'vitest'

const get = vi.hoisted(() => vi.fn())
const post = vi.hoisted(() => vi.fn())
vi.mock('@/services/api', () => ({ api: { get, post } }))
import { getSearchIndexRebuildJob, listSearchIndexes, rebuildSearchIndex } from './searchIndexes'

describe('search index service', () => {
  it('requests the fixed inventory endpoint and returns items', async () => {
    const items = [{ logical_name: 'official_knowledge', index_name: 'official-v1', status: 'healthy', document_count: 2, message: null }]
    get.mockResolvedValue({ data: { items } })
    await expect(listSearchIndexes()).resolves.toEqual(items)
    expect(get).toHaveBeenCalledWith('/admin/search-indexes')
  })

  it('requests a rebuild job for the selected index', async () => {
    const job = { id: 'job-1', index_name: 'official_knowledge', status: 'queued' }
    post.mockResolvedValue({ data: job })
    await expect(rebuildSearchIndex('official_knowledge')).resolves.toEqual(job)
    expect(post).toHaveBeenCalledWith('/admin/search-indexes:rebuild', { index_name: 'official_knowledge' })
  })

  it('requests a rebuild job by id', async () => {
    const job = { id: 'job-1', index_name: 'official_knowledge', status: 'running' }
    get.mockResolvedValue({ data: job })
    await expect(getSearchIndexRebuildJob('job-1')).resolves.toEqual(job)
    expect(get).toHaveBeenCalledWith('/admin/search-index-rebuild-jobs/job-1')
  })
})
