import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getMyAIEntitlements, listMyMembershipPurchases } = vi.hoisted(() => ({ getMyAIEntitlements: vi.fn(), listMyMembershipPurchases: vi.fn() }))
vi.mock('@/features/ai/assistantApi', () => ({ getMyAIEntitlements }))
vi.mock('./api', () => ({ listMyMembershipPurchases }))
vi.mock('@/services/api', () => ({ normalizeApiError: (value: Error) => value }))
import MyEntitlementsPage from './MyEntitlementsPage.vue'

describe('MyEntitlementsPage', () => {
  beforeEach(() => { vi.clearAllMocks(); getMyAIEntitlements.mockResolvedValue({ free: { itinerary_generation_remaining: 1, assistant_message_remaining: 20, period_end: '2026-09-01T00:00:00Z' }, membership: { itinerary_generation_remaining: 10, assistant_message_remaining: 300, period_end: '2026-09-15T00:00:00Z' } }); listMyMembershipPurchases.mockResolvedValue([{ id: 'purchase-1', plan_name: 'AI 规划会员', amount: '19.90', currency: 'CNY', duration_days: 30, payment_status: 'paid', authorization_status: 'authorized', valid_until: '2026-09-15T00:00:00Z', created_at: '2026-08-15T00:00:00Z' }]) })
  it('shows free and member balances with recent purchase facts', async () => {
    const wrapper = mount(MyEntitlementsPage, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()
    expect(wrapper.text()).toContain('免费额度')
    expect(wrapper.text()).toContain('20 次')
    expect(wrapper.text()).toContain('当前会员额度')
    expect(wrapper.text()).toContain('300 次')
    expect(wrapper.text()).toContain('AI 规划会员')
    expect(wrapper.text()).toContain('¥19.90')
  })

  it('shows a skeleton placeholder and busy state while loading', () => {
    getMyAIEntitlements.mockReturnValue(new Promise(() => {}))
    const wrapper = mount(MyEntitlementsPage, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(true)
    expect(wrapper.find('.skeleton-grid').exists()).toBe(true)
  })

  it('shows an error state with a retry action when the request fails', async () => {
    getMyAIEntitlements.mockRejectedValue(new Error('读取失败'))
    const wrapper = mount(MyEntitlementsPage, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()
    expect(wrapper.text()).toContain('读取失败')
    expect(wrapper.get('.state--error button').text()).toContain('重新读取')
  })

  it('shows the upgrade prompt and empty purchases when no membership or history exists', async () => {
    getMyAIEntitlements.mockResolvedValue({ free: { itinerary_generation_remaining: 1, assistant_message_remaining: 20, period_end: '2026-09-01T00:00:00Z' }, membership: null })
    listMyMembershipPurchases.mockResolvedValue([])
    const wrapper = mount(MyEntitlementsPage, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    await flushPromises()
    expect(wrapper.text()).toContain('还没有有效会员')
    expect(wrapper.text()).toContain('还没有购买记录')
  })
})
