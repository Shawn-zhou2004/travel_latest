import { api } from '@/services/api'

export interface PageResult<T> {
  items: T[]
  next_cursor: string | null
}

export interface ModerationPost {
  id: string
  author_id: string
  content_type: string
  title: string
  body: string
  status: string
  moderation_reason?: string | null
  has_route_snapshot: boolean
  created_at: string
  updated_at: string
}

export interface Report {
  id: string
  reporter_id: string
  target_type: string
  target_id: string
  reason: string
  details?: string | null
  status: string
  resolution?: string | null
  created_at: string
}

export interface ProviderApplication {
  id: string
  provider_type: string
  legal_name: string
  contact_masked: string
  verification_status: string
  review_reason?: string | null
  member_count: number
  created_at: string
}

export interface CompanionRequest {
  id: string
  owner_id: string
  title: string
  destination: string
  trip_kind: 'trip' | 'activity' | null
  has_itinerary: boolean
  start_date: string | null
  end_date: string | null
  party_size: number | null
  accepted_count: number
  travel_pace: 'slow' | 'balanced' | 'packed' | null
  interest_tags: string[]
  intro_text: string | null
  description: string
  business_status: 'open' | 'full' | 'closed' | 'cancelled' | 'completed'
  status: string
  review_reason: string | null
  created_at: string
}

export interface TravelOrder {
  id: string
  order_no: string
  amount: string
  currency: string
  status: string
  payment_status: string
  fulfillment_status: string
  failure_code?: string | null
  created_at: string
}

function items<T>(data: PageResult<T> | T[]) {
  return Array.isArray(data) ? data : data.items
}

export async function listPosts(status = 'pending_review') {
  const { data } = await api.get<PageResult<ModerationPost>>('/admin/posts', { params: { status, limit: 50 } })
  return items(data)
}

export async function updatePost(id: string, status: string, moderation_reason: string) {
  return api.patch(`/admin/posts/${id}`, { status, moderation_reason })
}

export async function listReports(status = 'pending') {
  const { data } = await api.get<PageResult<Report>>('/admin/reports', { params: { status, limit: 50 } })
  return items(data)
}

export async function updateReport(id: string, status: string, resolution: string) {
  return api.patch(`/admin/reports/${id}`, { status, resolution })
}

export async function listCompanionRequests(status = 'pending_review') {
  const { data } = await api.get<PageResult<CompanionRequest>>('/admin/companion-requests', { params: { status, limit: 50 } })
  return items(data)
}

export async function updateCompanionRequest(id: string, status: string, review_reason: string) {
  return api.patch(`/admin/companion-requests/${id}`, { status, review_reason })
}

export async function listProviderApplications(status = 'pending_review') {
  const { data } = await api.get<PageResult<ProviderApplication>>('/admin/providers', { params: { status, limit: 50 } })
  return items(data)
}

export async function updateProvider(id: string, status: string, review_reason: string) {
  return api.patch(`/admin/providers/${id}`, { status, review_reason })
}

export async function listOrders(status?: string) {
  const { data } = await api.get<PageResult<TravelOrder>>('/admin/travel-orders', { params: { status, limit: 50 } })
  return items(data)
}

export async function queryOrderPayment(id: string) {
  const { data } = await api.post<TravelOrder>(`/travel-orders/${id}:query-payment`)
  return data
}
