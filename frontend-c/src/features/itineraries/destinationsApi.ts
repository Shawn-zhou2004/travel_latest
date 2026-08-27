import { api } from '@/services/api'

export interface DestinationOption {
  id: string
  name: string
  display_address: string
  city_code: string
  kind: 'city' | 'district' | 'scenic_area'
}

export type PreferenceTag =
  | '经典必玩'
  | '吃吃喝喝'
  | '小众探索'
  | '拍照出片'
  | '逛街购物'
  | 'citywalk'
  | '自然风光'
  | '文艺展览'
  | '历史古建'

export interface ManualPlanRequest {
  destination: DestinationOption
  start_date: string
  end_date: string
  title?: string
}

export interface ItinerarySummary {
  id: string
  owner_id: string
  title: string
  start_date: string
  end_date: string
  version: number
  status: string
  created_at: string
  updated_at: string
}

export async function searchDestinations(query: string): Promise<DestinationOption[]> {
  const { data } = await api.get<{ items: DestinationOption[] }>('/destinations', { params: { query } })
  return data.items
}

export async function createManualPlan(request: ManualPlanRequest): Promise<ItinerarySummary> {
  const { data } = await api.post<ItinerarySummary>('/itineraries:manual-plan', request)
  return data
}
