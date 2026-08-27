import { api } from '@/services/api'

export type MembershipPurchaseStatus = 'pending_payment' | 'paid' | 'closed'

export interface AdminMembershipPurchase {
  id: string
  user_id: string
  membership_plan_id: string
  plan_name: string
  amount: string | number
  currency: string
  duration_days: number
  generation_quota: number
  assistant_quota: number
  status: MembershipPurchaseStatus
  payment_status: 'pending' | 'paying' | 'paid' | 'failed'
  authorization_status: 'pending' | 'authorized' | 'failed'
  failure_code: string | null
  paid_at: string | null
  authorized_at: string | null
  valid_from: string | null
  valid_until: string | null
  created_at: string
}

interface MembershipPurchasePage {
  items: AdminMembershipPurchase[]
}

export async function listMembershipPurchases(status?: MembershipPurchaseStatus) {
  const { data } = await api.get<MembershipPurchasePage>('/admin/membership-purchases', { params: status ? { status } : {} })
  return data.items
}

export async function retryMembershipPurchaseAuthorization(purchaseId: string) {
  const { data } = await api.post<AdminMembershipPurchase>(`/admin/membership-purchases/${purchaseId}:retry-authorization`)
  return data
}
