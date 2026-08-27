import { api } from '@/services/api'

export type SearchIndexStatus = 'healthy' | 'empty' | 'unavailable' | 'degraded'
export type SearchIndexRebuildStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export interface SearchIndexInventoryItem { logical_name: string; index_name: string; status: SearchIndexStatus; document_count: number | null; message: string | null }
export interface SearchIndexInventoryResponse { items: SearchIndexInventoryItem[] }
export interface SearchIndexRebuildJob { id: string; index_name: string; requested_by: string; status: SearchIndexRebuildStatus; progress: number; error: string | null; created_at: string; updated_at: string; started_at: string | null; completed_at: string | null }

export async function listSearchIndexes() {
  const { data } = await api.get<SearchIndexInventoryResponse>('/admin/search-indexes')
  return data.items
}

export async function rebuildSearchIndex(index_name: string) {
  const { data } = await api.post<SearchIndexRebuildJob>('/admin/search-indexes:rebuild', { index_name })
  return data
}

export async function getSearchIndexRebuildJob(id: string) {
  const { data } = await api.get<SearchIndexRebuildJob>(`/admin/search-index-rebuild-jobs/${id}`)
  return data
}
