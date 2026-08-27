import { api } from '@/services/api'
import type { TravelerType } from '@/features/settings/api'
import type { DestinationOption, PreferenceTag } from './destinationsApi'

export type GenerationJobStatus =
  | 'queued'
  | 'understanding'
  | 'resolving_destination'
  | 'retrieving'
  | 'retrieving_reviewed_sources'
  | 'searching_live_sources'
  | 'verifying_pois'
  | 'planning'
  | 'validating'
  | 'awaiting_confirmation'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export type GenerationJobOutcome = 'preview' | 'no_result' | 'clarification' | 'unavailable'

export const generationJobStatusLabels: Record<GenerationJobStatus, string> = {
  queued: '正在排队等待规划',
  understanding: '正在理解你的出行需求',
  resolving_destination: '正在确认目的地',
  retrieving: '正在检索旅行资料',
  retrieving_reviewed_sources: '正在检索平台已审核资料',
  searching_live_sources: '正在补充本次实时网络资料',
  verifying_pois: '正在核验地点信息',
  planning: '正在生成行程方案',
  validating: '正在校验行程方案',
  awaiting_confirmation: '行程方案已生成，等待确认',
  succeeded: '规划已完成',
  failed: '规划未完成',
  cancelled: '规划已取消',
}

export interface SmartPlanRequest {
  destination?: DestinationOption
  start_date: string
  end_date: string
  preference_tags?: PreferenceTag[]
  pace?: 'slow' | 'balanced' | 'fast' | null
  traveler_type?: TravelerType | null
  prompt: string
  must_visit_poi_ids?: string[]
  target_itinerary_id?: string | null
  base_version?: number | null
}

export type AiPlanningRequest = SmartPlanRequest

export interface GenerationJobResponse {
  id: string
  status: GenerationJobStatus
  progress: number
  outcome: GenerationJobOutcome | null
  error_code: string | null
  message: string | null
  preview_id: string | null
  target_itinerary_id: string | null
  created_at: string
  updated_at: string
}

export interface AiPreviewActivity {
  poi_id: string
  poi_name: string
  longitude: number
  latitude: number
  title: string
  estimated_cost: number
}

export interface AiPreviewDay { date: string; activities: AiPreviewActivity[] }
export interface AiPreview { id: string; generation_job_id: string; draft: { title: string; days: AiPreviewDay[] }; citations: { document_id: string; chunk_id: string; source_type: string; source_id: string; city_code: string; source_updated_at?: string; content: string }[]; prompt_version: string | null; model_version: string | null; created_at: string; target_itinerary_id?: string | null; base_version?: number | null }
export interface AiPreviewApplyResult { code: string; current_version: number | null; snapshot: unknown | null; idempotent: boolean }

export async function createGenerationJob(request: SmartPlanRequest, idempotencyKey: string) {
  const { data } = await api.post<GenerationJobResponse>('/generation-jobs', request, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
  return data
}

export async function getGenerationJob(jobId: string) {
  const { data } = await api.get<GenerationJobResponse>(`/generation-jobs/${jobId}`)
  return data
}

export async function listPendingGenerationPreviews() {
  const { data } = await api.get<GenerationJobResponse[]>('/generation-jobs')
  return data
}

export async function retryGenerationJob(jobId: string) {
  const { data } = await api.post<GenerationJobResponse>(`/generation-jobs/${jobId}/retry`)
  return data
}

export async function getGenerationPreview(jobId: string) {
  const { data } = await api.get<AiPreview>(`/generation-jobs/${jobId}/preview`)
  return data
}

export async function applyGenerationPreview(jobId: string, previewId: string, version: number, operationId: string) {
  const { data } = await api.post<AiPreviewApplyResult>(`/generation-jobs/${jobId}/preview/${previewId}:apply`, {}, {
    headers: { 'If-Match-Version': version, 'X-Operation-ID': operationId },
  })
  return data
}
