import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OrderStateCard from './components/OrderStateCard.vue'
import MockTicketStatePanel from './components/MockTicketStatePanel.vue'
import PaymentContinuationPanel from './components/PaymentContinuationPanel.vue'
import RefundRequestPanel from './components/RefundRequestPanel.vue'
import OrdersPage from './pages/OrdersPage.vue'
import SearchPage from './pages/SearchPage.vue'

const paymentApi = vi.hoisted(() => ({
  createTravelOrderPayment: vi.fn(),
  createTravelOrderRefund: vi.fn(),
  createTravelOrder: vi.fn(),
  createTravelSearch: vi.fn(),
  fetchMockTransportTicket: vi.fn(),
  fetchTravelOrders: vi.fn(),
  queryTravelOrderPayment: vi.fn(),
}))

vi.mock('./api', () => paymentApi)

describe('OrderStateCard', () => {
  const order = { id: '1', order_no: 'TO1', amount: '100.00', currency: 'CNY', status: 'PAID_PENDING_FULFILLMENT', payment_status: 'paid', fulfillment_status: 'pending_confirmation' as const, created_at: '2026-08-01T00:00:00Z' }

  it.each([
    ['pending_confirmation', 'Payment received. Supplier confirmation is still pending.'],
    ['confirming', 'Supplier confirmation is in progress.'],
    ['confirmed', 'Supplier confirmation has been received.'],
    ['failed', 'Fulfillment could not be completed.'],
    ['not_supported', 'Fulfillment is unavailable for this order.'],
  ] as const)('renders the server-reported %s fulfillment state', (fulfillmentStatus, expected) => {
    const wrapper = mount(OrderStateCard, { props: { order: { ...order, fulfillment_status: fulfillmentStatus } } })
    expect(wrapper.text()).toContain(expected)
    expect(wrapper.text()).not.toContain('Ticket issued')
  })
})

describe('MockTicketStatePanel', () => {
  it('renders issued mock-ticket facts without passenger document details', async () => {
    paymentApi.fetchMockTransportTicket.mockResolvedValue({ data: { id: 'ticket-1', transport_type: 'train', status: 'issued', mock_ticket_no: 'MOCK-1', seat_assignments: {}, passenger_facts: { masked_document_number: '********1234' }, failure_code: null } })
    const wrapper = mount(MockTicketStatePanel, { props: { order: { id: '1', order_no: 'TO1', amount: '100.00', currency: 'CNY', status: 'CONFIRMED', payment_status: 'paid', fulfillment_status: 'confirmed', created_at: '2026-08-01T00:00:00Z' } } })

    await vi.waitFor(() => expect(wrapper.text()).toContain('模拟票已出票'))
    expect(wrapper.text()).toContain('模拟票已出票')
    expect(wrapper.text()).toContain('MOCK-1')
    expect(wrapper.text()).not.toContain('********1234')
  })
})

describe('SearchPage', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    window.localStorage.clear()
    paymentApi.createTravelSearch.mockReset()
    paymentApi.createTravelOrder.mockReset()
  })

  it('submits exact train station names and creates an order with transient passenger and seat details only', async () => {
    paymentApi.createTravelSearch.mockResolvedValue({ data: { id: 'job-1', status: 'completed', source: 'mock-supplier', unavailable_code: null, retrieved_at: '2026-08-01T00:00:00Z', offers: [{ id: 'offer-1', source: 'mock-supplier', title: 'G100 杭州东至上海虹桥', amount: '553.00', currency: 'CNY', availability: 'available', valid_until: '2026-08-02T00:00:00Z', retrieved_at: '2026-08-01T00:00:00Z', change_rules: {} }] } })
    paymentApi.createTravelOrder.mockResolvedValue({ data: { id: 'order-1', order_no: 'TO1' } })
    const sessionSetItem = vi.spyOn(window.sessionStorage, 'setItem')
    const localSetItem = vi.spyOn(window.localStorage, 'setItem')
    const wrapper = mount(SearchPage)

    expect((wrapper.get('input[aria-label="出发车站"]').element as HTMLInputElement).value).toBe('杭州东')
    expect((wrapper.get('input[aria-label="到达车站"]').element as HTMLInputElement).value).toBe('上海虹桥')
    expect(wrapper.text()).toContain('请输入具体车站，例如杭州东、上海虹桥；系统会自动解析站码。')
    await wrapper.get('form.search-grid').trigger('submit')
    await vi.waitFor(() => expect(paymentApi.createTravelSearch).toHaveBeenCalledWith({ search_type: 'train', origin: '杭州东', destination: '上海虹桥', depart_date: '2026-10-01', passenger_count: 1 }))
    await vi.waitFor(() => expect(wrapper.text()).toContain('G100 杭州东至上海虹桥'))
    await wrapper.get('.offer-action button').trigger('click')
    const fields = wrapper.findAll('.passenger-form input')
    await fields[0].setValue('张三')
    await fields[1].setValue('310101199001011234')
    const selects = wrapper.findAll('.passenger-form select')
    await selects[0].setValue('identity_card')
    await selects[1].setValue('window')
    await wrapper.vm.$nextTick()
    await wrapper.get('.passenger-form').trigger('submit')

    expect(paymentApi.createTravelOrder).toHaveBeenCalledWith('offer-1', [{ name: '张三', document_type: 'identity_card', document_number: '310101199001011234', seat_preference: 'window' }])
    expect(wrapper.text()).toContain('座位偏好，最终以出票结果为准')
    expect(sessionSetItem).not.toHaveBeenCalled()
    expect(localSetItem).not.toHaveBeenCalled()
  })

  it('uses city labels for flight searches', async () => {
    const wrapper = mount(SearchPage)

    await wrapper.get('input[type="radio"][value="flight"]').setValue()

    expect(wrapper.get('input[aria-label="出发城市"]').attributes('placeholder')).toBe('例如杭州')
    expect(wrapper.get('input[aria-label="到达城市"]').attributes('placeholder')).toBe('例如上海')
    expect(wrapper.text()).not.toContain('请输入具体车站，例如杭州东、上海虹桥；系统会自动解析站码。')
  })

  it('shows the provider outage message when realtime transport is unavailable', async () => {
    paymentApi.createTravelSearch.mockResolvedValue({ data: { id: 'job-1', status: 'empty', source: 'realtime-transport', unavailable_code: 'REALTIME_TRANSPORT_UNAVAILABLE', retrieved_at: '2026-08-01T00:00:00Z', offers: [] } })
    const wrapper = mount(SearchPage)

    await wrapper.get('form.search-grid').trigger('submit')

    await vi.waitFor(() => expect(wrapper.text()).toContain('供应商服务暂不可用，未展示价格或余量。'))
  })
})

describe('OrdersPage', () => {
  beforeEach(() => {
    paymentApi.fetchTravelOrders.mockReset()
  })

  it('reloads orders when the user requests a refresh', async () => {
    paymentApi.fetchTravelOrders
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({ data: [{ id: '1', order_no: 'TO1', amount: '100.00', currency: 'CNY', status: 'CONFIRMED', payment_status: 'paid', fulfillment_status: 'confirmed' as const, created_at: '2026-08-01T00:00:00Z' }] })
    const wrapper = mount(OrdersPage, { global: { stubs: { PaymentContinuationPanel: true } } })

    await vi.waitFor(() => expect(paymentApi.fetchTravelOrders).toHaveBeenCalledTimes(1))
    await vi.waitFor(() => expect(wrapper.get('button.refresh-orders').attributes('disabled')).toBeUndefined())
    await wrapper.get('button.refresh-orders').trigger('click')
    await vi.waitFor(() => expect(paymentApi.fetchTravelOrders).toHaveBeenCalledTimes(2))

    expect(wrapper.text()).toContain('TO1')
  })
})

describe('PaymentContinuationPanel', () => {
  const pendingOrder = { id: '1', order_no: 'TO1', amount: '100.00', currency: 'CNY', status: 'PENDING_CONFIRMATION', payment_status: 'pending', fulfillment_status: 'pending_confirmation' as const, created_at: '2026-08-01T00:00:00Z' }

  beforeEach(() => {
    window.sessionStorage.clear()
    paymentApi.createTravelOrderPayment.mockReset()
    paymentApi.queryTravelOrderPayment.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the configured-payment unavailable result from refreshed order facts', async () => {
    paymentApi.createTravelOrderPayment.mockRejectedValueOnce({ code: 'PAYMENT_NOT_CONFIGURED' })
    paymentApi.queryTravelOrderPayment.mockResolvedValue({ data: { ...pendingOrder, status: 'FAILED', payment_status: 'failed', fulfillment_status: 'not_supported', failure_code: 'PAYMENT_NOT_CONFIGURED' } })
    const wrapper = mount(PaymentContinuationPanel, { props: { order: pendingOrder } })

    await wrapper.get('button.primary').trigger('click')
    await vi.waitFor(() => expect(paymentApi.queryTravelOrderPayment).toHaveBeenCalledWith('1'))

    expect(wrapper.emitted('updated')?.[0]).toEqual([{ ...pendingOrder, status: 'FAILED', payment_status: 'failed', fulfillment_status: 'not_supported', failure_code: 'PAYMENT_NOT_CONFIGURED' }])
    expect(wrapper.text()).toContain('Online payment is unavailable for this order')
  })

  it('reuses a session idempotency key and rejects insecure checkout links', async () => {
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000001')
    paymentApi.createTravelOrderPayment.mockResolvedValue({ data: { id: 'pay-1', payment_no: 'PAY1', amount: '100.00', currency: 'CNY', status: 'pending', redirect_url: 'http://checkout.example.test' } })
    paymentApi.queryTravelOrderPayment.mockResolvedValue({ data: pendingOrder })
    const wrapper = mount(PaymentContinuationPanel, { props: { order: pendingOrder } })

    await wrapper.get('button.primary').trigger('click')
    await wrapper.get('button.primary').trigger('click')

    expect(paymentApi.createTravelOrderPayment).toHaveBeenNthCalledWith(1, '1', '00000000-0000-4000-8000-000000000001')
    expect(paymentApi.createTravelOrderPayment).toHaveBeenNthCalledWith(2, '1', '00000000-0000-4000-8000-000000000001')
    expect(wrapper.text()).toContain('did not provide a secure checkout link')
  })
})

describe('RefundRequestPanel', () => {
  const refundableOrder = { id: '1', order_no: 'TO1', amount: '100.00', currency: 'CNY', status: 'PAID_PENDING_FULFILLMENT', payment_status: 'paid', fulfillment_status: 'pending_confirmation' as const, created_at: '2026-08-01T00:00:00Z' }

  beforeEach(() => {
    window.sessionStorage.clear()
    paymentApi.createTravelOrderRefund.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('submits an eligible refund with its reason and an idempotency key without claiming completion', async () => {
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000002')
    paymentApi.createTravelOrderRefund.mockResolvedValue({ data: { id: 'refund-1', status: 'processing', amount: '100.00', currency: 'CNY' } })
    const wrapper = mount(RefundRequestPanel, { props: { order: refundableOrder } })

    await wrapper.get('textarea').setValue('Plans changed')
    await wrapper.get('form').trigger('submit')

    expect(paymentApi.createTravelOrderRefund).toHaveBeenCalledWith('1', {
      amount: '100.00',
      currency: 'CNY',
      reason: 'Plans changed',
    }, '00000000-0000-4000-8000-000000000002')
    expect(wrapper.text()).toContain('Refund processing: CNY 100.00.')
    expect(wrapper.text()).not.toContain('Refunded: CNY 100.00.')
  })

  it('does not expose refund submission for orders outside the paid pending-fulfillment state', () => {
    const wrapper = mount(RefundRequestPanel, { props: { order: { ...refundableOrder, fulfillment_status: 'confirmed' as const } } })

    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).toContain('available only for paid orders awaiting supplier fulfillment')
  })

  it('reports submission failure without claiming that a refund was completed', async () => {
    paymentApi.createTravelOrderRefund.mockRejectedValue(new Error('network'))
    const wrapper = mount(RefundRequestPanel, { props: { order: refundableOrder } })

    await wrapper.get('textarea').setValue('Plans changed')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.text()).toContain('Refund request could not be submitted. No refund has been confirmed.')
  })
})
