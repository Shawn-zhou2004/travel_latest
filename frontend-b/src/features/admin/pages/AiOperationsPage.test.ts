import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const aiOperations = vi.hoisted(() => ({
  createKnowledgeSource: vi.fn(), createPoiImportJob: vi.fn(), createStructuredKnowledgeImportJob: vi.fn(), createWebSearchJob: vi.fn(),
  decideCommunityKnowledgeReview: vi.fn(), decideExternalWebKnowledgeSource: vi.fn(), decideKnowledgeSource: vi.fn(), decideWebSearchCandidate: vi.fn(), getAiMetrics: vi.fn(),
  getAiWorkflowHealth: vi.fn(), listCommunityKnowledgeReviews: vi.fn(), listExternalWebKnowledgeSources: vi.fn(), listGenerationAudit: vi.fn(), listKnowledgeSources: vi.fn(),
  listPoiImportJobs: vi.fn(), listStructuredKnowledgeImportJobs: vi.fn(), listWebSearchCandidates: vi.fn(), listWebSearchJobs: vi.fn(),
  previewRetrieval: vi.fn(), retryPoiImportJob: vi.fn(), retryStructuredKnowledgeImportJob: vi.fn(),
}))

vi.mock('../services/aiOperations', () => aiOperations)
vi.mock('@/services/api', () => ({ normalizeApiError: (cause: unknown) => ({ message: String(cause) }) }))
vi.mock('element-plus', () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }))

import AiOperationsPage from './AiOperationsPage.vue'

const source = {
  id: 'external-1', candidate_id: 'candidate-9', target_domain: 'official' as const, title: 'West Lake visitor guidance',
  body_text: 'Visitors must reserve peak-season tickets before arrival.', city_code: '330100', source_url: 'https://travel.example.gov/west-lake',
  source_host: 'travel.example.gov', published_at: '2026-08-01T08:00:00Z', fetched_at: '2026-08-02T08:00:00Z', status: 'pending_review' as const,
  review_reason: null, reviewed_by: null, reviewed_at: null, indexed_at: null, index_error: null, removal_error: null,
  created_at: '2026-08-02T08:00:00Z', updated_at: '2026-08-02T08:00:00Z',
}

const communityReview = {
  id: 'review-1', post_id: 'post-8', status: 'pending' as const, reason: null, reviewed_by: null, reviewed_at: null,
  created_at: '2026-08-03T08:00:00Z', updated_at: '2026-08-03T08:00:00Z', post_title: 'West Lake morning route',
  post_body_text: 'Take the first bus and reserve tickets before arriving.', post_city_code: '330100', post_status: 'published',
}

function mountPage() {
  return mount(AiOperationsPage, {
    global: {
      stubs: {
        'el-table': { template: '<div><slot /></div>' }, 'el-table-column': { template: '<div><slot :row="{}" /></div>' },
        'el-select': { template: '<div><slot /></div>' }, 'el-option': true, 'el-tag': { template: '<span><slot /></span>' },
        'el-dialog': { props: ['modelValue'], template: '<div v-if="modelValue"><slot /></div>' },
        'el-input': { props: ['modelValue'], emits: ['update:modelValue'], template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
      },
      directives: { loading: {} },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  aiOperations.listKnowledgeSources.mockResolvedValue([])
  aiOperations.listPoiImportJobs.mockResolvedValue([])
  aiOperations.listStructuredKnowledgeImportJobs.mockResolvedValue([])
  aiOperations.listGenerationAudit.mockResolvedValue([])
  aiOperations.getAiMetrics.mockResolvedValue({ knowledge: { pending_review: 0, indexed: 0, failed: 0, indexing: 0 }, generation: { total: 0, failed: 0, awaiting_confirmation: 0 }, imports: { poi_failed: 0, structured_failed: 0 } })
  aiOperations.getAiWorkflowHealth.mockResolvedValue({ generation_jobs: { queued: 0, running: 0, failed: 0, most_recent_at: null }, export_tasks: { queued: 0, running: 0, failed: 0, most_recent_at: null }, outbox: { unprocessed: 0, retrying: 0, dead_letter: 0, most_recent_at: null }, worker: { status: 'healthy', last_heartbeat_at: null } })
  aiOperations.listWebSearchJobs.mockResolvedValue([])
  aiOperations.listWebSearchCandidates.mockResolvedValue([])
  aiOperations.listExternalWebKnowledgeSources.mockResolvedValue([source])
  aiOperations.decideExternalWebKnowledgeSource.mockResolvedValue({ ...source, status: 'indexing' })
  aiOperations.listCommunityKnowledgeReviews.mockResolvedValue([communityReview])
  aiOperations.decideCommunityKnowledgeReview.mockResolvedValue({ ...communityReview, status: 'approved' })
})

describe('AiOperationsPage community knowledge review', () => {
  it('renders public-post provenance and approves with a required reason before refreshing the queue', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(aiOperations.listCommunityKnowledgeReviews).toHaveBeenCalledWith()
    expect(wrapper.text()).toContain('社区知识审核')
    expect(wrapper.text()).toContain('仅已发布且审核通过的公开社区帖子会进入社区 RAG')
    expect(wrapper.text()).toContain(communityReview.post_body_text)
    expect(wrapper.text()).toContain(communityReview.post_city_code)
    expect(wrapper.text()).toContain(communityReview.post_id)

    await wrapper.get('.community-review-item .text-action').trigger('click')
    const approvalButton = wrapper.findAll('button').find((button) => button.text() === '确认通过')!
    expect(approvalButton.attributes('disabled')).toBeDefined()

    const reasonInput = wrapper.findAll('textarea').at(-1)!
    await reasonInput.setValue('The route advice is specific and verifiable.')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(aiOperations.decideCommunityKnowledgeReview).toHaveBeenCalledWith(communityReview.post_id, { status: 'approved', reason: 'The route advice is specific and verifiable.' })
    expect(aiOperations.listCommunityKnowledgeReviews).toHaveBeenCalledTimes(2)
  })

  it('requires a reason before rejecting a public post', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.get('.community-review-item .text-action.danger').trigger('click')
    const rejectionButton = wrapper.findAll('button').find((button) => button.text() === '确认拒绝')!
    expect(rejectionButton.attributes('disabled')).toBeDefined()

    const reasonInput = wrapper.findAll('textarea').at(-1)!
    await reasonInput.setValue('The recommendation has no supporting details.')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(aiOperations.decideCommunityKnowledgeReview).toHaveBeenCalledWith(communityReview.post_id, { status: 'rejected', reason: 'The recommendation has no supporting details.' })
  })
})

describe('AiOperationsPage external source second review', () => {
  it('renders pending provenance and content, approves it, then refreshes the pending queue', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(aiOperations.listExternalWebKnowledgeSources).toHaveBeenCalledWith('pending_review')
    expect(wrapper.text()).toContain('外部网页资料二次审核')
    expect(wrapper.text()).toContain(source.source_host)
    expect(wrapper.text()).toContain(source.body_text)
    expect(wrapper.get('.external-source-provenance a').attributes('href')).toBe(source.source_url)

    await wrapper.get('.external-source-item .text-action').trigger('click')
    await flushPromises()

    expect(aiOperations.decideExternalWebKnowledgeSource).toHaveBeenCalledWith(source.id, { status: 'approved' })
    expect(aiOperations.listExternalWebKnowledgeSources).toHaveBeenCalledTimes(2)
  })

  it('requires a rejection reason before submitting the second-review decision', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.get('.external-source-item .text-action.danger').trigger('click')
    const rejectionButton = wrapper.findAll('button').find((button) => button.text() === '确认拒绝')!
    expect(rejectionButton.attributes('disabled')).toBeDefined()

    const reasonInput = wrapper.findAll('textarea').at(-1)!
    await reasonInput.setValue('The provenance does not support this guidance.')
    expect(rejectionButton.attributes('disabled')).toBeUndefined()

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(aiOperations.decideExternalWebKnowledgeSource).toHaveBeenCalledWith(source.id, { status: 'rejected', reason: 'The provenance does not support this guidance.' })
  })
})
