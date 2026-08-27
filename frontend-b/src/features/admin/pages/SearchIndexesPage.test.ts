import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const service = vi.hoisted(() => ({ listSearchIndexes: vi.fn(), rebuildSearchIndex: vi.fn(), getSearchIndexRebuildJob: vi.fn() }))
vi.mock('../services/searchIndexes', () => service)
vi.mock('@/services/api', () => ({ normalizeApiError: (cause: unknown) => ({ message: String(cause) }) }))

import SearchIndexesPage from './SearchIndexesPage.vue'

function mountPage() { return mount(SearchIndexesPage, { global: { stubs: { 'el-tag': { template: '<span><slot /></span>' } }, directives: { loading: {} } } }) }

beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); service.listSearchIndexes.mockResolvedValue([{ logical_name: 'official_knowledge', index_name: 'official-v1', status: 'healthy', document_count: 4, message: null }]); service.rebuildSearchIndex.mockResolvedValue({ id: 'job-1', index_name: 'official_knowledge', requested_by: 'admin-1', status: 'queued', progress: 0, error: null, created_at: '', updated_at: '', started_at: null, completed_at: null }) })
afterEach(() => vi.useRealTimers())

describe('SearchIndexesPage', () => {
  it('renders healthy inventory items', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('官方知识')
    expect(wrapper.text()).toContain('official-v1')
    expect(wrapper.text()).toContain('健康')
  })

  it('renders a retryable error', async () => {
    service.listSearchIndexes.mockRejectedValue(new Error('Elasticsearch is unavailable'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('Elasticsearch is unavailable')
    expect(wrapper.text()).toContain('重新尝试')
  })

  it('renders the configured empty state', async () => {
    service.listSearchIndexes.mockResolvedValue([])
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无已配置索引')
  })

  it('renders unavailable index status without hiding the inventory', async () => {
    service.listSearchIndexes.mockResolvedValue([{ logical_name: 'official_knowledge', index_name: 'official-v1', status: 'unavailable', document_count: null, message: 'Elasticsearch is unavailable.' }])
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('不可用')
    expect(wrapper.text()).toContain('Elasticsearch is unavailable.')
  })

  it('only offers rebuild for official and community knowledge', async () => {
    service.listSearchIndexes.mockResolvedValue(['official_knowledge', 'community_knowledge', 'travel_knowledge', 'user_memory'].map((logical_name) => ({ logical_name, index_name: `${logical_name}-v1`, status: 'healthy', document_count: 1, message: null })))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.findAll('button.rebuild-button')).toHaveLength(2)
    expect(wrapper.findAll('.index-row').find((row) => row.text().includes('旅行知识'))?.find('button.rebuild-button').exists()).toBe(false)
    expect(wrapper.findAll('.index-row').find((row) => row.text().includes('用户记忆'))?.find('button.rebuild-button').exists()).toBe(false)
  })

  it('polls an active rebuild and refreshes inventory after success', async () => {
    service.getSearchIndexRebuildJob.mockResolvedValue({ id: 'job-1', index_name: 'official_knowledge', requested_by: 'admin-1', status: 'succeeded', progress: 100, error: null, created_at: '', updated_at: '', started_at: '', completed_at: '' })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('button.rebuild-button').trigger('click')
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(service.getSearchIndexRebuildJob).toHaveBeenCalledWith('job-1')
    expect(service.listSearchIndexes).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('重建完成')
  })

  it('shows a failed rebuild result', async () => {
    service.getSearchIndexRebuildJob.mockResolvedValue({ id: 'job-1', index_name: 'official_knowledge', requested_by: 'admin-1', status: 'failed', progress: 43, error: '重建服务不可用', created_at: '', updated_at: '', started_at: '', completed_at: '' })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('button.rebuild-button').trigger('click')
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.text()).toContain('重建失败：重建服务不可用')
  })

  it('stops rebuild polling when unmounted', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('button.rebuild-button').trigger('click')
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(1500)
    expect(service.getSearchIndexRebuildJob).not.toHaveBeenCalled()
  })
})
