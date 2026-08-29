import { api } from '@/services/api'
import { newClientId } from '@/services/id'

export type SearchType = 'train' | 'flight' | 'hotel' | 'ride'
export type FulfillmentStatus = 'pending_confirmation' | 'confirming' | 'confirmed' | 'failed' | 'not_supported'
export type RefundStatus = 'requested' | 'processing' | 'refunded' | 'failed'
export type SeatPreference = 'window' | 'aisle' | 'none'

export interface TravelOffer {
  id: string
  source: string
  title: string
  amount: string
  currency: string
  availability: 'available' | 'unavailable'
  valid_until: string
  retrieved_at: string
  change_rules: Record<string, unknown>
}

export interface TravelSearchJob {
  id: string
  status: 'pending' | 'completed' | 'empty' | 'failed'
  source: string
  unavailable_code: string | null
  retrieved_at: string
  offers: TravelOffer[]
}

export interface TravelOrder {
  id: string
  order_no: string
  amount: string
  currency: string
  status: string
  payment_status: string
  fulfillment_status: FulfillmentStatus
  failure_code?: string | null
  created_at: string
}

export interface TravelOrderPassenger {
  name: string
  document_type: 'identity_card' | 'passport'
  document_number: string
  seat_preference: SeatPreference
}

export interface MockTransportTicket {
  id: string
  transport_type: 'train' | 'flight'
  status: 'pending' | 'issued' | 'failed'
  mock_ticket_no: string | null
  seat_assignments: Record<string, unknown>
  passenger_facts: Record<string, unknown>
  failure_code: string | null
}

export interface TravelOrderPayment {
  id: string
  payment_no: string
  amount: string
  currency: string
  status: string
  redirect_url: string | null
}

export interface TravelOrderRefund {
  id: string
  status: RefundStatus
  amount: string
  currency: string
}

export interface TravelOrderRefundRequest {
  amount: string
  currency: string
  reason: string
}

export interface TravelSearchRequest {
  search_type: SearchType
  origin: string
  destination: string
  depart_date: string
  passenger_count: number
}

export function createTravelSearch(payload: TravelSearchRequest) {
  return api.post<TravelSearchJob>('/travel-search-jobs', payload, { headers: { 'Idempotency-Key': newClientId() } })
}

export function createTravelOrder(offerId: string, passengers: TravelOrderPassenger[] = []) {
  return api.post<TravelOrder>('/travel-orders', { offer_id: offerId, passengers }, { headers: { 'Idempotency-Key': newClientId() } })
}

export function fetchTravelOrders() {
  return api.get<TravelOrder[]>('/travel-orders')
}

export function fetchMockTransportTicket(orderId: string) {
  return api.get<MockTransportTicket>(`/travel-orders/${orderId}/mock-ticket`)
}

export function createTravelOrderPayment(orderId: string, idempotencyKey: string) {
  return api.post<TravelOrderPayment>(
    `/travel-orders/${orderId}/payments`,
    { provider: 'alipay_sandbox' },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}

export function queryTravelOrderPayment(orderId: string) {
  return api.post<TravelOrder>(`/travel-orders/${orderId}:query-payment`)
}

export function createTravelOrderRefund(orderId: string, payload: TravelOrderRefundRequest, idempotencyKey: string) {
  return api.post<TravelOrderRefund>(
    `/travel-orders/${orderId}/refunds`,
    payload,
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}
