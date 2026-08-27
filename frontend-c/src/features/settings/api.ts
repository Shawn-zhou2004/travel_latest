import { api } from '@/services/api'

export type BudgetLevel = 'economy' | 'balanced' | 'premium'
export type TravelPace = 'relaxed' | 'balanced' | 'packed'
export type TravelerType = 'solo' | 'couple' | 'friends' | 'family'
export type ProfileVisibility = 'private' | 'collaborators'
export type InterestTag =
  | '经典必玩'
  | '吃吃喝喝'
  | '小众探索'
  | '拍照出片'
  | '逛街购物'
  | 'citywalk'
  | '自然风光'
  | '文艺展览'
  | '历史古建'

export interface UserSettings {
  departure_city: string | null
  budget_level: BudgetLevel
  travel_pace: TravelPace
  interest_tags: InterestTag[]
  traveler_type: TravelerType
  notifications_enabled: boolean
  order_notifications: boolean
  itinerary_notifications: boolean
  community_notifications: boolean
  profile_visibility: ProfileVisibility
}

export type SettingsUpdate = Partial<UserSettings>

export const interestTags: { value: InterestTag; label: string }[] = [
  { value: '经典必玩', label: '经典必玩' },
  { value: '吃吃喝喝', label: '吃吃喝喝' },
  { value: '小众探索', label: '小众探索' },
  { value: '拍照出片', label: '拍照出片' },
  { value: '逛街购物', label: '逛街购物' },
  { value: 'citywalk', label: 'Citywalk' },
  { value: '自然风光', label: '自然风光' },
  { value: '文艺展览', label: '文艺展览' },
  { value: '历史古建', label: '历史古建' },
]

export function getMySettings() {
  return api.get<UserSettings>('/users/me/settings').then(({ data }) => data)
}

export function updateMySettings(changes: SettingsUpdate) {
  return api.patch<UserSettings>('/users/me/settings', changes).then(({ data }) => data)
}
