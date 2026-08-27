import { api } from '@/services/api'

export interface KnowledgeSource {
  id: string
  source_type: 'rule' | 'template' | 'poi'
  title: string
  body_text: string
  city_code: string | null
  poi_id: string | null
  language: string
  status: 'draft' | 'pending_review' | 'indexing' | 'indexed' | 'removing' | 'failed' | 'rejected' | 'inactive'
  review_reason: string | null
  indexed_at: string | null
  index_error: string | null
  removal_error: string | null
  created_at: string
  updated_at: string
}

export interface GenerationAuditItem { id: string; city_code: string; status: string; progress: number; outcome: string | null; error_code: string | null; message: string | null; preview_id: string | null; created_at: string; updated_at: string }
export interface PoiImportJob { id: string; city_code: string; keywords: string[]; status: 'queued' | 'running' | 'succeeded' | 'failed'; imported_count: number; skipped_count: number; error_message: string | null; created_at: string; updated_at: string }
export interface StructuredKnowledgeImportEntry { source_type: 'rule' | 'template'; title: string; body_text: string }
export interface StructuredKnowledgeImportJob { id: string; city_code: string; entries: StructuredKnowledgeImportEntry[]; status: 'queued' | 'running' | 'succeeded' | 'failed'; imported_count: number; skipped_count: number; error_message: string | null; created_at: string; updated_at: string }
export interface AiMetrics { generation: { total: number; failed: number; awaiting_confirmation: number }; knowledge: { indexed: number; failed: number; pending_review: number; indexing: number }; imports: { poi_failed: number; structured_failed: number } }
export interface AiWorkflowHealth { generation_jobs: AiWorkflowHealthCategory; export_tasks: AiWorkflowHealthCategory; outbox: AiOutboxHealth; worker: AiWorkerHeartbeatHealth }
export interface AiWorkflowHealthCategory { queued: number; running: number; failed: number; most_recent_at: string | null }
export interface AiOutboxHealth { unprocessed: number; retrying: number; dead_letter: number; most_recent_at: string | null }
export interface AiWorkerHeartbeatHealth { status: 'healthy' | 'stale' | 'unavailable'; last_heartbeat_at: string | null }
export interface RetrievalPreviewCitation { document_id: string; chunk_id: string; source_type: string; source_id: string; city_code: string | null; poi_id: string | null; source_updated_at: string }
export interface RetrievalPreviewContext { rank: number; score: number; content: string; citation: RetrievalPreviewCitation }
export interface RetrievalPreview { status: 'available' | 'no_results' | 'clarification_required' | 'unavailable'; message: string | null; contexts: RetrievalPreviewContext[] }
export interface WebSearchJob { id: string; requested_by: string; city_code: string; query: string; target_domain: 'official' | 'community'; status: 'queued' | 'running' | 'succeeded' | 'failed'; provider_name: string | null; error_code: string | null; error_message: string | null; result_count: number; created_at: string; updated_at: string }
export interface WebSearchCandidate { id: string; job_id: string; title: string; excerpt: string; source_url: string; source_host: string; published_at: string | null; fetched_at: string | null; city_code: string; target_domain: 'official' | 'community'; status: 'needs_human_review' | 'approved' | 'rejected' | 'ingested' | 'failed'; review_reason: string | null; reviewed_by: string | null; reviewed_at: string | null; external_web_source_id: string | null; created_at: string; updated_at: string }
export interface ExternalWebKnowledgeSource { id: string; candidate_id: string; target_domain: 'official' | 'community'; title: string; body_text: string; city_code: string; source_url: string; source_host: string; published_at: string | null; fetched_at: string | null; status: 'draft' | 'pending_review' | 'indexing' | 'indexed' | 'removing' | 'failed' | 'rejected' | 'inactive'; review_reason: string | null; reviewed_by: string | null; reviewed_at: string | null; indexed_at: string | null; index_error: string | null; removal_error: string | null; created_at: string; updated_at: string }
export interface CommunityKnowledgeReview { id: string; post_id: string; status: 'pending' | 'approved' | 'rejected'; reason: string | null; reviewed_by: string | null; reviewed_at: string | null; created_at: string; updated_at: string; post_title: string; post_body_text: string; post_city_code: string | null; post_status: string }
export interface WebSearchJobCreate { city_code: string; query: string; target_domain: WebSearchJob['target_domain'] }
export type WebSearchCandidateDecision = { status: 'approved'; title: string; body_text: string } | { status: 'rejected'; reason: string }
export type ExternalWebKnowledgeSourceDecision = { status: 'approved'; reason?: string } | { status: 'rejected'; reason: string }
export type CommunityKnowledgeReviewDecision = { status: 'approved' | 'rejected'; reason: string }
interface Page<T> { items: T[]; next_cursor: string | null }

export async function listKnowledgeSources(status?: string) { const { data } = await api.get<Page<KnowledgeSource>>('/admin/ai/knowledge-sources', { params: { status, limit: 50 } }); return data.items }
export async function createKnowledgeSource(payload: Pick<KnowledgeSource, 'source_type' | 'title' | 'body_text' | 'city_code' | 'poi_id' | 'language'>) { const { data } = await api.post<KnowledgeSource>('/admin/ai/knowledge-sources', payload); return data }
export async function decideKnowledgeSource(id: string, status: 'indexed' | 'rejected' | 'inactive', reason: string) { const { data } = await api.patch<KnowledgeSource>(`/admin/ai/knowledge-sources/${id}`, { status, reason }); return data }
export async function listGenerationAudit(status?: string) { const { data } = await api.get<Page<GenerationAuditItem>>('/admin/ai/generation-jobs', { params: { status, limit: 50 } }); return data.items }
export async function createPoiImportJob(city_code: string, keywords: string[]) { const { data } = await api.post<PoiImportJob>('/admin/ai/poi-import-jobs', { city_code, keywords }); return data }
export async function listPoiImportJobs() { const { data } = await api.get<Page<PoiImportJob>>('/admin/ai/poi-import-jobs', { params: { limit: 20 } }); return data.items }
export async function retryPoiImportJob(jobId: string) { const { data } = await api.post<PoiImportJob>(`/admin/ai/poi-import-jobs/${jobId}/retry`); return data }
export async function createStructuredKnowledgeImportJob(city_code: string, entries: StructuredKnowledgeImportEntry[]) { const { data } = await api.post<StructuredKnowledgeImportJob>('/admin/ai/structured-knowledge-import-jobs', { city_code, entries }); return data }
export async function listStructuredKnowledgeImportJobs() { const { data } = await api.get<Page<StructuredKnowledgeImportJob>>('/admin/ai/structured-knowledge-import-jobs', { params: { limit: 20 } }); return data.items }
export async function retryStructuredKnowledgeImportJob(jobId: string) { const { data } = await api.post<StructuredKnowledgeImportJob>(`/admin/ai/structured-knowledge-import-jobs/${jobId}/retry`); return data }
export async function getAiMetrics() { const { data } = await api.get<AiMetrics>('/admin/ai/metrics'); return data }
export async function getAiWorkflowHealth() { const { data } = await api.get<AiWorkflowHealth>('/admin/ai/workflow-health'); return data }
export async function previewRetrieval(city_code: string, query: string) { const { data } = await api.post<RetrievalPreview>('/admin/ai/retrieval-preview', { city_code, query }); return data }
export async function createWebSearchJob(payload: WebSearchJobCreate) { const { data } = await api.post<WebSearchJob>('/admin/ai/websearch-jobs', payload); return data }
export async function listWebSearchJobs(status?: WebSearchJob['status']) { const { data } = await api.get<Page<WebSearchJob>>('/admin/ai/websearch-jobs', { params: { status, limit: 50 } }); return data.items }
export async function listWebSearchCandidates(jobId: string, status?: WebSearchCandidate['status']) { const { data } = await api.get<Page<WebSearchCandidate>>(`/admin/ai/websearch-jobs/${jobId}/candidates`, { params: { status, limit: 50 } }); return data.items }
export async function decideWebSearchCandidate(candidateId: string, payload: WebSearchCandidateDecision) { const { data } = await api.patch<WebSearchCandidate>(`/admin/ai/websearch-candidates/${candidateId}`, payload); return data }
export async function listExternalWebKnowledgeSources(status?: ExternalWebKnowledgeSource['status']) { const { data } = await api.get<Page<ExternalWebKnowledgeSource>>('/admin/ai/external-web-knowledge-sources', { params: { status, limit: 50 } }); return data.items }
export async function decideExternalWebKnowledgeSource(sourceId: string, payload: ExternalWebKnowledgeSourceDecision) { const { data } = await api.patch<ExternalWebKnowledgeSource>(`/admin/ai/external-web-knowledge-sources/${sourceId}`, payload); return data }
export async function listCommunityKnowledgeReviews(status: CommunityKnowledgeReview['status'] = 'pending') { const { data } = await api.get<Page<CommunityKnowledgeReview>>('/admin/ai/community-knowledge-reviews', { params: { status, limit: 50 } }); return data.items }
export async function decideCommunityKnowledgeReview(postId: string, payload: CommunityKnowledgeReviewDecision) { const { data } = await api.patch<CommunityKnowledgeReview>(`/admin/ai/community-knowledge-reviews/${postId}`, payload); return data }
