import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { createManualPlan, getMySettings, searchDestinations, submit, planning } = vi.hoisted(() => ({
  createManualPlan: vi.fn(), searchDestinations: vi.fn(), submit: vi.fn(),
  getMySettings: vi.fn(),
  planning: { reset: vi.fn(), stopPolling: vi.fn(), submit: vi.fn(), retry: vi.fn(), applyPreview: vi.fn(), state: 'idle', job: null, message: '', preview: null, previewLoading: false, applyingPreview: false, appliedItineraryId: '', progress: 0, isWorking: false, canRetry: false },
}))
const destination = { id: '430100', name: '长沙市', display_address: '中国 · 湖南省 · 长沙市', city_code: '430100', kind: 'city' as const }
const otherDestination = { id: '220100', name: '长春市', display_address: '中国 · 吉林省 · 长春市', city_code: '220100', kind: 'city' as const }

vi.mock('../destinationsApi', () => ({ createManualPlan, searchDestinations }))
vi.mock('../stores/aiPlanning', () => ({ useAiPlanningStore: () => ({ ...planning, submit }) }))
vi.mock('@/services/api', () => ({ normalizeApiError: () => ({ message: '请求失败。' }) }))
vi.mock('@/features/settings/api', () => ({ getMySettings }))
const push = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), useRoute: () => ({ query: {} }) }))

import PlanPage from './PlanPage.vue'

function mountPage() { return mount(PlanPage) }
async function search(wrapper: ReturnType<typeof mountPage>, query = '长沙') {
  await wrapper.get('#destination').setValue(query)
  await new Promise((resolve) => setTimeout(resolve, 270))
  await flushPromises()
}
async function selectAndDate(wrapper: ReturnType<typeof mountPage>) {
  searchDestinations.mockResolvedValue([destination])
  await search(wrapper)
  await wrapper.get('#destination').trigger('keydown', { key: 'ArrowDown' })
  await wrapper.get('#destination').trigger('keydown', { key: 'Enter' })
  await wrapper.find('input[type="date"]').setValue('2099-08-10')
  await wrapper.findAll('input[type="date"]')[1].setValue('2099-08-12')
}

describe('PlanPage', () => {
  beforeEach(() => { Object.assign(planning, { state: 'idle', job: null, message: '', preview: null, previewLoading: false, applyingPreview: false, appliedItineraryId: '', progress: 0, isWorking: false, canRetry: false }); vi.clearAllMocks(); getMySettings.mockResolvedValue({ departure_city: null, budget_level: 'premium', travel_pace: 'relaxed', interest_tags: ['吃吃喝喝'], traveler_type: 'family', notifications_enabled: true, order_notifications: true, itinerary_notifications: true, community_notifications: true, profile_visibility: 'collaborators' }) })

  it('requires selecting a destination result rather than submitting typed text', async () => {
    const wrapper = mountPage()
    await wrapper.get('#destination').setValue('长沙')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('请从搜索结果中选择目的地')
  })

  it('selects a destination with ArrowDown and Enter', async () => {
    searchDestinations.mockResolvedValue([destination])
    const wrapper = mountPage()
    await search(wrapper)
    await wrapper.get('#destination').trigger('keydown', { key: 'ArrowDown' })
    await wrapper.get('#destination').trigger('keydown', { key: 'Enter' })
    expect((wrapper.get('#destination').element as HTMLInputElement).value).toBe('长沙市')
    expect(wrapper.text()).toContain('中国 · 湖南省 · 长沙市')
  })

  it('ignores an older response after a newer destination search', async () => {
    let resolveOld!: (value: typeof destination[]) => void
    let resolveNew!: (value: typeof destination[]) => void
    searchDestinations.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve })).mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve }))
    const wrapper = mountPage()
    await wrapper.get('#destination').setValue('长')
    await new Promise((resolve) => setTimeout(resolve, 270))
    await wrapper.get('#destination').setValue('长沙')
    await new Promise((resolve) => setTimeout(resolve, 270))
    resolveNew([destination])
    await flushPromises()
    resolveOld([otherDestination])
    await flushPromises()
    expect(wrapper.text()).toContain('长沙市')
    expect(wrapper.text()).not.toContain('长春市')
  })

  it('keeps preference selection to three tags', async () => {
    const wrapper = mountPage()
    const tags = wrapper.findAll('.tag-list button')
    await tags[0].trigger('click'); await tags[1].trigger('click'); await tags[2].trigger('click'); await tags[3].trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('最多选择 3 个旅行偏好')
    expect(wrapper.findAll('.tag-list button.selected')).toHaveLength(3)
  })

  it('creates a manual plan without calling AI generation', async () => {
    createManualPlan.mockResolvedValue({ id: 'itinerary-1' })
    const wrapper = mountPage()
    await selectAndDate(wrapper)
    await wrapper.get('.manual-action').trigger('click')
    await flushPromises()
    expect(createManualPlan).toHaveBeenCalledOnce()
    expect(submit).not.toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith('/itineraries/itinerary-1')
  })

  it('shows saved preferences but omits untouched optional fields from the request', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await selectAndDate(wrapper)
    await wrapper.get('form').trigger('submit')

    expect(wrapper.text()).toContain('默认使用个人设置')
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      preference_tags: undefined,
      pace: undefined,
      traveler_type: undefined,
    }))
  })

  it('sends explicit preference clears without inventing a numeric budget', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await selectAndDate(wrapper)
    await wrapper.get('[data-tag="吃吃喝喝"]').trigger('click')
    await wrapper.findAll('.choice-list')[0].get('button.clear-preference').trigger('click')
    await wrapper.findAll('.choice-list')[1].get('button.clear-preference').trigger('click')
    await wrapper.get('form').trigger('submit')

    expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      preference_tags: [],
      pace: null,
      traveler_type: null,
    }))
    expect(submit.mock.calls[0][0]).not.toHaveProperty('budget_amount')
  })

  it('sends an explicit pace choice only after the traveler changes it', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await selectAndDate(wrapper)
    await wrapper.findAll('.choice-list')[0].findAll('button')[2].trigger('click')
    await wrapper.get('form').trigger('submit')

    expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      pace: 'fast',
      preference_tags: undefined,
      traveler_type: undefined,
    }))
  })

  it('labels live citations as current live web material', () => {
    Object.assign(planning, {
      state: 'ready',
      preview: { draft: { title: '长沙三日游', days: [] }, citations: [{ chunk_id: 'live-1', source_type: 'live_web', content: '岳麓山开放信息' }] },
    })
    const wrapper = mountPage()
    expect(wrapper.text()).toContain('本次实时网络资料')
  })

  it('navigates to the itinerary list after confirming an AI preview', async () => {
    Object.assign(planning, {
      state: 'ready',
      appliedItineraryId: 'itinerary-1',
      preview: { draft: { title: '长沙三日游', days: [] }, citations: [] },
    })
    const wrapper = mountPage()
    await wrapper.findAll('.preview .smart-action')[0].trigger('click')
    await flushPromises()

    expect(planning.applyPreview).toHaveBeenCalledOnce()
    expect(push).toHaveBeenCalledWith('/itineraries')
  })
})
