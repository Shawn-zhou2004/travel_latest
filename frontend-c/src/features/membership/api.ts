import { api } from '@/services/api'

export interface MembershipPlan {
  id: string
  code: string
  name: string
  duration_days: number
  entitlement_codes: string[]
  status: 'published'
  created_at: string
  updated_at: string
  price_amount: string | number
  currency: string
  generation_quota: number
  assistant_quota: number
  purchasable: boolean
}

export interface EffectiveEntitlement {
  id: string
  membership_id: string
  code: string
  valid_from: string
  valid_until: string
  status: 'active'
}

export interface MembershipPurchase {
  id: string
  membership_plan_id: string
  plan_name: string
  amount: string | number
  currency: string
  duration_days: number
  generation_quota: number
  assistant_quota: number
  status: string
  payment_status: string
  authorization_status: string
  payment_no: string | null
  paid_at: string | null
  authorized_at: string | null
  valid_from: string | null
  valid_until: string | null
  created_at: string
}

export type MembershipQrAttemptStatus = 'pending' | 'paying' | 'paid' | 'expired' | 'closed' | 'failed' | null

export interface MembershipQrPayment {
  attempt_id: string | null
  payment_no: string | null
  qr_code: string | null
  expires_at: string | null
  status: MembershipQrAttemptStatus
  payment_status: string
  authorization_status: string
}

export async function listPublishedMembershipPlans() {
  const { data } = await api.get<MembershipPlan[]>('/membership-plans')
  return data
}

export async function listMyEffectiveEntitlements() {
  const { data } = await api.get<EffectiveEntitlement[]>('/users/me/entitlements')
  return data
}

export async function createMembershipPurchase(membershipPlanId: string, idempotencyKey: string) {
  const { data } = await api.post<MembershipPurchase>('/membership-purchases', { membership_plan_id: membershipPlanId }, { headers: { 'Idempotency-Key': idempotencyKey } })
  return data
}

export async function createMembershipQrPayment(purchaseId: string) {
  const { data } = await api.post<MembershipQrPayment>(`/membership-purchases/${purchaseId}/qr-payments`)
  return data
}

export async function getCurrentMembershipQrPayment(purchaseId: string) {
  const { data } = await api.get<MembershipQrPayment>(`/membership-purchases/${purchaseId}/qr-payments/current`)
  return data
}

export async function refreshMembershipQrPayment(purchaseId: string) {
  const { data } = await api.post<MembershipQrPayment>(`/membership-purchases/${purchaseId}/qr-payments:refresh`)
  return data
}

export async function queryMembershipPurchasePayment(purchaseId: string) {
  const { data } = await api.post<MembershipQrPayment>(`/membership-purchases/${purchaseId}:query-payment`)
  return data
}

export async function listMyMembershipPurchases() {
  const { data } = await api.get<{ items: MembershipPurchase[] }>('/membership-purchases/mine')
  return data.items
}
