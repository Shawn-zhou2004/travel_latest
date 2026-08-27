import { api } from '@/services/api'
import type { FieldNoteDetail } from '@/features/community/fieldNotesApi'
import type { CompanionWorkspaceSummary } from '@/features/community/companionPlansApi'

export type { CompanionWorkspaceSummary }

export interface ItineraryEvent {
  id?: string
  poi_id: string
  poi_snapshot: { name?: string; address?: string; source_updated_at?: string; location?: { longitude: number; latitude: number } }
  starts_at: string | null
  ends_at: string | null
  display_order: number
  notes: string | null
}

export interface RouteSegment { display_order: number; travel_mode: string; distance_meters: number | null; duration_seconds: number | null; route_snapshot: { polyline?: { longitude: number; latitude: number }[] } | null }
export interface RouteCalculation { id: string; status: 'queued' | 'calculating' | 'completed' | 'failed'; error_code: string | null }
export interface ItineraryDay { id?: string; day_date: string; display_order: number; events: ItineraryEvent[]; route_segments?: RouteSegment[]; route_calculation?: RouteCalculation | null }
export interface ItinerarySnapshot { title: string; start_date: string; end_date: string; days: ItineraryDay[] }
export interface RouteCalculationJob extends RouteCalculation { day_id: string; created_at: string; updated_at: string; completed_at: string | null }
export interface OperationResult { code: string; current_version: number | null; snapshot: ItinerarySnapshot | null; idempotent: boolean; route_job?: RouteCalculationJob | null }

export interface ItineraryRecord {
  id: string
  owner_id: string
  title: string
  start_date: string
  end_date: string
  version: number
  status: string
  created_at: string
  updated_at: string
  source_post_id: string | null
  access_role?: ItineraryAccessRole | null
}

export type ItineraryAccessRole = 'owner' | 'editor' | 'viewer'
export interface ItineraryDetail extends ItineraryRecord { snapshot: ItinerarySnapshot; access_role: ItineraryAccessRole }
export interface ItineraryVersion { id: string; version_no: number; source: string; created_at: string }
export interface ItineraryVersionDetail extends ItineraryVersion { snapshot: ItinerarySnapshot }
export interface ShareToken { id: string; share_url: string; token: string; expires_at: string | null }
export interface Collaborator { id: string; user_id: string; role: 'viewer' | 'editor'; invite_status: 'pending' | 'accepted' | 'revoked' }
export interface FieldNotePublishRequest { version_no: number; title: string; recap_text: string; cover_media_id: string; media_ids: string[] }

export interface POIRecord { id: string; name: string; address: string; longitude: number; latitude: number; city: string | null; type_name: string | null }
export interface MapClientConfig { js_api_key: string | null; service_host: string }

export async function createItinerary(payload: { title: string; start_date: string; end_date: string }) {
  const { data } = await api.post<ItineraryRecord>('/itineraries', payload)
  return data
}

export async function listItineraries() {
  const { data } = await api.get<ItineraryRecord[]>('/itineraries')
  return data
}

export async function getItinerary(itineraryId: string) {
  const { data } = await api.get<ItineraryDetail>(`/itineraries/${itineraryId}`)
  return data
}

export async function deleteItinerary(itineraryId: string) {
  await api.delete(`/itineraries/${itineraryId}`)
}

export async function getCompanionWorkspace(itineraryId: string) {
  const { data } = await api.get<CompanionWorkspaceSummary | null>(`/itineraries/${itineraryId}/companion-workspace`)
  return data
}

export async function listItineraryVersions(itineraryId: string) {
  const { data } = await api.get<ItineraryVersion[]>(`/itineraries/${itineraryId}/versions`)
  return data
}

export async function getItineraryVersion(itineraryId: string, versionNo: number) {
  const { data } = await api.get<ItineraryVersionDetail>(`/itineraries/${itineraryId}/versions/${versionNo}`)
  return data
}

export async function publishFieldNote(itineraryId: string, payload: FieldNotePublishRequest) {
  const { data } = await api.post<FieldNoteDetail>(`/itineraries/${itineraryId}/field-notes`, payload)
  return data
}

export async function getRouteCalculation(itineraryId: string, jobId: string) {
  const { data } = await api.get<RouteCalculationJob>(`/itineraries/${itineraryId}/route-calculations/${jobId}`)
  return data
}

export async function getSharedItinerary(itineraryId: string, shareToken: string) {
  const { data } = await api.get<Omit<ItineraryDetail, 'owner_id' | 'created_at' | 'updated_at'>>(`/itineraries/${itineraryId}/shared`, { params: { share_token: shareToken } })
  return data
}

export async function createShareToken(itineraryId: string) {
  const { data } = await api.post<ShareToken>(`/itineraries/${itineraryId}/share-tokens`, {})
  return data
}

export async function inviteCollaborator(itineraryId: string, userId: string, role: 'viewer' | 'editor') {
  const { data } = await api.post<Collaborator>(`/itineraries/${itineraryId}/collaborators`, { user_id: userId, role })
  return data
}

export async function acceptCollaborator(itineraryId: string, collaboratorId: string) {
  const { data } = await api.post<Collaborator>(`/itineraries/${itineraryId}/collaborators/${collaboratorId}:accept`)
  return data
}

export async function searchPOIs(keywords: string, city?: string) {
  const { data } = await api.get<POIRecord[]>('/map/pois', { params: { keywords, city: city || undefined } })
  return data
}

export async function getMapClientConfig() {
  const { data } = await api.get<MapClientConfig>('/map/client-config')
  return data
}

export async function applyItineraryOperation(
  itineraryId: string, version: number, operationId: string, operationType: string, payload: Record<string, unknown>,
) {
  const { data } = await api.post<OperationResult>(`/itineraries/${itineraryId}:operations`, { operation_type: operationType, payload }, {
    headers: { 'If-Match-Version': version, 'X-Operation-ID': operationId },
  })
  return data
}

export async function removeItineraryDay(itineraryId: string, version: number, operationId: string, dayId: string) {
  const { data } = await api.post<OperationResult>(`/itineraries/${itineraryId}:operations`, {
    operation_type: 'remove_day', payload: { day_id: dayId },
  }, {
    headers: { 'If-Match-Version': version, 'X-Operation-ID': operationId },
  })
  return data
}
