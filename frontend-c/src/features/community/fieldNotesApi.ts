import { api } from '@/services/api'
import type { ItineraryRecord, ItinerarySnapshot } from '@/features/itineraries/api'
import { getPrivateImageUrl } from '@/features/media/api'
import { newClientId } from '@/services/id'

export type FieldNoteStatus = 'draft' | 'pending_review' | 'published' | 'hidden' | 'rejected'
export type FieldNoteSort = 'latest' | 'recommended'

export interface FieldNoteSummary {
  id: string
  author_id: string
  title: string
  body_text: string
  city_code: string | null
  status: FieldNoteStatus
  published_at: string | null
  recap_text: string
  itinerary_snapshot: ItinerarySnapshot
  cover_media_id: string | null
  media_ids: string[]
  day_count: number
  stop_count: number
  copy_count: number
}

export interface FieldNoteDetail extends FieldNoteSummary {}

export interface FieldNoteAuthorStatus extends FieldNoteSummary {
  moderation_reason: string | null
}

export interface FieldNotePage {
  items: FieldNoteSummary[]
  next_cursor: string | null
}

export interface FieldNoteCopyResult {
  itinerary: ItineraryRecord
  source_post_id: string
  idempotent: boolean
}

export interface RouteMeta {
  days: number
  stops: number
}

export interface ListFieldNotesParams {
  city_code?: string
  q?: string
  sort?: FieldNoteSort
  cursor?: string
  limit?: number
}

export function canPublish(input: {
  versionNo: number | null
  title: string
  recap: string
  coverId: string
  mediaIds: string[]
}) {
  return input.versionNo !== null
    && Boolean(input.title.trim())
    && Boolean(input.recap.trim())
    && Boolean(input.coverId)
    && input.mediaIds.length > 0
    && input.mediaIds.includes(input.coverId)
}

export async function listFieldNotes(params: ListFieldNotesParams = {}) {
  const { data } = await api.get<FieldNotePage>('/posts', {
    params: { content_type: 'itinerary', ...params },
  })
  return data
}

export async function getFieldNote(postId: string) {
  const { data } = await api.get<FieldNoteDetail>(`/posts/${postId}`)
  return data
}

export async function listMyFieldNotes() {
  const { data } = await api.get<FieldNoteAuthorStatus[]>('/posts/me/field-notes')
  return data
}

export async function copyFieldNote(postId: string, idempotencyKey: string = newClientId()) {
  const { data } = await api.post<FieldNoteCopyResult>(`/posts/${postId}:copy-itinerary`, {}, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
  return data
}

export function routeMeta(snapshot: ItinerarySnapshot): RouteMeta {
  return {
    days: snapshot.days.length,
    stops: snapshot.days.reduce((total, day) => total + day.events.length, 0),
  }
}

export function copyDestination(result: FieldNoteCopyResult) {
  return `/itineraries/${result.itinerary.id}`
}

export async function resolveFieldNoteImage(assetId: string) {
  const downloadUrl = await getPrivateImageUrl(assetId)
  const response = await fetch(downloadUrl, { credentials: 'omit' })
  if (!response.ok) throw new Error('图片暂时无法读取。')
  return URL.createObjectURL(await response.blob())
}
