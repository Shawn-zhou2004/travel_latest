import { describe, expect, it, vi } from 'vitest'

const { get, patch, post } = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api', () => ({ api: { get, patch, post } }))

import { createWebSearchJob, decideExternalWebKnowledgeSource, decideWebSearchCandidate, getAiWorkflowHealth, listExternalWebKnowledgeSources, listWebSearchCandidates, listWebSearchJobs } from './aiOperations'

describe('getAiWorkflowHealth', () => {
  it('requests the aggregate-only platform-admin health endpoint', async () => {
    const health = { generation_jobs: { queued: 0, running: 0, failed: 0, most_recent_at: null }, export_tasks: { queued: 0, running: 0, failed: 0, most_recent_at: null }, outbox: { unprocessed: 0, retrying: 0, dead_letter: 0, most_recent_at: null }, worker: { status: 'healthy' as const, last_heartbeat_at: null } }
    get.mockResolvedValueOnce({ data: health })

    await expect(getAiWorkflowHealth()).resolves.toEqual(health)

    expect(get).toHaveBeenCalledWith('/admin/ai/workflow-health')
  })
})

describe('WebSearch admin client', () => {
  it('submits a typed search job without exposing provider configuration', async () => {
    const job = { id: 'job-1', status: 'queued' }
    post.mockResolvedValueOnce({ data: job })

    await expect(createWebSearchJob({ city_code: '330100', query: 'West Lake official notice', target_domain: 'official' })).resolves.toEqual(job)

    expect(post).toHaveBeenCalledWith('/admin/ai/websearch-jobs', { city_code: '330100', query: 'West Lake official notice', target_domain: 'official' })
  })

  it('lists a job’s candidates and sends explicit approval or rejection decisions', async () => {
    get.mockClear()
    patch.mockClear()
    get.mockResolvedValueOnce({ data: { items: [{ id: 'job-1' }], next_cursor: null } })
    get.mockResolvedValueOnce({ data: { items: [{ id: 'candidate-1' }], next_cursor: null } })
    patch.mockResolvedValueOnce({ data: { id: 'candidate-1', status: 'approved' } })

    await expect(listWebSearchJobs('queued')).resolves.toEqual([{ id: 'job-1' }])
    await expect(listWebSearchCandidates('job-1', 'needs_human_review')).resolves.toEqual([{ id: 'candidate-1' }])
    await expect(decideWebSearchCandidate('candidate-1', { status: 'approved', title: 'Reviewed title', body_text: 'Reviewed body' })).resolves.toMatchObject({ status: 'approved' })

    expect(get).toHaveBeenNthCalledWith(1, '/admin/ai/websearch-jobs', { params: { status: 'queued', limit: 50 } })
    expect(get).toHaveBeenNthCalledWith(2, '/admin/ai/websearch-jobs/job-1/candidates', { params: { status: 'needs_human_review', limit: 50 } })
    expect(patch).toHaveBeenCalledWith('/admin/ai/websearch-candidates/candidate-1', { status: 'approved', title: 'Reviewed title', body_text: 'Reviewed body' })
  })
})

describe('External web knowledge source admin client', () => {
  it('lists pending second-review sources and sends the indexing approval', async () => {
    get.mockClear()
    patch.mockClear()
    get.mockResolvedValueOnce({ data: { items: [{ id: 'source-1', status: 'pending_review' }], next_cursor: null } })
    patch.mockResolvedValueOnce({ data: { id: 'source-1', status: 'indexing' } })

    await expect(listExternalWebKnowledgeSources('pending_review')).resolves.toEqual([{ id: 'source-1', status: 'pending_review' }])
    await expect(decideExternalWebKnowledgeSource('source-1', { status: 'approved' })).resolves.toMatchObject({ status: 'indexing' })

    expect(get).toHaveBeenCalledWith('/admin/ai/external-web-knowledge-sources', { params: { status: 'pending_review', limit: 50 } })
    expect(patch).toHaveBeenCalledWith('/admin/ai/external-web-knowledge-sources/source-1', { status: 'approved' })
  })

  it('sends a required rejection reason without source content', async () => {
    patch.mockClear()
    patch.mockResolvedValueOnce({ data: { id: 'source-1', status: 'rejected' } })

    await expect(decideExternalWebKnowledgeSource('source-1', { status: 'rejected', reason: 'Source attribution is insufficient.' })).resolves.toMatchObject({ status: 'rejected' })

    expect(patch).toHaveBeenCalledWith('/admin/ai/external-web-knowledge-sources/source-1', { status: 'rejected', reason: 'Source attribution is insufficient.' })
  })
})
