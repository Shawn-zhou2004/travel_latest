import { api } from '@/services/api'
import type { DestinationOption } from '@/features/itineraries/destinationsApi'

export type CompanionPlanStatus = 'open' | 'full' | 'closed' | 'cancelled' | 'completed'
export type CompanionPlanReviewStatus = 'pending_review' | 'approved' | 'rejected'
export type CompanionTripKind = 'trip' | 'activity'
export type CompanionPace = 'slow' | 'balanced' | 'packed'
export type CompanionApplicationStatus = 'pending' | 'accepted' | 'rejected' | 'withdrawn'
export type CompanionViewerRole = 'owner' | 'member' | 'applicant' | 'public'

export interface CompanionPlanSummary {
  id: string
  title: string
  city_code: string | null
  trip_kind: CompanionTripKind | null
  start_date: string | null
  end_date: string | null
  party_size: number | null
  accepted_count: number
  budget_min: number | string | null
  budget_max: number | string | null
  currency: string | null
  travel_pace: CompanionPace | null
  interest_tags: string[]
  intro_text: string | null
  route_count: number
  cover_candidate: string | null
  status: CompanionPlanStatus
  application_status: CompanionApplicationStatus | null
  viewer_role: CompanionViewerRole
}

export interface CompanionPlanMember {
  display_name: string
  avatar_asset_id: string | null
  role: 'owner' | 'member'
}

export interface ItinerarySnapshot {
  title?: string
  days?: Array<{
    date?: string
    title?: string
    events?: Array<{
      title?: string
      poi_snapshot?: { name?: string }
    }>
  }>
}

export interface CompanionPlanDetail extends CompanionPlanSummary {
  review_status?: CompanionPlanReviewStatus
  members: CompanionPlanMember[]
  itinerary_id?: string
  conversation_id?: string
  protected_itinerary?: ItinerarySnapshot
}

export interface CompanionPlanPage {
  items: CompanionPlanSummary[]
  next_cursor: string | null
}

export interface CompanionPlanFilters {
  city_code?: string
  start_date?: string
  end_date?: string
  trip_kind?: CompanionTripKind
  travel_pace?: CompanionPace
  tags?: string[]
  has_slots?: boolean
  cursor?: string
  limit?: number
}

export interface CompanionApplication {
  id: string
  request_id: string
  applicant_id: string
  message: string
  status: CompanionApplicationStatus
  conversation_id: string | null
  applicant_display_name?: string | null
}

export interface CompanionApplicationAcceptance {
  application: CompanionApplication
  conversation_id: string
  group_name?: string | null
  group_avatar_asset_id?: string | null
  plan_status: CompanionPlanStatus
  accepted_count: number
}

export interface CompanionPlanUpdate {
  title?: string
  city_code?: string | null
  party_size?: number
  budget_min?: number | null
  budget_max?: number | null
  currency?: string | null
  travel_pace?: CompanionPace
  interest_tags?: string[]
  intro_text?: string
}

export interface CompanionPlanPublishPayload {
  party_size: number
  budget_min: number | null
  budget_max: number | null
  currency: string | null
  travel_pace: CompanionPace
  interest_tags: string[]
  intro_text: string
  city_code?: string
}

export interface CompanionCitySnapshot {
  destination?: { city_code?: string | null }
  days?: Array<{ events?: Array<{ poi_snapshot?: { city?: string | null } }> }>
}

export interface CompanionActivityPublishPayload extends CompanionPlanPublishPayload {
  title: string
  city_code: string
  activity_date: string
  starts_at: string
  ends_at: string
  poi_id: string
}

export interface CompanionWorkspaceSummary {
  id: string
  status: CompanionPlanStatus
  review_status?: CompanionPlanReviewStatus
  party_size: number
  accepted_count: number
  role: 'owner' | 'member' | 'collaborator'
  conversation_id: string | null
}

export const companionInterestTags = ['citywalk', 'food', 'photography', 'nature', 'museum', 'hiking', 'coffee', 'culture'] as const

export const companionInterestTagLabels: Record<string, string> = {
  citywalk: '城市漫游',
  food: '美食探索',
  photography: '摄影出片',
  nature: '自然风光',
  museum: '博物馆',
  hiking: '徒步登山',
  coffee: '咖啡小馆',
  culture: '人文历史',
}

export function companionInterestTagLabel(tag: string) {
  return companionInterestTagLabels[tag] ?? tag
}

export function canPublishPlan(input: { partySize: number; pace: CompanionPace | ''; tags: string[]; intro: string }) {
  return input.partySize >= 2 && input.partySize <= 12 && Boolean(input.pace) && input.tags.length > 0 && input.tags.length <= 8 && Boolean(input.intro.trim())
}

function validCityCode(value: string | null | undefined) {
  return typeof value === 'string' && /^\d{6}$/.test(value) ? value : null
}

function companionCitySnapshot(snapshot: unknown): CompanionCitySnapshot | undefined {
  return typeof snapshot === 'object' && snapshot !== null ? snapshot as CompanionCitySnapshot : undefined
}

export function inferredCompanionCityCode(snapshot: unknown) {
  const citySnapshot = companionCitySnapshot(snapshot)
  const destinationCityCode = validCityCode(citySnapshot?.destination?.city_code)
  if (destinationCityCode) return destinationCityCode
  for (const day of citySnapshot?.days ?? []) {
    for (const event of day.events ?? []) {
      const poiCityCode = validCityCode(event.poi_snapshot?.city)
      if (poiCityCode) return poiCityCode
    }
  }
  return null
}

export function requiresDestinationSelection(snapshot: unknown) {
  return inferredCompanionCityCode(snapshot) === null
}

export function publishPayload(form: Omit<CompanionPlanPublishPayload, 'city_code'>, destination: Pick<DestinationOption, 'city_code'> | null, inferredCityCode?: string | null): CompanionPlanPublishPayload {
  const cityCode = destination?.city_code ?? inferredCityCode ?? null
  return cityCode ? { ...form, city_code: cityCode } : form
}

export function remainingSeats(plan: Pick<CompanionPlanSummary, 'accepted_count' | 'party_size'>) {
  return Math.max(0, (plan.party_size ?? plan.accepted_count) - plan.accepted_count)
}

export function formatBudget(plan: Pick<CompanionPlanSummary, 'budget_min' | 'budget_max' | 'currency'>) {
  if (plan.budget_min === null || plan.budget_max === null || !plan.currency) return '预算待定'
  return `${plan.currency} ${plan.budget_min}-${plan.budget_max}`
}

export function acceptedDestination(result: Pick<CompanionApplicationAcceptance, 'conversation_id'>) {
  return `/messages/${result.conversation_id}`
}

export async function listCompanionPlans(filters: CompanionPlanFilters = {}) {
  const { data } = await api.get<CompanionPlanPage>('/companion-requests', { params: filters })
  return data
}

export async function getCompanionPlan(requestId: string) {
  const { data } = await api.get<CompanionPlanDetail>(`/companion-requests/${requestId}`)
  return data
}

export async function updateCompanionPlan(requestId: string, body: CompanionPlanUpdate) {
  const { data } = await api.patch<CompanionPlanDetail>(`/companion-requests/${requestId}`, body)
  return data
}

export async function publishCompanionPlan(itineraryId: string, body: CompanionPlanPublishPayload) {
  const { data } = await api.post<CompanionPlanDetail>(`/itineraries/${itineraryId}/companion-requests`, body)
  return data
}

export async function publishCompanionActivity(body: CompanionActivityPublishPayload) {
  const { data } = await api.post<CompanionPlanDetail>('/companion-requests:activity', body)
  return data
}

export async function applyToCompanionPlan(requestId: string, message: string) {
  const { data } = await api.post<Pick<CompanionApplication, 'id' | 'status'>>(`/companion-requests/${requestId}/applications`, { message })
  return data
}

export async function listCompanionPlanApplications(requestId: string) {
  const { data } = await api.get<CompanionApplication[]>(`/companion-requests/${requestId}/applications`)
  return data
}

export async function listMyCompanionApplications() {
  const { data } = await api.get<CompanionApplication[]>('/companion-applications/mine')
  return data
}

export async function withdrawCompanionApplication(applicationId: string) {
  const { data } = await api.post<CompanionApplication>(`/companion-applications/${applicationId}:withdraw`)
  return data
}

export async function acceptCompanionApplication(applicationId: string, groupName?: string, groupAvatarAssetId?: string) {
  const body = groupName !== undefined || groupAvatarAssetId !== undefined ? { group_name: groupName, group_avatar_asset_id: groupAvatarAssetId } : undefined
  const { data } = await api.post<CompanionApplicationAcceptance>(`/companion-applications/${applicationId}:accept`, body)
  return data
}

export async function rejectCompanionApplication(applicationId: string) {
  const { data } = await api.post<Pick<CompanionApplication, 'id' | 'status' | 'conversation_id'>>(`/companion-applications/${applicationId}:reject`)
  return data
}

async function transitionCompanionPlan(requestId: string, action: 'close' | 'reopen' | 'cancel' | 'leave' | 'complete') {
  const { data } = await api.post<CompanionPlanDetail>(`/companion-requests/${requestId}:${action}`)
  return data
}

export const closeCompanionPlan = (requestId: string) => transitionCompanionPlan(requestId, 'close')
export const reopenCompanionPlan = (requestId: string) => transitionCompanionPlan(requestId, 'reopen')
export const cancelCompanionPlan = (requestId: string) => transitionCompanionPlan(requestId, 'cancel')
export const leaveCompanionPlan = (requestId: string) => transitionCompanionPlan(requestId, 'leave')
export const completeCompanionPlan = (requestId: string) => transitionCompanionPlan(requestId, 'complete')

export async function removeCompanionMember(requestId: string, userId: string) {
  const { data } = await api.delete<CompanionPlanDetail>(`/companion-requests/${requestId}/members/${userId}`)
  return data
}
