import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CompanionPlanDetailPage from './CompanionPlanDetailPage.vue'

const mocks = vi.hoisted(() => ({
  getPlan: vi.fn(),
  listApplications: vi.fn(),
  listMine: vi.fn(),
  withdraw: vi.fn(),
  accept: vi.fn(),
  push: vi.fn(),
  authenticated: true,
}))

vi.mock('vue-router', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRouter: () => ({ push: mocks.push }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ get isConsumerSession() { return mocks.authenticated } }) }))
vi.mock('./companionPlansApi', async (importOriginal) => ({
  ...await importOriginal<typeof import('./companionPlansApi')>(),
  getCompanionPlan: mocks.getPlan,
  listCompanionPlanApplications: mocks.listApplications,
  listMyCompanionApplications: mocks.listMine,
  withdrawCompanionApplication: mocks.withdraw,
  acceptCompanionApplication: mocks.accept,
  applyToCompanionPlan: vi.fn(),
  cancelCompanionPlan: vi.fn(),
  closeCompanionPlan: vi.fn(),
  completeCompanionPlan: vi.fn(),
  leaveCompanionPlan: vi.fn(),
  rejectCompanionApplication: vi.fn(),
  removeCompanionMember: vi.fn(),
  reopenCompanionPlan: vi.fn(),
  updateCompanionPlan: vi.fn(),
}))

function plan(viewerRole: 'owner' | 'applicant' | 'public', applicationStatus: 'pending' | 'withdrawn' | null = null, reviewStatus?: 'pending_review' | 'approved' | 'rejected') {
  return {
    id: 'plan-1', title: '西湖同行', city_code: '330100', trip_kind: 'trip', start_date: '2026-10-01', end_date: '2026-10-02',
    party_size: 3, accepted_count: 1, budget_min: null, budget_max: null, currency: null, travel_pace: 'slow', interest_tags: ['citywalk'],
    intro_text: '一起慢慢走。', route_count: 1, cover_candidate: null, status: 'open', application_status: applicationStatus,
    viewer_role: viewerRole, review_status: reviewStatus, members: [], itinerary_id: viewerRole === 'owner' ? 'itinerary-1' : null, conversation_id: null, protected_itinerary: null,
  }
}

describe('CompanionPlanDetailPage workflow', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.authenticated = true })

  it('shows the application form to an authenticated non-owner even when detail role is public', async () => {
    mocks.getPlan.mockResolvedValue(plan('public', null, 'approved'))
    const wrapper = mount(CompanionPlanDetailPage, { props: { requestId: 'plan-1' }, global: { stubs: { RouterLink: true, CompanionPlanTimeline: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('留下你的同行说明')
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('shows public viewers a login CTA instead of the application form', async () => {
    mocks.authenticated = false
    mocks.getPlan.mockResolvedValue(plan('public', null, 'approved'))
    const wrapper = mount(CompanionPlanDetailPage, { props: { requestId: 'plan-1' }, global: { stubs: { RouterLink: true, CompanionPlanTimeline: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('登录并申请')
    expect(wrapper.find('textarea').exists()).toBe(false)
    await wrapper.findAll('button').find((button) => button.text().includes('登录并申请'))!.trigger('click')
    expect(mocks.push).toHaveBeenCalledWith({ path: '/login', query: { redirect: '/companions/plan-1' } })
  })

  it('uses viewer_role so the owner sees pending messages but never apply UI', async () => {
    mocks.getPlan.mockResolvedValue(plan('owner'))
    mocks.listApplications.mockResolvedValue([{ id: 'application-1', request_id: 'plan-1', applicant_id: 'user-2', applicant_display_name: '小林', message: '喜欢早起和逛市场。', status: 'pending', conversation_id: null }])
    const wrapper = mount(CompanionPlanDetailPage, { props: { requestId: 'plan-1' }, global: { stubs: { RouterLink: true, CompanionPlanTimeline: true } } })
    await flushPromises()

    expect(wrapper.text()).toContain('待处理申请（1）')
    expect(wrapper.text()).toContain('小林')
    expect(wrapper.text()).toContain('喜欢早起和逛市场。')
    expect(wrapper.text()).toContain('待处理')
    expect(wrapper.text()).toContain('招募中')
    expect(wrapper.text()).not.toContain('留下你的同行说明')
    expect(wrapper.find('textarea').exists()).toBe(false)
  })

  it('keeps withdrawal as the pending action and reloads the application form afterward', async () => {
    mocks.getPlan.mockResolvedValueOnce(plan('applicant', 'pending')).mockResolvedValueOnce(plan('applicant', 'withdrawn'))
    mocks.listMine.mockResolvedValue([{ id: 'application-1', request_id: 'plan-1', applicant_id: 'user-2', message: '同行申请', status: 'pending', conversation_id: null }])
    mocks.withdraw.mockResolvedValue({ status: 'withdrawn' })
    const wrapper = mount(CompanionPlanDetailPage, { props: { requestId: 'plan-1' }, global: { stubs: { RouterLink: true, CompanionPlanTimeline: true } } })
    await flushPromises()

    const withdrawButton = wrapper.findAll('button').find((button) => button.text().includes('撤回申请'))
    expect(withdrawButton).toBeDefined()
    await withdrawButton!.trigger('click')
    await flushPromises()

    expect(mocks.withdraw).toHaveBeenCalledWith('application-1')
    expect(wrapper.text()).toContain('留下你的同行说明')
    expect(wrapper.text()).toContain('发送申请')
  })

  it('hides owner lifecycle actions until review approval', async () => {
    mocks.getPlan.mockResolvedValue(plan('owner', null, 'pending_review'))
    mocks.listApplications.mockResolvedValue([])
    const wrapper = mount(CompanionPlanDetailPage, { props: { requestId: 'plan-1' }, global: { stubs: { RouterLink: true, CompanionPlanTimeline: true } } })
    await flushPromises()

    expect(wrapper.text()).not.toContain('关闭招募')
    expect(wrapper.text()).not.toContain('取消计划')
    expect(wrapper.text()).not.toContain('完成计划')
  })

  it('shows approved owner lifecycle actions for an open plan', async () => {
    mocks.getPlan.mockResolvedValue(plan('owner', null, 'approved'))
    mocks.listApplications.mockResolvedValue([])
    const wrapper = mount(CompanionPlanDetailPage, { props: { requestId: 'plan-1' }, global: { stubs: { RouterLink: true, CompanionPlanTimeline: true } } })
    await flushPromises()

    expect(wrapper.text()).toContain('关闭招募')
    expect(wrapper.text()).toContain('取消计划')
    expect(wrapper.text()).toContain('完成计划')
  })

  it('requires group name and uploaded avatar before first acceptance', async () => {
    mocks.getPlan.mockResolvedValue(plan('owner', null, 'approved'))
    mocks.listApplications.mockResolvedValue([{ id: 'application-1', request_id: 'plan-1', applicant_id: 'user-2', message: '同行申请', status: 'pending', conversation_id: null }])
    const wrapper = mount(CompanionPlanDetailPage, { props: { requestId: 'plan-1' }, global: { stubs: { RouterLink: true, CompanionPlanTimeline: true, ImageReferenceUpload: { template: '<button type="button" @click="$emit(\'completed\', \'asset-1\')">上传头像</button>' } } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '接受')!.trigger('click')
    expect(wrapper.text()).toContain('设置群聊资料')
    const submit = wrapper.findAll('button').find((button) => button.text().includes('确认并接受'))!
    expect(submit.attributes('disabled')).toBeDefined()
    await wrapper.find('input[placeholder="例如：西湖慢行小组"]').setValue('西湖慢行小组')
    expect(submit.attributes('disabled')).toBeDefined()
    await wrapper.findAll('button').find((button) => button.text() === '上传头像')!.trigger('click')
    expect(submit.attributes('disabled')).toBeUndefined()
    mocks.accept.mockResolvedValue({ conversation_id: 'conversation-1' })
    await submit.trigger('click')
    await flushPromises()
    expect(mocks.accept).toHaveBeenCalledWith('application-1', '西湖慢行小组', 'asset-1')
  })

  it('accepts later applications without reopening group profile', async () => {
    const existing = { ...plan('owner', null, 'approved'), conversation_id: 'conversation-1' }
    mocks.getPlan.mockResolvedValue(existing)
    mocks.listApplications.mockResolvedValue([{ id: 'application-2', request_id: 'plan-1', applicant_id: 'user-3', message: '同行申请', status: 'pending', conversation_id: 'conversation-1' }])
    mocks.accept.mockResolvedValue({ conversation_id: 'conversation-1' })
    const wrapper = mount(CompanionPlanDetailPage, { props: { requestId: 'plan-1' }, global: { stubs: { RouterLink: true, CompanionPlanTimeline: true, ImageReferenceUpload: true } } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '接受')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('设置群聊资料')
    expect(mocks.accept).toHaveBeenCalledWith('application-2')
  })
})
