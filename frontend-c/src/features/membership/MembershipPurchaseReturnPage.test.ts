import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const { replace, route } = vi.hoisted(() => ({ replace: vi.fn(), route: { params: {} as Record<string, string> } }))
vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => ({ replace }),
}))
import MembershipPurchaseReturnPage from './MembershipPurchaseReturnPage.vue'

describe('MembershipPurchaseReturnPage', () => {
  it('redirects to the payment page when a purchaseId is present', async () => {
    route.params = { purchaseId: 'purchase-1' }
    mount(MembershipPurchaseReturnPage)
    await flushPromises()
    expect(replace).toHaveBeenCalledWith('/memberships/pay/purchase-1')
  })

  it('redirects to the membership list when purchaseId is missing', async () => {
    replace.mockClear()
    route.params = {}
    mount(MembershipPurchaseReturnPage)
    await flushPromises()
    expect(replace).toHaveBeenCalledWith('/memberships')
  })

  it('renders a busy loading state while redirecting', () => {
    route.params = { purchaseId: 'purchase-2' }
    const wrapper = mount(MembershipPurchaseReturnPage)
    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在恢复会员支付状态')
  })
})
