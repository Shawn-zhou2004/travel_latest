import { api } from '@/services/api'

export type MembershipPlanStatus = 'draft' | 'published' | 'archived'

export interface MembershipPlan {
  id: string
  code: string
  name: string
  duration_days: number
  entitlement_codes: string[]
  status: MembershipPlanStatus
  created_at: string
  updated_at: string
  price_amount: string | number
  currency: 'CNY'
  generation_quota: number
  assistant_quota: number
  purchasable: boolean
}

export interface MembershipPlanCreate {
  code: string
  name: string
  duration_days: number
  entitlement_codes: string[]
  price_amount: string | number
  currency: 'CNY'
  generation_quota: number
  assistant_quota: number
  purchasable: false
}

export interface MembershipPlanUpdate {
  price_amount?: string | number
  currency?: 'CNY'
  duration_days?: number
  generation_quota?: number
  assistant_quota?: number
  purchasable?: boolean
}

interface MembershipPlanPage {
  items: MembershipPlan[]
  next_cursor: null
}

export async function listMembershipPlans(status?: MembershipPlanStatus) {
  const { data } = await api.get<MembershipPlanPage>('/admin/membership-plans', { params: { status } })
  return data.items
}

export async function createMembershipPlan(body: MembershipPlanCreate) {
  const { data } = await api.post<MembershipPlan>('/admin/membership-plans', body)
  return data
}

export async function updateMembershipPlan(planId: string, body: MembershipPlanUpdate) {
  const { data } = await api.patch<MembershipPlan>(`/admin/membership-plans/${planId}`, body)
  return data
}

export async function publishMembershipPlan(planId: string) {
  const { data } = await api.post<MembershipPlan>(`/admin/membership-plans/${planId}:publish`)
  return data
}

export async function archiveMembershipPlan(planId: string) {
  const { data } = await api.post<MembershipPlan>(`/admin/membership-plans/${planId}:archive`)
  return data
}
