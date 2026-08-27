import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { createMembershipQrPayment, getCurrentMembershipQrPayment, listMyMembershipPurchases, queryMembershipPurchasePayment, refreshMembershipQrPayment } = vi.hoisted(() => ({ createMembershipQrPayment: vi.fn(), getCurrentMembershipQrPayment: vi.fn(), listMyMembershipPurchases: vi.fn(), queryMembershipPurchasePayment: vi.fn(), refreshMembershipQrPayment: vi.fn() }))
const renderer = vi.hoisted(() => ({ addData: vi.fn(), make: vi.fn(), createDataURL: vi.fn(() => 'data:image/png;base64,local') }))
vi.mock('./api', () => ({ createMembershipQrPayment, getCurrentMembershipQrPayment, listMyMembershipPurchases, queryMembershipPurchasePayment, refreshMembershipQrPayment }))
vi.mock('qrcode-generator', () => ({ default: vi.fn(() => renderer) }))
vi.mock('vue-router', () => ({ RouterLink: { template: '<a><slot /></a>' }, useRoute: () => ({ params: { purchaseId: 'purchase-1' } }) }))
vi.mock('@/services/api', () => ({ normalizeApiError: (value: Error) => value }))
import MembershipQrPaymentPage from './MembershipQrPaymentPage.vue'

const activePayment = { attempt_id: 'attempt-1', payment_no: 'payment-1', qr_code: 'alipay://local-code', expires_at: '2099-01-01T00:00:00Z', status: 'pending', payment_status: 'pending', authorization_status: 'pending' }
const purchase = { id: 'purchase-1', membership_plan_id: 'plan-1', plan_name: 'AI 规划会员', amount: '19.90', currency: 'CNY', duration_days: 30, generation_quota: 10, assistant_quota: 300, status: 'pending_payment', payment_status: 'pending', authorization_status: 'pending', payment_no: null, paid_at: null, authorized_at: null, valid_from: null, valid_until: null, created_at: '' }

describe('MembershipQrPaymentPage', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    listMyMembershipPurchases.mockResolvedValue([purchase])
    getCurrentMembershipQrPayment.mockResolvedValue(activePayment)
    queryMembershipPurchasePayment.mockResolvedValue(activePayment)
  })

  afterEach(() => vi.useRealTimers())

  function page() { return mount(MembershipQrPaymentPage) }

  it('renders the raw code locally and polls every three seconds without navigation', async () => {
    const wrapper = page()
    await flushPromises()
    expect(renderer.addData).toHaveBeenCalledWith('alipay://local-code')
    expect(wrapper.get('img').attributes('src')).toBe('data:image/png;base64,local')
    await vi.advanceTimersByTimeAsync(3000)
    expect(queryMembershipPurchasePayment).toHaveBeenCalledWith('purchase-1')
    expect(window.location.href).not.toContain('alipay')
    wrapper.unmount()
  })

  it('pauses while hidden, immediately queries when visible, and cleans up on unmount', async () => {
    const wrapper = page()
    await flushPromises()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(6000)
    expect(queryMembershipPurchasePayment).not.toHaveBeenCalled()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(queryMembershipPurchasePayment).toHaveBeenCalledTimes(1)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(6000)
    expect(queryMembershipPurchasePayment).toHaveBeenCalledTimes(1)
  })

  it('only enables manual QR refresh after expiry and stops polling for authorization', async () => {
    getCurrentMembershipQrPayment.mockResolvedValue({ ...activePayment, status: 'expired', qr_code: null })
    refreshMembershipQrPayment.mockResolvedValue(activePayment)
    const wrapper = page()
    await flushPromises()
    await wrapper.get('.refresh').trigger('click')
    await flushPromises()
    expect(refreshMembershipQrPayment).toHaveBeenCalledWith('purchase-1')
    queryMembershipPurchasePayment.mockResolvedValue({ ...activePayment, status: 'paid', authorization_status: 'authorized', qr_code: null })
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(6000)
    expect(queryMembershipPurchasePayment).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
