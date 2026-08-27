import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { createMembershipPurchase, listPublishedMembershipPlans } = vi.hoisted(() => ({ createMembershipPurchase: vi.fn(), listPublishedMembershipPlans: vi.fn() }))
vi.mock('./api', () => ({ createMembershipPurchase, listPublishedMembershipPlans }))
vi.mock('@/services/api', () => ({ normalizeApiError: (value: Error) => value }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
import MembershipPlansPage from './MembershipPlansPage.vue'

describe('MembershipPlansPage', () => {
  beforeEach(() => { vi.clearAllMocks(); listPublishedMembershipPlans.mockResolvedValue([{ id: 'plan-1', code: 'ai-planner', name: 'AI 规划会员', price_amount: '19.90', currency: 'CNY', duration_days: 30, generation_quota: 10, assistant_quota: 300, purchasable: true, entitlement_codes: [], status: 'published', created_at: '', updated_at: '' }]) })
  it('shows the server plan price, duration, and AI quotas with a purchase action', async () => {
    const wrapper = mount(MembershipPlansPage, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()
    expect(wrapper.text()).toContain('¥19.90')
    expect(wrapper.text()).toContain('/ 30 天')
    expect(wrapper.text()).toContain('10 次行程生成')
    expect(wrapper.text()).toContain('300 次 AI 对话')
    expect(wrapper.get('.buy').text()).toContain('立即购买')
  })

  it('shows a skeleton placeholder and busy state while loading', () => {
    listPublishedMembershipPlans.mockReturnValue(new Promise(() => {}))
    const wrapper = mount(MembershipPlansPage, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(true)
    expect(wrapper.find('.skeleton-grid').exists()).toBe(true)
  })

  it('shows an error state with a retry action when the request fails', async () => {
    listPublishedMembershipPlans.mockRejectedValue(new Error('网络异常'))
    const wrapper = mount(MembershipPlansPage, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()
    expect(wrapper.text()).toContain('网络异常')
    expect(wrapper.get('.state--error button').text()).toContain('重新读取')
  })
})
