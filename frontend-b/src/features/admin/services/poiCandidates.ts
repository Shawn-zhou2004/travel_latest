import { api } from '@/services/api'

export const poiCandidateTags = ['经典必玩', '吃吃喝喝', '小众探索', '拍照出片', '逛街购物', 'citywalk', '自然风光', '文艺展览', '历史古建'] as const
export type PoiCandidateTag = typeof poiCandidateTags[number]
export type PoiCandidateStatus = 'pending_review' | 'approved' | 'rejected' | 'retired'

export interface PoiCandidate {
  id: string
  poi_id: string
  name: string
  address: string
  city_code: string
  amap_type: string | null
  tags: PoiCandidateTag[]
  status: PoiCandidateStatus
  admin_weight: number
  discovery_count: number
  confirmed_itinerary_count: number
  review_reason: string | null
  reviewed_at: string | null
  official_knowledge_source_id: string | null
}

interface Page<T> { items: T[] }

export async function listPoiCandidates(status?: PoiCandidateStatus, city_code?: string) {
  const { data } = await api.get<Page<PoiCandidate>>('/admin/ai/poi-candidates', { params: { status, city_code, limit: 50 } })
  return data.items
}

export async function decidePoiCandidate(id: string, payload: { status: 'approved' | 'rejected' | 'retired'; tags?: PoiCandidateTag[]; admin_weight?: number; reason?: string }) {
  const { data } = await api.patch<PoiCandidate>(`/admin/ai/poi-candidates/${id}`, payload)
  return data
}
